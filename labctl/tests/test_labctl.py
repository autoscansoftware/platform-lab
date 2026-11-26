import io
import os
import shlex
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import labctl  # noqa: E402
import lanes as L  # noqa: E402
import pod as P  # noqa: E402

CFG = P.validate_config({"host": "pod.example", "port": 2222, "user": "root", "remote_root": "/work/lab",
                         "identity_file": "/keys/id", "self_destruct_hours": 2})


class FakeRunner:
    """Records commands; replies come from `replies` (substring -> (rc, bytes)) or default to (0, b'')."""

    def __init__(self, replies=None):
        self.calls, self.stdins, self.replies = [], [], replies or {}

    def run(self, cmd, stdin=None):
        self.calls.append(cmd)
        self.stdins.append(stdin)
        for k, v in self.replies.items():
            if k in cmd:
                return v
        return 0, b""

    def text(self, cmd):
        rc, out = self.run(cmd)
        return rc, out.decode()


def make_tar(name, files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for rel, data in files.items():
            ti = tarfile.TarInfo(f"{name}/{rel}" if rel else name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


class PathSafety(unittest.TestCase):
    def test_refuses_bad(self):
        for bad in ("/etc/passwd", "../x", "a/../b", "", "C:/x", "\\\\srv\\share", "a\\..\\b"):
            with self.assertRaises(P.LabError, msg=bad):
                P.clean_rel(bad)

    def test_accepts_and_normalises(self):
        self.assertEqual(P.clean_rel("a//b/./c/"), "a/b/c")
        self.assertEqual(P.remote_abs(CFG, "x/y"), "/work/lab/x/y")

    def test_config_validation(self):
        for bad in ({"host": "-oProxy=x", "remote_root": "/r"}, {"host": "h", "remote_root": "rel"},
                    {"host": "h", "remote_root": "/a/../b"}, {"host": "h", "remote_root": "/r", "port": 0},
                    {"host": "h", "remote_root": "/r", "self_destruct_hours": 99}, {"host": "h", "remote_root": "/"}):
            with self.assertRaises(P.LabError):
                P.validate_config(bad)

    def test_ssh_argv_single_remote_arg(self):
        argv = P.ssh_argv(CFG, "echo 'a b'")
        self.assertEqual(argv[-1], "echo 'a b'")
        self.assertEqual(argv[-2], "root@pod.example")
        self.assertIn("2222", argv)
        self.assertIn("/keys/id", argv)


class Resources(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(L.split_resources(16, 64000, 4), (4.0, 16000))
        self.assertEqual(L.split_resources(8, 30000, 3), (2.67, 10000))

    def test_limits(self):
        with self.assertRaises(P.LabError):
            L.split_resources(8, 64000, 0)
        with self.assertRaises(P.LabError):
            L.split_resources(8, 64000, 17)
        with self.assertRaises(P.LabError):
            L.split_resources(8, 400, 4)

    def test_up_command_and_gpu(self):
        c = L.build_up(CFG, 2, L.DEFAULT_IMAGE, 4.0, 16000, True)
        self.assertIn("--name lane-2", c)
        self.assertIn("--cpus 4.0", c)
        self.assertIn("--memory 16000m", c)
        self.assertIn("--gpus all", c)
        self.assertIn("127.0.0.1:6082:6080", c)
        self.assertNotIn("--gpus", L.build_up(CFG, 1, L.DEFAULT_IMAGE, 4.0, 16000, False))

    def test_bad_image(self):
        with self.assertRaises(P.LabError):
            L.build_up(CFG, 1, "x; rm -rf /", 1, 512, False)

    def test_up_runs_all_lanes_and_arms_timer(self):
        r = FakeRunner({"nproc": (0, b"8 32000\n")})
        out = []
        L.up(r, CFG, 4, L.DEFAULT_IMAGE, False, out.append)
        runs = [c for c in r.calls if "docker run" in c]
        self.assertEqual(len(runs), 4)
        self.assertIn("--cpus 2.0", runs[0])
        self.assertTrue(any("deadline" in c and "7200" in c for c in r.calls))


class Commands(unittest.TestCase):
    def test_run_quoting(self):
        job = L.new_job_id("lane-1", 1.5)
        c = L.build_run("lane-1", job, ["echo", "a b; rm -rf /", "$HOME"])
        outer = shlex.split(c)
        self.assertEqual(outer[:4], ["docker", "exec", "lane-1", "sh"])
        inner = outer[-1]
        self.assertIn("nohup sh -c", inner)
        self.assertIn(f"/work/.jobs/{job}/exit", inner)
        # the user's text survives as one quoted word inside the inner script
        self.assertIn("'a b; rm -rf /'", inner.replace("'\"'\"'", "'"))

    def test_run_single_string_goes_to_shell(self):
        c = L.build_run("lane-1", L.new_job_id("lane-1", 2), ["make && make test"])
        self.assertIn("make && make test", c)

    def test_bad_names(self):
        for bad in ("lane-0", "lane-1; ls", "x", "lane-99x"):
            with self.assertRaises(P.LabError):
                L.valid_lane(bad)
        with self.assertRaises(P.LabError):
            L.valid_job("lane-1-zz; ls")
        with self.assertRaises(P.LabError):
            L.build_run("lane-1", "bad", ["x"])

    def test_wait_polls_until_exit(self):
        job = L.new_job_id("lane-1", 3)
        seq = [(0, b""), (0, b""), (0, b"3\n")]
        r = FakeRunner()
        r.run = lambda cmd, stdin=None: seq.pop(0)
        sleeps = []
        self.assertEqual(L.wait(r, CFG, job, sleep=sleeps.append), 3)
        self.assertEqual(len(sleeps), 2)

    def test_wait_timeout(self):
        job = L.new_job_id("lane-1", 3)
        t = iter([0, 10, 20])
        with self.assertRaises(P.LabError):
            L.wait(FakeRunner(), CFG, job, timeout=5, sleep=lambda s: None, mono=lambda: next(t))

    def test_logs_tail(self):
        job = L.new_job_id("lane-2", 4)
        r = FakeRunner({"tail": (0, b"line\n")})
        self.assertEqual(L.logs(r, CFG, job, 7), "line\n")
        self.assertIn("tail -n 7", r.calls[0])

    def test_down(self):
        r = FakeRunner()
        L.down(r, CFG, "lane-3", False, lambda s: None)
        self.assertEqual(r.calls[0], "docker rm -f lane-3")
        with self.assertRaises(P.LabError):
            L.down(r, CFG, None, False)
        with self.assertRaises(P.LabError):
            L.down(r, CFG, "lane-1", True)

    def test_status_parse(self):
        txt = "#gpu\nA4500, 10 MiB, 20000 MiB\n#disk\n/dev/x 100G\n#lanes\nlane-1 Up 2 minutes\n#jobs\nlane-1-ab12cd34 running\n#deadline\n5400\n"
        sec = L.parse_status(txt)
        self.assertEqual(sec["minutes_left"], 90.0)
        self.assertEqual(sec["jobs"], ["lane-1-ab12cd34 running"])
        self.assertIsNone(L.parse_status("#deadline\n")["minutes_left"])

    def test_extend_limits_and_script(self):
        for bad in (0, -1, 12.5):
            with self.assertRaises(P.LabError):
                L.build_extend(CFG, bad)
        self.assertIn("43200", L.build_extend(CFG, 12))
        r = FakeRunner({"deadline": (3, b"no-timer\n")})
        with self.assertRaises(P.LabError):
            L.extend(r, CFG, 1)

    def test_timer_marker_only_with_destroy_cmd(self):
        self.assertNotIn("DESTROY_MARKER", L.timer_script(CFG))
        cfg2 = P.validate_config({"host": "h", "remote_root": "/r", "destroy_cmd": "go"})
        self.assertIn("DESTROY_MARKER", L.timer_script(cfg2))
        self.assertIn("docker stop", L.timer_script(CFG))

    def test_tunnel_binds_localhost(self):
        t = L.tunnel_cmd(CFG, "lane-2")
        self.assertIn("-L 127.0.0.1:6082:127.0.0.1:6082", t)
        self.assertIn("-p 2222", t)


class Transfer(unittest.TestCase):
    def test_push_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.txt").write_bytes(b"hello")
            (Path(d) / "sub").mkdir()
            (Path(d) / "sub" / "b.txt").write_bytes(b"12345")
            r = FakeRunner({"find -L": (0, b"10 2\n")})
            self.assertEqual(P.push(r, CFG, d, "in/data"), (10, 2))
            self.assertIn("tar -xf - -C /work/lab/in", r.calls[0])
            names = tarfile.open(fileobj=io.BytesIO(r.stdins[0])).getnames()
            self.assertIn("data/a.txt", names)
            bad = FakeRunner({"find -L": (0, b"9 2\n")})
            with self.assertRaises(P.LabError):
                P.push(bad, CFG, d, "in/data")

    def test_push_refuses_absolute(self):
        with self.assertRaises(P.LabError):
            P.push(FakeRunner(), CFG, __file__, "/etc/x")

    def test_pull_ok_and_merge(self):
        tar = make_tar("out", {"": b"", "r1.txt": b"abc", "d/r2.txt": b"de"})
        # directory entries: make_tar adds a size-0 regular file named 'out'; use a real dir tree instead
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as src:
            (Path(src) / "out" / "d").mkdir(parents=True)
            (Path(src) / "out" / "r1.txt").write_bytes(b"abc")
            (Path(src) / "out" / "d" / "r2.txt").write_bytes(b"de")
            with tarfile.open(fileobj=buf, mode="w") as t:
                t.add(str(Path(src) / "out"), arcname="out")
        r = FakeRunner({"find -L": (0, b"5 2\n"), "tar -cf": (0, buf.getvalue())})
        with tempfile.TemporaryDirectory() as dst:
            (Path(dst) / "keep.txt").write_text("local only")
            self.assertEqual(P.pull(r, CFG, "jobs/out", dst), (5, 2))
            self.assertEqual((Path(dst) / "d" / "r2.txt").read_bytes(), b"de")
            self.assertTrue((Path(dst) / "keep.txt").exists())
        self.assertTrue(tar)

    def test_pull_count_mismatch(self):
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as src:
            (Path(src) / "o").mkdir()
            (Path(src) / "o" / "a").write_bytes(b"abc")
            with tarfile.open(fileobj=buf, mode="w") as t:
                t.add(str(Path(src) / "o"), arcname="o")
        r = FakeRunner({"find -L": (0, b"3 2\n"), "tar -cf": (0, buf.getvalue())})
        with tempfile.TemporaryDirectory() as dst:
            with self.assertRaises(P.LabError):
                P.pull(r, CFG, "o", dst)

    def test_pull_refuses_unsafe_archive(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            ti = tarfile.TarInfo("o/../../evil")
            ti.size = 1
            t.addfile(ti, io.BytesIO(b"x"))
        r = FakeRunner({"find -L": (0, b"1 1\n"), "tar -cf": (0, buf.getvalue())})
        with tempfile.TemporaryDirectory() as dst:
            with self.assertRaises(P.LabError):
                P.pull(r, CFG, "o", dst)

    def test_pull_empty_remote(self):
        r = FakeRunner({"find -L": (0, b"0 0\n")})
        with self.assertRaises(P.LabError):
            P.pull(r, CFG, "nothing", tempfile.gettempdir())

    def test_pull_command_quoting(self):
        self.assertEqual(P.build_pull(CFG, "a b/c d"), "tar -cf - -C '/work/lab/a b' 'c d'")


class Cli(unittest.TestCase):
    def test_run_dispatch(self):
        r = FakeRunner()
        out = []
        a = labctl.build_parser().parse_args(["run", "lane-1", "--", "echo", "hi"])
        self.assertEqual(labctl.dispatch(a, CFG, r, out.append), 0)
        self.assertTrue(out[0].startswith("lane-1-"))
        self.assertIn("echo hi", r.calls[0])

    def test_tunnel_and_error_exit(self):
        out = []
        a = labctl.build_parser().parse_args(["tunnel", "lane-1"])
        labctl.dispatch(a, CFG, FakeRunner(), out.append)
        self.assertIn("127.0.0.1:6081", out[0])
        self.assertEqual(labctl.main(["pull", "../x", "y"], cfg=CFG, runner=FakeRunner()), 1)

    def test_missing_config(self):
        os.environ["LABCTL_CONFIG"] = os.path.join(tempfile.gettempdir(), "no-such-labctl.json")
        try:
            self.assertEqual(labctl.main(["lanes", "ls"]), 1)
        finally:
            del os.environ["LABCTL_CONFIG"]


if __name__ == "__main__":
    unittest.main()
