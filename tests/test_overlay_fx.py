import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class OverlayFxTests(unittest.TestCase):
    def test_resolve_card_keyframes(self):
        from workflow.overlay_fx import resolve
        cfg = {"overlay_fx": {"enabled": True, "items": [
            {"label": "卡段", "keyframes": [
                {"property": "scale", "time": 0.0, "value": "1.03"},
                {"property": "scale", "time": 0.35, "value": "1.0"}]},
        ]}}
        plans, errors = resolve(cfg, [{"label": "卡段", "id": "seg-1",
                                       "start": 12.63, "end": 16.47}])
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]["segment_id"], "seg-1")

    def test_unknown_label_and_out_of_range_fail(self):
        from workflow.overlay_fx import resolve
        cfg = {"overlay_fx": {"enabled": True, "items": [
            {"label": "不存在", "keyframes": []},
            {"label": "卡段", "keyframes": [{"property": "scale", "time": 9, "value": "1"}]},
        ]}}
        plans, errors = resolve(cfg, [{"label": "卡段", "id": "seg-1",
                                       "start": 0, "end": 1}])
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
