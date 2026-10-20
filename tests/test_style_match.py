import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StyleMatchTests(unittest.TestCase):
    def test_content_with_detail_list_prefers_glass_stack(self):
        from style_match import match
        from _common import ensure_dirs, write_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            p = ensure_dirs(project)
            cfg = {"name": "t", "duration": 20.0, "canvas": {"width": 1080, "height": 1920, "fps": 30},
                   "input": {"subtitle": "captions.srt"}, "card": {"theme": {"skin": "glass"}}}
            write_json(p["config"], cfg)
            (p["input"] / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n这些细节\n\n"
                "2\n00:00:02,000 --> 00:00:06,000\n第一 营养餐 第二 房间 第三 照护\n",
                encoding="utf-8")
            catalog = root / "catalog.json"
            recipes = root / "recipes"
            recipes.mkdir()
            rows = []
            for sid, grammar, status in (("TH-DY-08", "d08_glass_stack", "partial_native_windows_reviewed"),
                                          ("TH-DY-13", "d13_cutout_outline", "partial_native_windows_reviewed")):
                recipe = {"id": sid, "name": sid, "version": "0.1.0",
                          "readiness": {"status": status}, "semantic_use": ["步骤列表与信息层级"],
                          "observed_motion": "三卡展开", "basic_implementation": {"grammar": grammar}}
                rp = recipes / f"{sid}.json"
                rp.write_text(json.dumps(recipe), encoding="utf-8")
                rows.append({"id": sid, "name": sid, "version": "0.1.0",
                             "recipe": f"recipes/{sid}.json", "readiness": {"status": status}})
            catalog.write_text(json.dumps({"styles": rows}), encoding="utf-8")
            result = match(project, catalog, 3)
            self.assertEqual(result["matches"][0]["id"], "TH-DY-08")


if __name__ == "__main__":
    unittest.main()
