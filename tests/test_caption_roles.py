import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class CaptionRoleTests(unittest.TestCase):
    def test_insert_repeating_caption_is_flagged(self):
        from workflow.caption_roles import audit
        cues = [{"index": 7, "start": 19.39, "end": 24.23,
                 "lines": ["那一句放心我们一直都在", "带来的安心"]}]
        contract = {"beats": [{"id": "insert-1", "kind": "insert",
                               "start": 19.51, "end": 21.71,
                               "source_texts": ["放心", "我们一直都在"]}]}
        result = audit(contract, cues)
        self.assertTrue(result["findings"])
        self.assertEqual(result["findings"][0]["match"], "duplicate")

    def test_independent_brand_label_is_not_flagged(self):
        from workflow.caption_roles import audit
        cues = [{"index": 12, "start": 40.46, "end": 42.59,
                 "lines": ["月子中心", "坚持的意义"]}]
        contract = {"beats": [{"id": "gold-1", "kind": "gold",
                               "start": 40.5, "end": 41.5,
                               "source_texts": ["多萌十月"]}]}
        self.assertEqual(audit(contract, cues)["findings"], [])


if __name__ == "__main__":
    unittest.main()
