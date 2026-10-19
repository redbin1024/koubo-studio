import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _cfg():
    return {
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "captions": {"font": "Noto Sans CJK SC Black", "size": 90,
                     "outline": 10, "shadow": 6, "spacing": 1.5,
                     "layout": "bottom", "skip": [5]},
        "card": {"fill": "#F7F3EC", "radius": 38, "title": "内容标题",
                 "rows": [{"title": "内容行"}], "theme": {"skin": "glass",
                                                          "footnote": "内容脚注"}},
        "inserts": {"layout": "band", "box": [0.1, 0.54, 0.9, 0.72],
                    "items": [{"title": "内容插图"}]},
        "gold": {"size": 100, "text": "内容品牌"},
        "grade": {"eq": "eq=contrast=1.06", "blur": "gblur=sigma=20", "darken": 0.2},
        "jianying_fx": {"effects": [{"name": "光晕", "at": 0.0, "intensity": 0.25}],
                        "filters": [{"name": "暖食", "intensity": 0.16}],
                        "transitions": [{"name": "叠化", "at": 1.0, "dur": 0.36}]},
    }


class StyleLockTests(unittest.TestCase):
    def test_projection_excludes_content(self):
        from workflow.style_lock import projection
        style = projection(_cfg())
        text = json.dumps(style, ensure_ascii=False)
        self.assertNotIn("内容标题", text)
        self.assertNotIn("内容行", text)
        self.assertNotIn("内容插图", text)
        self.assertNotIn("内容脚注", text)
        self.assertNotIn("skip", text)
        self.assertEqual(style["captions"]["size"], 90)

    def test_bind_then_detect_style_drift(self):
        from workflow.style_lock import bind, projection, validate
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _cfg()
            recipe = {"id": "KB-TH-01", "name": "测试风格", "version": "1.0.0",
                      "style": projection(cfg)}
            recipe_path = root / "recipe.json"
            recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
            import hashlib
            digest = hashlib.sha256(recipe_path.read_bytes()).hexdigest()
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"styles": [{
                "id": "KB-TH-01", "name": "测试风格", "version": "1.0.0",
                "recipe": "recipe.json", "recipe_sha256": digest,
                "readiness": {"status": "test"}}]}), encoding="utf-8")
            project = root / "project"
            (project / "work").mkdir(parents=True)
            bind(project, "KB-TH-01", "单测选择", path=catalog)
            self.assertTrue(validate(project, cfg, path=catalog)["ok"])
            cfg["captions"]["size"] = 120
            result = validate(project, cfg, path=catalog)
            self.assertFalse(result["ok"])
            self.assertTrue(any("captions.size" in x for x in result["issues"]))


if __name__ == "__main__":
    unittest.main()
