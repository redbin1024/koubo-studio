import sys, tempfile, unittest
from pathlib import Path
from PIL import Image, ImageDraw  # noqa: F401  (ensure PIL env is loaded like the rest)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class GroundingTests(unittest.TestCase):
    def test_brand_without_spoken_evidence_fails(self):
        from workflow.grounding import check
        from _common import ensure_dirs, load_config, project_paths, write_json
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dirs(Path(tmp) / "p")
            write_json(p["config"], {})
            cfg = load_config(p["config"])
            cfg["card"] = {"enabled": True, "title": "多萌十月", "rows": [],
                           "theme": {"footnote": "预约参观"}}
            write_json(p["config"], cfg)
            (p["input"] / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n咱们月子中心\n", encoding="utf-8")
            write_json(p["work"] / "transcript.json", {"text": "咱们月子中心"})
            ok, detail = check(load_config(p["config"]), Path(p["root"]))
            self.assertFalse(ok)
            self.assertIn("多萌", detail)

    def test_allowlisted_brand_is_unchecked_not_pass(self):
        from workflow.grounding import check
        from _common import ensure_dirs, load_config, project_paths, write_json
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dirs(Path(tmp) / "p")
            write_json(p["config"], {})
            cfg = load_config(p["config"])
            cfg["card"] = {"enabled": True, "title": "预约参观", "rows": []}
            cfg["claims"] = {"allow": ["预约", "参观"]}
            write_json(p["config"], cfg)
            (p["input"] / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n咱们月子中心\n", encoding="utf-8")
            write_json(p["work"] / "transcript.json", {"text": "咱们月子中心"})
            ok, detail = check(load_config(p["config"]), Path(p["root"]))
            self.assertIsNone(ok)
            self.assertIn("人工保留", detail)

    def test_brand_with_spoken_evidence_passes(self):
        from workflow.grounding import check
        from _common import ensure_dirs, load_config, project_paths, write_json
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dirs(Path(tmp) / "p")
            write_json(p["config"], {})
            cfg = load_config(p["config"])
            cfg["card"] = {"enabled": True, "title": "多萌十月", "rows": [],
                           "theme": {"footnote": "预约参观"}}
            write_json(p["config"], cfg)
            (p["input"] / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n多萌十月 预约参观\n", encoding="utf-8")
            write_json(p["work"] / "transcript.json", {"text": "多萌十月 预约参观"})
            ok, _ = check(load_config(p["config"]), Path(p["root"]))
            self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
