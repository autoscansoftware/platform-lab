"""Pod access for labctl: config, path safety, ssh runner, tar push/pull with verification. Standard library only."""
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

MAX_EXTEND_H = 12.0
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:_-]{0,252}$")
_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}$")


class LabError(RuntimeError):
    pass


def config_path():
    return Path(os.environ.get("LABCTL_CONFIG") or Path.home() / ".labctl.json")


def load_config(path=None):
    p = Path(path) if path else config_path()
    try:
        raw = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError) as e:
        raise LabError(f"cannot read config {p}: {e}")
    return validate_config(raw)


def validate_config(raw):
    cfg = {"port": 22, "user": "root", "self_destruct_hours": 4.0, "destroy_cmd": None, "identity_file": None}
    cfg.update(raw)
    if not _HOST.match(str(cfg.get("host") or "")):
        raise LabError("config: 'host' missing or invalid")
    if not _USER.match(str(cfg["user"])):
        raise LabError("config: invalid 'user'")
    if not isinstance(cfg["port"], int) or not 0 < cfg["port"] < 65536:
        raise LabError("config: invalid 'port'")
    root = str(cfg.get("remote_root") or "")
    if not root.startswith("/") or ".." in root.split("/") or root == "/":
        raise LabError("config: 'remote_root' must be an absolute path on the pod, not '/'")
    cfg["remote_root"] = root.rstrip("/")
    h = float(cfg["self_destruct_hours"])
    if not 0 < h <= MAX_EXTEND_H:
        raise LabError(f"config: self_destruct_hours must be 0 < h <= {MAX_EXTEND_H}")
    cfg["self_destruct_hours"] = h
    return cfg


def clean_rel(rel):
    """Remote paths are relative to the remote root: no absolute paths, no '..', no empty parts."""
    s = str(rel).replace("\\", "/").strip()
    if not s or s.startswith("/") or re.match(r"^[A-Za-z]:", s) or ".." in s.split("/"):
        raise LabError(f"remote path must be relative to the remote root, no '..': {rel!r}")
    parts = [x for x in s.split("/") if x not in ("", ".")]
    if not parts:
        raise LabError(f"remote path must be relative to the remote root, no '..': {rel!r}")
    return "/".join(parts)


def remote_abs(cfg, rel):
    return cfg["remote_root"] + "/" + clean_rel(rel)


def split_parent(rel):
    head, _, tail = rel.rpartition("/")
    return head, tail


def ssh_argv(cfg, remote_cmd):
    argv = ["ssh", "-p", str(cfg["port"]), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if cfg.get("identity_file"):
        argv += ["-i", str(cfg["identity_file"]), "-o", "IdentitiesOnly=yes"]
    return argv + [f"{cfg['user']}@{cfg['host']}", remote_cmd]


class SshRunner:
    """Real runner. run(cmd, stdin=None) -> (returncode, stdout bytes). Tests pass a fake with the same method."""

    def __init__(self, cfg, timeout=900):
        self.cfg, self.timeout = cfg, timeout

    def run(self, cmd, stdin=None):
        r = subprocess.run(ssh_argv(self.cfg, cmd), input=stdin, capture_output=True, timeout=self.timeout)
        return r.returncode, r.stdout

    def text(self, cmd):
        rc, out = self.run(cmd)
        return rc, out.decode("utf-8", "replace")


def build_push(cfg, rel):
    parent, name = split_parent(clean_rel(rel))
    d = shlex.quote(cfg["remote_root"] + ("/" + parent if parent else ""))
    return f"mkdir -p {d} && tar -xf - -C {d}", name


def build_pull(cfg, rel):
    parent, name = split_parent(clean_rel(rel))
    d = shlex.quote(cfg["remote_root"] + ("/" + parent if parent else ""))
    return f"tar -cf - -C {d} {shlex.quote(name)}"


def build_size(cfg, rel):
    p = shlex.quote(remote_abs(cfg, rel))
    return f"find -L {p} -type f -printf '%s\n' | awk '{{s+=$1; n++}} END {{print s+0, n+0}}'"


def parse_size(text):
    f = text.split()
    if len(f) != 2 or not all(x.isdigit() for x in f):
        raise LabError(f"unexpected size reply: {text!r}")
    return int(f[0]), int(f[1])


def tree_stats(path):
    p = Path(path)
    if p.is_file():
        return p.stat().st_size, 1
    files = [f for f in p.rglob("*") if f.is_file()]
    return sum(f.stat().st_size for f in files), len(files)


def push(runner, cfg, local, rel):
    src = Path(local)
    if not src.exists():
        raise LabError(f"local path not found: {local}")
    cmd, name = build_push(cfg, rel)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        t.add(str(src), arcname=name)
    rc, _ = runner.run(cmd, stdin=buf.getvalue())
    if rc != 0:
        raise LabError(f"push failed (exit {rc})")
    want = tree_stats(src)
    rc, out = runner.text(build_size(cfg, rel))
    got = parse_size(out) if rc == 0 else None
    if got != want:
        raise LabError(f"push verification failed: sent {want[0]} bytes/{want[1]} files, pod has {got}")
    return want


def _safe_members(t, name):
    for m in t.getmembers():
        parts = m.name.split("/")
        if m.name.startswith("/") or ".." in parts or parts[0] != name or m.issym() or m.islnk() or m.isdev():
            raise LabError(f"refusing unsafe archive member {m.name!r}")
    return t.getmembers()


def pull(runner, cfg, rel, local):
    rel = clean_rel(rel)
    rc, out = runner.text(build_size(cfg, rel))
    if rc != 0:
        raise LabError("cannot size remote path")
    want = parse_size(out)
    if want[1] == 0:
        raise LabError(f"nothing to pull at {rel!r} (missing or empty)")
    rc, data = runner.run(build_pull(cfg, rel))
    if rc != 0:
        raise LabError(f"pull failed (exit {rc})")
    name = split_parent(rel)[1]
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r") as t:
            t.extractall(tmp, members=_safe_members(t, name), **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        got = tree_stats(Path(tmp) / name)
        if got != want:
            raise LabError(f"pull verification failed: pod has {want[0]} bytes/{want[1]} files, received {got}")
        dst = Path(local)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = Path(tmp) / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    return want
