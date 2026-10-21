import sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class ReviewOutputTests(unittest.TestCase):
    def test_caption_asr_coverage_pass(self):
        from review_outputs import _caption_asr
        from _common import ensure_dirs, write_json
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dirs(Path(tmp) / "p")
            (p["input"] / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n咱们月子中心\n", encoding="utf-8")
            write_json(p["work"] / "transcript.json", {"text": "咱们月子中心"})
            ok, detail = _caption_asr(Path(p["root"]))
            self.assertTrue(ok)
            self.assertIn("1.00", detail)


if __name__ == "__main__":
    unittest.main()
