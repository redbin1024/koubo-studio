import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _beat(asset: Path):
    return {
        "id": "insert-1", "kind": "insert", "structure": "icon-label",
        "start": 1.0, "end": 3.0, "style_id": "editorial-insert",
        "visible_feature": {"description": "图标+标题+正文", "region": [0.1, 0.5, 0.9, 0.7]},
        "reading": {"start": 1.3, "end": 3.0, "stable_text": True, "description": "稳定"},
        "motion": {"mechanism": "rise", "phase": "semantic-completion",
                   "windows": [[1.0, 1.3]], "description": "上浮"},
        "assets": [{"id": "insert-1", "kind": "authored-graphic",
                     "path": str(asset), "exists": True, "sha256": ""}],
        "claim_status": "speech", "evidence_refs": [], "native": False,
    }


class VisualContractTests(unittest.TestCase):
    def test_valid_contract_passes(self):
        from workflow.visual_contract import validate
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "insert-1.png"
            asset.write_bytes(b"x")
            self.assertEqual(validate({"version": 1, "beats": [_beat(asset)]}), [])

    def test_bad_region_reading_and_sourced_claim_fail(self):
        from workflow.visual_contract import validate
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "insert-1.png"
            asset.write_bytes(b"x")
            beat = _beat(asset)
            beat["visible_feature"]["region"] = [0.9, 0.1, 0.2, 0.2]
            beat["reading"]["end"] = 1.2
            beat["claim_status"] = "sourced"
            issues = validate({"version": 1, "beats": [beat]})
            text = "\n".join(issues)
            self.assertIn("region", text)
            self.assertIn("阅读窗口", text)
            self.assertIn("evidence_refs", text)


if __name__ == "__main__":
    unittest.main()
