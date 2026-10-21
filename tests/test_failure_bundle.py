import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class FailureBundleTests(unittest.TestCase):
    def test_capture_writes_manifest(self):
        from workflow.failure_bundle import capture
        from _common import ensure_dirs, write_json
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dirs(Path(tmp) / "p")
            write_json(p["config"], {"name": "t"})
            write_json(p["work"] / "qc-report.json", {"checks": []})
            dest = capture(Path(p["root"]), "render", "boom")
            self.assertTrue((dest / "failure.json").is_file())
            data = json.loads((dest / "failure.json").read_text(encoding="utf-8"))
            self.assertEqual(data["step"], "render")
            self.assertIn("config.json", data["copied"])


if __name__ == "__main__":
    unittest.main()
