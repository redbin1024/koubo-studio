import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class BrollTests(unittest.TestCase):
    def test_resolve_real_clip_at_cue(self):
        from workflow.broll import resolve
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "input" / "broll").mkdir(parents=True)
            (project / "input" / "broll" / "tea.mp4").write_bytes(b"x")
            cfg = {"broll": {"enabled": True, "items": [
                {"cue": 7, "keyword": "放心", "source": "broll/tea.mp4",
                 "in": 0.5, "dur": 1.5}]}}
            cues = [{"index": 7, "start": 19.39, "end": 24.23,
                     "lines": ["那一句[[放心]]我们一直都在"]}]
            plans, errors = resolve(cfg, project, cues)
            self.assertEqual(errors, [])
            self.assertEqual(plans[0]["start"], 19.51)
            self.assertEqual(plans[0]["end"], 21.01)

    def test_unknown_keyword_and_out_of_window_fail(self):
        from workflow.broll import resolve
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "input" / "broll").mkdir(parents=True)
            (project / "input" / "broll" / "tea.mp4").write_bytes(b"x")
            cfg = {"broll": {"enabled": True, "items": [
                {"cue": 7, "keyword": "不存在", "source": "broll/tea.mp4", "dur": 1},
                {"cue": 7, "keyword": "放心", "source": "broll/tea.mp4", "at": 99, "dur": 1},
            ]}}
            cues = [{"index": 7, "start": 19.39, "end": 24.23,
                     "lines": ["那一句[[放心]]我们一直都在"]}]
            plans, errors = resolve(cfg, project, cues)
            self.assertEqual(plans, [])
            self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
