"""labctl: run several containers ("lanes") on one rented VM pod over ssh. Never rents or destroys the pod itself.
  labctl lanes up <n> [--image IMG] [--gpu] | lanes ls | lanes down [name|--all]
  labctl run <lane> -- <cmd> | wait <job> | logs <job> -n N | push <local> <rel> | pull <rel> <local>
  labctl status | extend <hours> | tunnel <lane>
Config: JSON at $LABCTL_CONFIG (default ~/.labctl.json): host, port, user, identity_file, remote_root, self_destruct_hours, destroy_cmd."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lanes as L  # noqa: E402
import pod as P  # noqa: E402


def build_parser():
    p = argparse.ArgumentParser(prog="labctl", description=__doc__.splitlines()[0])
    sp = p.add_subparsers(dest="c", required=True)
    ln = sp.add_parser("lanes").add_subparsers(dest="s", required=True)
    x = ln.add_parser("up")
    x.add_argument("n", type=int)
    x.add_argument("--image", default=L.DEFAULT_IMAGE)
    x.add_argument("--gpu", action="store_true")
    ln.add_parser("ls")
    x = ln.add_parser("down")
    x.add_argument("name", nargs="?")
    x.add_argument("--all", action="store_true")
    x = sp.add_parser("run")
    x.add_argument("lane")
    x.add_argument("cmd", nargs=argparse.REMAINDER)
    x = sp.add_parser("wait")
    x.add_argument("job")
    x.add_argument("--timeout", type=float)
    x = sp.add_parser("logs")
    x.add_argument("job")
    x.add_argument("-n", type=int, default=50)
    x = sp.add_parser("push")
    x.add_argument("local")
    x.add_argument("remote")
    x = sp.add_parser("pull")
    x.add_argument("remote")
    x.add_argument("local")
    sp.add_parser("status")
    x = sp.add_parser("extend")
    x.add_argument("hours", type=float)
    x = sp.add_parser("tunnel")
    x.add_argument("lane")
    return p


def dispatch(a, cfg, runner, out=print):
    c = a.c
    if c == "lanes":
        if a.s == "up":
            L.up(runner, cfg, a.n, a.image, a.gpu, out)
            return 0
        if a.s == "ls":
            L.ls(runner, cfg, out)
            return 0
        return L.down(runner, cfg, a.name, a.all, out)
    if c == "run":
        L.run(runner, cfg, a.lane, a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd, out)
    elif c == "wait":
        rc = L.wait(runner, cfg, a.job, timeout=a.timeout)
        out(f"exit {rc}")
        return rc
    elif c == "logs":
        out(L.logs(runner, cfg, a.job, a.n))
    elif c == "push":
        b, n = P.push(runner, cfg, a.local, a.remote)
        out(f"pushed {n} files, {b} bytes (verified)")
    elif c == "pull":
        b, n = P.pull(runner, cfg, a.remote, a.local)
        out(f"pulled {n} files, {b} bytes (verified)")
    elif c == "status":
        L.status(runner, cfg, out)
    elif c == "extend":
        L.extend(runner, cfg, a.hours, out)
    elif c == "tunnel":
        out(L.tunnel_cmd(cfg, a.lane))
    return 0


def main(argv=None, cfg=None, runner=None):
    a = build_parser().parse_args(argv)
    try:
        cfg = cfg or P.load_config()
        return dispatch(a, cfg, runner or P.SshRunner(cfg))
    except (P.LabError, ValueError) as e:
        print(f"labctl: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
