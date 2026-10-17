import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import apply_defaults, ensure_dirs  # noqa: E402
import make_captions  # noqa: E402


class EmptyCaptionTests(unittest.TestCase):
    def test_empty_srt_generates_valid_empty_ass(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            p = ensure_dirs(project)
            p["input"].joinpath("captions.srt").write_text("", encoding="utf-8")
            cfg = apply_defaults({"name": "empty", "duration": 2.0})
            result = make_captions.build(cfg, project)
            self.assertEqual(result["count"], 0)
            ass = (p["captions"] / "final.ass").read_text(encoding="utf-8")
            self.assertIn("[Events]", ass)
            self.assertNotIn("Dialogue:", ass)


if __name__ == "__main__":
    unittest.main()
