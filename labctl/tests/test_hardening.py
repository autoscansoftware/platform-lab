import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import labctl  # noqa: E402
import lanes as L  # noqa: E402
import pod as P  # noqa: E402
from test_labctl import CFG, FakeRunner  # noqa: E402


class Hardening(unittest.TestCase):
    def test_default_image_pinned_digest_and_override(self):
        self.assertRegex(L.DEFAULT_IMAGE, r"^ghcr\.io/[a-z0-9/_-]+@sha256:[0-9a-f]{64}$")
        a = labctl.build_parser().parse_args(["lanes", "up", "1"])
        self.assertEqual(a.image, L.DEFAULT_IMAGE)
        a = labctl.build_parser().parse_args(["lanes", "up", "1", "--image", "example/x:dev"])
        self.assertEqual(a.image, "example/x:dev")

    def test_read_default_image_skips_comments(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "IMAGE"
            f.write_text("# c\n\nexample/x@sha256:" + "a" * 64 + "\n")
            self.assertTrue(L.read_default_image(f).startswith("example/x@sha256:"))
            f.write_text("# only\n")
            with self.assertRaises(P.LabError):
                L.read_default_image(f)

    def test_lane_label_not_name_substring(self):
        self.assertIn("--label labctl.lane=1", L.build_up(CFG, 1, L.DEFAULT_IMAGE, 1, 512, False))
        r = FakeRunner()
        L.ls(r, CFG, lambda s: None)
        L.down(r, CFG, None, True, lambda s: None)
        for c in r.calls + [L.timer_script(CFG), L.build_status(CFG)]:
            self.assertNotIn("name=lane-", c)
            self.assertIn("label=labctl.lane=1", c)

    def test_status_says_timer_not_running(self):
        base = "#deadline\n600\n#timer\n"
        out = []
        L.status(FakeRunner({"#gpu": (0, (base + "dead\n").encode())}), CFG, out.append)
        self.assertIn("TIMER NOT RUNNING", out[-1])
        out = []
        L.status(FakeRunner({"#gpu": (0, (base + "alive\n").encode())}), CFG, out.append)
        self.assertNotIn("NOT RUNNING", out[-1])
        self.assertIn("LANES only", out[-1])
        self.assertTrue(L.parse_status(base + "alive\n")["timer_alive"])
        self.assertFalse(L.parse_status("#deadline\n5\n")["timer_alive"])

    def test_extend_refuses_dead_timer_and_arm_checks_alive(self):
        self.assertIn("kill -0", L.build_extend(CFG, 1))
        with self.assertRaises(P.LabError) as e:
            L.extend(FakeRunner({"deadline": (4, b"timer-dead\n")}), CFG, 1)
        self.assertIn("TIMER NOT RUNNING", str(e.exception))
        arm = L.build_arm(CFG, 60)
        self.assertIn("systemd-run", arm)
        self.assertIn("nohup", arm)
        r = FakeRunner({"nproc": (0, b"8 32000\n"), "deadline": (5, b"not-running\n")})
        with self.assertRaises(P.LabError):
            L.up(r, CFG, 1, L.DEFAULT_IMAGE, False, lambda s: None)


if __name__ == "__main__":
    unittest.main()
