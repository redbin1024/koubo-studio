import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class IllustrationTests(unittest.TestCase):
    def test_referenced_illustrations_are_collected(self):
        from render_illustrations import referenced
        cfg = {"inserts": {"items": [
            {"illustration": "illustrations/car-seat.png"},
            {"illustration": "illustrations/crib.png"},
            {"title": "no art"},
        ]}, "card": {"rows": [
            {"illustration": "illustrations/food-tray.png"},
        ]}}
        self.assertEqual(referenced(cfg), {"car-seat", "crib", "food-tray"})


if __name__ == "__main__":
    unittest.main()
