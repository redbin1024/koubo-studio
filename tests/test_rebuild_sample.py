import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rebuild_sample import import_legacy_plan
from _common import apply_defaults
from make_jianying_draft import main_video_segments


class SampleImportTests(unittest.TestCase):
    def test_import_preserves_source_ranges_and_rejects_timeline_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp)
            source = sample / "source.mov"
            source.write_bytes(b"placeholder")
            legacy = {"duration": 3.0, "shots": [
                {"start": 0, "duration": 1.5, "source": str(source),
                 "source_in": 2.0, "caption": "第一镜"},
                {"start": 1.5, "duration": 1.5, "source": str(source),
                 "source_in": 5.0, "caption": "第二镜"}]}
            (sample / "镜头方案.json").write_text(json.dumps(legacy), encoding="utf-8")
            plan = import_legacy_plan(sample)
            self.assertEqual(plan["version"], 1)
            self.assertEqual([s["in"] for s in plan["shots"]], [2.0, 5.0])
            self.assertEqual([s["caption"] for s in plan["shots"]], ["第一镜", "第二镜"])

            legacy["shots"][1]["start"] = 1.6
            (sample / "镜头方案.json").write_text(json.dumps(legacy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不连续"):
                import_legacy_plan(sample)

    def test_draft_uses_edit_plan_cut_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "input").mkdir()
            (project / "work").mkdir()
            (project / "input/clean-cut.mp4").write_bytes(b"placeholder")
            (project / "work/edit-plan.json").write_text(json.dumps({"shots": [
                {"duration": 1.4}, {"duration": 1.6}]}), encoding="utf-8")
            cfg = apply_defaults({"input": {"video": "clean-cut.mp4"}})
            self.assertEqual(main_video_segments(cfg, project, 3.0), [1.4, 1.6])


if __name__ == "__main__":
    unittest.main()
