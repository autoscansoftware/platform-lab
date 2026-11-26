"""Lane (container) commands for labctl: resource split, docker run, jobs, status, self-destruct timer. Pure builders plus thin verbs."""
import re
import shlex
import time

import pod as P

DEFAULT_IMAGE = "ghcr.io/autoscansoftware/lab:latest"
NOVNC_PORT = 6080          # inside the container
HOST_PORT_BASE = 6080      # lane N is published on 127.0.0.1:(base+N) on the pod
MAX_LANES = 16
_LANE = re.compile(r"^lane-([1-9][0-9]?)$")
_JOB = re.compile(r"^(lane-[1-9][0-9]?)-[0-9a-f]{8,}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?$")


def lane_name(i):
    return f"lane-{i}"


def valid_lane(name):
    if not _LANE.match(str(name)):
        raise P.LabError(f"lane name must look like lane-1..lane-{MAX_LANES}, got {name!r}")
    return name


def valid_job(job):
    if not _JOB.match(str(job)):
        raise P.LabError(f"bad job id {job!r}")
    return job


def lane_of(job):
    return _JOB.match(valid_job(job)).group(1)


def host_port(lane):
    return HOST_PORT_BASE + int(_LANE.match(valid_lane(lane)).group(1))


def split_resources(cpus, mem_mb, n):
    """Split the pod's CPUs and RAM evenly over n lanes (each lane gets its share, never zero)."""
    if not 1 <= n <= MAX_LANES:
        raise P.LabError(f"lane count must be 1..{MAX_LANES}")
    if cpus < 1 or mem_mb < 256 * n:
        raise P.LabError("pod too small for that many lanes")
    return round(cpus / n, 2), mem_mb // n


def build_up(cfg, i, image, cpus, mem_mb, gpu):
    if not _IMAGE.match(image):
        raise P.LabError(f"bad image reference {image!r}")
    name = lane_name(i)
    work = f"{cfg['remote_root']}/lanes/{name}"
    argv = ["docker", "run", "-d", "--name", name, "--restart", "no", "--cpus", str(cpus), "--memory", f"{mem_mb}m",
            "-v", f"{work}:/work", "-w", "/work", "-p", f"127.0.0.1:{host_port(name)}:{NOVNC_PORT}"]
    if gpu:
        argv += ["--gpus", "all"]
    argv += [image]
    return f"mkdir -p {shlex.quote(work)} && " + shlex.join(argv)


def build_run(lane, job, argv):
    """Start argv detached inside the lane: nohup, log + exit code files under /work/.jobs/<job>/."""
    valid_lane(lane)
    valid_job(job)
    if not argv:
        raise P.LabError("no command")
    inner = argv[0] if len(argv) == 1 else shlex.join(argv)
    d = f"/work/.jobs/{job}"
    script = (f"mkdir -p {d} && nohup sh -c {shlex.quote(inner + '; echo $? > ' + d + '/exit')} "
              f"> {d}/log 2>&1 < /dev/null & echo started")
    return shlex.join(["docker", "exec", lane, "sh", "-c", script])


def build_cat(job, fname, tail=None):
    lane = lane_of(job)
    path = f"/work/.jobs/{job}/{fname}"
    cmd = f"tail -n {int(tail)} {path}" if tail else f"cat {path}"
    return shlex.join(["docker", "exec", lane, "sh", "-c", cmd + " 2>/dev/null; true"])


def new_job_id(lane, now=None):
    return f"{valid_lane(lane)}-{int((now or time.time()) * 1000):011x}"


# ---- self-destruct (runs ON the pod; labctl never touches the Vast API) ----
def timer_script(cfg):
    r = shlex.quote(cfg["remote_root"])
    marker = f"touch {r}/DESTROY_MARKER; " if cfg.get("destroy_cmd") else ""
    return (f'while [ "$(date +%s)" -lt "$(cat {r}/deadline)" ]; do sleep 20; done; '
            f"docker ps -aq --filter name=lane- | xargs -r docker stop; {marker}rm -f {r}/timer.pid")


def build_arm(cfg, seconds):
    r = shlex.quote(cfg["remote_root"])
    inner = shlex.quote(timer_script(cfg))
    return (f"mkdir -p {r} && echo $(( $(date +%s) + {int(seconds)} )) > {r}/deadline && "
            f'if ! kill -0 "$(cat {r}/timer.pid 2>/dev/null)" 2>/dev/null; then '
            f"rm -f {r}/DESTROY_MARKER; nohup sh -c {inner} > /dev/null 2>&1 < /dev/null & echo $! > {r}/timer.pid; fi; echo armed")


def build_extend(cfg, hours):
    """Add hours to the time left, total capped at MAX_EXTEND_H from now; never shortens."""
    h = float(hours)
    if not 0 < h <= P.MAX_EXTEND_H:
        raise P.LabError(f"extend refused: {h} h (allowed 0 < h <= {P.MAX_EXTEND_H})")
    r = shlex.quote(cfg["remote_root"])
    add, cap = int(round(h * 3600)), int(P.MAX_EXTEND_H * 3600)
    return (f"test -s {r}/deadline || {{ echo no-timer; exit 3; }}; now=$(date +%s); d=$(cat {r}/deadline); "
            f"rem=$((d-now)); [ $rem -lt 0 ] && rem=0; new=$((rem+{add})); [ $new -gt {cap} ] && new={cap}; "
            f"[ $new -lt $rem ] && new=$rem; echo $((now+new)) > {r}/deadline; echo $new")


def build_status(cfg):
    r = shlex.quote(cfg["remote_root"])
    return ("echo '#gpu'; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null; "
            f"echo '#disk'; df -h {r} 2>/dev/null | tail -n 1; "
            "echo '#lanes'; docker ps -a --filter name=lane- --format '{{.Names}} {{.Status}}' 2>/dev/null; "
            f"echo '#jobs'; for e in {r}/lanes/*/.jobs/*; do [ -d \"$e\" ] || continue; "
            "if [ -f \"$e/exit\" ]; then echo \"$(basename $e) exit $(cat $e/exit)\"; else echo \"$(basename $e) running\"; fi; done; "
            f"echo '#deadline'; d=$(cat {r}/deadline 2>/dev/null); [ -n \"$d\" ] && echo $((d-$(date +%s)))")


def parse_status(text):
    sec, cur = {}, None
    for line in text.splitlines():
        if line.startswith("#"):
            cur = line[1:].strip()
            sec[cur] = []
        elif cur and line.strip():
            sec[cur].append(line.strip())
    left = None
    if sec.get("deadline") and re.fullmatch(r"-?\d+", sec["deadline"][0]):
        left = max(0, int(sec["deadline"][0])) / 60.0
    sec["minutes_left"] = left
    return sec


# ---- verbs ----
def up(runner, cfg, n, image, gpu, out=print):
    rc, txt = runner.text("echo $(nproc) $(free -m | awk '/^Mem:/{print $2}')")
    f = txt.split()
    if rc != 0 or len(f) != 2 or not all(x.isdigit() for x in f):
        raise P.LabError("cannot read pod CPU/RAM")
    cpus, mem = split_resources(int(f[0]), int(f[1]), n)
    for i in range(1, n + 1):
        rc, _ = runner.text(build_up(cfg, i, image, cpus, mem, gpu))
        if rc != 0:
            raise P.LabError(f"could not start {lane_name(i)} (exit {rc}); lanes started so far keep running, use 'lanes down'")
        out(f"{lane_name(i)} up: {cpus} CPU, {mem} MB, gpu={'shared' if gpu else 'no'}")
    secs = int(cfg["self_destruct_hours"] * 3600)
    rc, _ = runner.text(build_arm(cfg, secs))
    if rc != 0:
        raise P.LabError("lanes started but the self-destruct timer could not be armed: run 'lanes down' now")
    out(f"self-destruct armed: all lanes stop in {cfg['self_destruct_hours']:g} h")


def ls(runner, cfg, out=print):
    rc, txt = runner.text("docker ps -a --filter name=lane- --format '{{.Names}}\t{{.Status}}\t{{.Image}}'")
    out(txt.strip() or "no lanes")


def down(runner, cfg, name=None, all_=False, out=print):
    if bool(name) == bool(all_):
        raise P.LabError("give a lane name or --all")
    cmd = ("docker ps -aq --filter name=lane- | xargs -r docker rm -f" if all_
           else shlex.join(["docker", "rm", "-f", valid_lane(name)]))
    rc, _ = runner.text(cmd)
    out(f"down: {'all lanes' if all_ else name} (exit {rc})")
    return rc


def run(runner, cfg, lane, argv, out=print):
    job = new_job_id(lane)
    rc, _ = runner.text(build_run(lane, job, argv))
    if rc != 0:
        raise P.LabError(f"could not start the job (exit {rc})")
    out(job)
    return job


def wait(runner, cfg, job, poll=5.0, timeout=None, sleep=time.sleep, mono=time.monotonic):
    t0 = mono()
    while True:
        _, txt = runner.text(build_cat(job, "exit"))
        if txt.strip():
            return int(txt.strip()) if txt.strip().lstrip("-").isdigit() else 1
        if timeout is not None and mono() - t0 > timeout:
            raise P.LabError("wait timed out; the job keeps running")
        sleep(poll)


def logs(runner, cfg, job, n=50):
    return runner.text(build_cat(job, "log", tail=max(1, int(n))))[1]


def status(runner, cfg, out=print):
    _, txt = runner.text(build_status(cfg))
    sec = parse_status(txt)
    for k in ("gpu", "disk", "lanes", "jobs"):
        out(f"{k}: " + ("; ".join(sec.get(k, [])) or "-"))
    m = sec["minutes_left"]
    out("self-destruct in: " + ("no timer" if m is None else f"{m:.0f} min"))
    return sec


def extend(runner, cfg, hours, out=print):
    rc, txt = runner.text(build_extend(cfg, hours))
    if rc != 0 or not txt.strip().isdigit():
        raise P.LabError("extend refused: no self-destruct timer found on the pod")
    out(f"self-destruct now in {int(txt) / 60:.0f} min")


def tunnel_cmd(cfg, lane, local_port=None):
    hp = host_port(lane)
    lp = local_port or hp
    ident = f" -i {shlex.quote(str(cfg['identity_file']))}" if cfg.get("identity_file") else ""
    return (f"ssh -N -p {cfg['port']}{ident} -L 127.0.0.1:{lp}:127.0.0.1:{hp} {cfg['user']}@{cfg['host']}"
            f"   # then open http://127.0.0.1:{lp}/")
