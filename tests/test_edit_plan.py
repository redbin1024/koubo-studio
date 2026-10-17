import importlib.util
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class EditPlanTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("edit_plan"))
        import edit_plan
        return edit_plan

    def test_validates_source_ranges_and_total(self):
        edit_plan = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            source = (Path(tmp) / "clip.mp4").resolve()
            source.touch()
            plan = {"version": 1, "mode": "vlog", "shots": [
                {"source": str(source), "in": 0.5, "duration": 1.5,
                 "reason": "scene", "score": 0.5},
                {"source": str(source), "in": 3, "duration": 2,
                 "reason": "scene", "score": 0.5},
            ]}
            self.assertEqual(edit_plan.validate_plan(plan, {str(source): 5}), 3.5)
            for bad in ([], [{"source": str(source), "in": -1, "duration": 1}],
                        [{"source": str(source), "in": 0, "duration": 0}],
                        [{"source": str(source), "in": 4.5, "duration": 1}],
                        [{"source": str(source), "in": math.nan, "duration": 1}],
                        [{"source": str(source) + ".missing", "in": 0, "duration": 1}]):
                with self.subTest(shots=bad), self.assertRaises(ValueError):
                    edit_plan.validate_plan({"version": 1, "mode": "vlog", "shots": bad},
                                            {str(source): 5})

    def test_renders_mixed_audio_sources_without_touching_inputs(self):
        edit_plan = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            silent, voiced, output = root / "silent.mp4", root / "voiced.mp4", root / "cut.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=red:s=64x64:r=10:d=1", "-c:v", "libx264", str(silent)],
                           check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x64:r=10:d=1", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=1", "-c:v", "libx264",
                            "-c:a", "aac", str(voiced)], check=True)
            sizes = silent.stat().st_size, voiced.stat().st_size
            plan = {"version": 1, "mode": "vlog", "shots": [
                {"source": str(silent), "in": 0.1, "duration": 0.6},
                {"source": str(voiced), "in": 0.2, "duration": 0.6}]}
            edit_plan.render_plan(plan, output, 64, 64, 10)
            from _common import probe_media
            actual = probe_media(output)
            self.assertAlmostEqual(actual["duration"], 1.2, delta=0.15)
            self.assertEqual((actual["width"], actual["height"], actual["fps"]),
                             (64, 64, 10))
            self.assertTrue(actual["has_audio"])
            self.assertEqual((silent.stat().st_size, voiced.stat().st_size), sizes)
            with self.assertRaises(ValueError):
                edit_plan.render_plan({"version": 1, "mode": "vlog", "shots": [
                    {"source": str(silent), "in": 10, "duration": 1}]}, output, 64, 64, 10)
            self.assertEqual(output.stat().st_size > 0, True)
            with self.assertRaises(ValueError):
                edit_plan.render_plan(plan, silent, 64, 64, 10)
            self.assertEqual(silent.stat().st_size, sizes[0])

    def test_dip_transition_keeps_duration_and_dips_to_black(self):
        edit_plan = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, output = root / "blue.mp4", root / "dip.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x64:r=30:d=2", "-c:v", "libx264",
                            str(source)], check=True)
            shots = [{"source": str(source), "in": 0, "duration": 1},
                     {"source": str(source), "in": 1, "duration": 1,
                      "transition": "dip"}]
            plan = {"version": 1, "mode": "vlog", "shots": shots}
            edit_plan.render_plan(plan, output, 64, 64, 30)
            from _common import probe_media
            self.assertAlmostEqual(probe_media(output)["duration"], 2, delta=0.08)
            pixel = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i",
                                    str(output), "-frames:v", "1", "-f", "rawvideo",
                                    "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
            self.assertLess(max(pixel.stdout[:3]), 55)
            for invalid in ("spin", None):
                with self.subTest(transition=invalid), self.assertRaises(ValueError):
                    edit_plan.validate_plan({**plan, "shots": [shots[0], {
                        **shots[1], "transition": invalid}]}, {str(source): 2})
            with self.assertRaises(ValueError):
                edit_plan.validate_plan({**plan, "shots": [{
                    **shots[0], "transition": "dip"}, shots[1]]}, {str(source): 2})


if __name__ == "__main__":
    unittest.main()
