import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class AdvancedFxTests(unittest.TestCase):
    def test_resolve_keyframes_and_mask(self):
        from workflow.advanced_fx import resolve
        cfg = {"shot_fx": {"enabled": True, "items": [
            {"shot": 1, "mask": {"type": "circle", "size": 0.6},
             "keyframes": [{"property": "scale", "time": 0.0, "value": "1.0"},
                           {"property": "scale", "time": 1.0, "value": "1.1"}]},
        ]}}
        plans, errors = resolve(cfg, [("seg-1", 0.0, 2.0), ("seg-2", 2.0, 4.0)])
        self.assertEqual(errors, [])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["segment_id"], "seg-1")
        self.assertEqual(plans[0]["mask_slug"], "circle")

    def test_invalid_shot_and_mask_are_rejected(self):
        from workflow.advanced_fx import resolve
        cfg = {"shot_fx": {"enabled": True, "items": [
            {"shot": 9, "mask": {"type": "circle"}},
            {"shot": 1, "mask": {"type": "hexagon"}},
        ]}}
        plans, errors = resolve(cfg, [("seg-1", 0.0, 2.0)])
        self.assertEqual(plans, [])
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
