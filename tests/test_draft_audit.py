import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _spec():
    return {
        "version": 1, "project": "audit", "duration": 4.0,
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "clips": [
            {"id": "main-1", "track": "main", "type": "video", "duration": 2.0},
            {"id": "main-2", "track": "main", "type": "video", "duration": 2.0},
            {"id": "voice", "track": "voice", "type": "audio",
             "duration": 3.9, "required": True},
        ],
        "texts": [{"id": "text-1", "start": 0.2, "duration": 1.8,
                   "content": "示例", "line_spacing": 0.22}],
        "stickers": [], "native": [],
        "qa": {"min_line_spacing": 0.12, "require_installed": False},
    }


def _draft(*, voice=True, spacing=0.22):
    tracks = [
        {"name": "video", "type": "video", "segments": [
            {"target_timerange": {"start": 0, "duration": 2_000_000}},
            {"target_timerange": {"start": 2_000_000, "duration": 2_000_000}},
        ]},
        {"name": "字幕", "type": "text", "segments": [
            {"target_timerange": {"start": 200_000, "duration": 1_800_000}},
        ]},
    ]
    if voice:
        tracks.append({"name": "人声", "type": "audio", "segments": [
            {"target_timerange": {"start": 0, "duration": 3_900_000}, "muted": False},
        ]})
    return {
        "canvas_config": {"width": 1080, "height": 1920},
        "materials": {"texts": [{"line_spacing": spacing}],
                      "videos": [], "audios": [], "transitions": []},
        "tracks": tracks,
    }


class DraftAuditTests(unittest.TestCase):
    def _run(self, draft):
        from workflow.draft_audit import audit
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "draft_content.json").write_text(
                json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            return audit(_spec(), root)

    def test_positive_control_passes(self):
        report = self._run(_draft())
        self.assertTrue(report["ok"], report["checks"])
        self.assertEqual(report["summary"]["fail"], 0)

    def test_missing_voice_and_tight_line_spacing_fail(self):
        report = self._run(_draft(voice=False, spacing=0.02))
        self.assertFalse(report["ok"])
        failed = {c["name"] for c in report["checks"] if c["status"] == "fail"}
        self.assertIn("audio-voice", failed)
        self.assertIn("text-line-spacing", failed)


if __name__ == "__main__":
    unittest.main()
