import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow.caption_timing import overlap_status
from _common import apply_defaults
import make_captions


class CaptionTimingTests(unittest.TestCase):
    def make_srt(self, directory: Path, second_start: str) -> Path:
        path = directory / "captions.srt"
        path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n"
            f"2\n{second_start} --> 00:00:01,500\n第二句",
            encoding="utf-8")
        return path

    def test_reports_the_colliding_frame_and_cue_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = self.make_srt(Path(tmp), "00:00:00,900")
            okay, detail = overlap_status(srt, 30)
            self.assertFalse(okay)
            self.assertIn("第 1 与第 2", detail)
            self.assertIn("0.900s", detail)
            self.assertTrue(overlap_status(srt, 30, {1})[0])

    def test_subframe_overlap_does_not_create_a_visible_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = self.make_srt(Path(tmp), "00:00:00,990")
            self.assertTrue(overlap_status(srt, 30)[0])

    def test_caption_build_stops_before_rendering_a_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "input").mkdir()
            self.make_srt(project / "input", "00:00:00,900")
            cfg = apply_defaults({"input": {"subtitle": "captions.srt"}})
            with self.assertRaisesRegex(SystemExit, "字幕预检未通过"):
                make_captions.build(cfg, project)


if __name__ == "__main__":
    unittest.main()
