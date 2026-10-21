import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import font_picker  # noqa: E402
from workflow.emfont import EmfontError  # noqa: E402


def candidate(ident, name, category, *, source="local", weight=900,
              license="OFL-1.1", suggest=None, tags=None):
    return {
        "id": ident, "name": name, "display": name, "source": source,
        "family": name, "suggest": suggest or name, "category": category,
        "tags": tags or [font_picker.CATEGORY_TAGS.get(category, category)],
        "weights": [str(weight)], "weight": weight, "license": license,
        "description": "测试字体",
    }


def profile():
    return {
        "source": {"meta": {"title": "AI 工具怎么选：3 个步骤"}},
        "breakdown": {"overview": {
            "hook": "先问一个问题：为什么你的画面没有科技感？",
            "structure": "问题→方法→对比→行动",
            "visual_style": "冷色调、科技感、极简、深色背景",
            "rhythm": "平均 2 秒一刀",
            "audio": "口播解释步骤",
            "target_audience": "想做短视频的职场人",
            "why_it_works": ["问题具体", "步骤清楚"],
        }},
        "style": {"aspect": "9:16", "caption_band": {"note": "底部白字"}},
        "pacing": {"used_cuts_per_minute": 30},
        "transcript": {"text": "为什么你的画面没有科技感？三个步骤解决。"},
        "recommendations": {"copy": {"hook": "为什么你的画面没有科技感？"}},
    }


def make_project(root: Path, font="Old Font", lock_font=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(exist_ok=True)
    (root / "work").mkdir(exist_ok=True)
    (root / "input" / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n为什么你的画面没有科技感\n", encoding="utf-8")
    (root / "config.json").write_text(json.dumps({
        "name": "demo", "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "captions": {"font": font, "size": 90},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if lock_font:
        (root / "work" / "style-lock.json").write_text(json.dumps({
            "version": "1.0.0", "id": "KB-TH-99", "name": "锁测",
            "recipe_sha256": "x",
            "recipe": {"style": {"captions": {"font": lock_font}}},
        }, ensure_ascii=False), encoding="utf-8")


class BriefTests(unittest.TestCase):
    def test_brief_extracts_signals_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project)
            from _common import load_config
            brief = font_picker.build_brief(
                project, load_config(project / "config.json"), profile())
        self.assertIn("tech", brief["signals"])
        self.assertEqual(brief["caption_chars"], len("为什么你的画面没有科技感"))
        self.assertIn("科技", brief["caption_sample"] + brief["overview"]["visual_style"])
        self.assertEqual(brief["existing_font"], "Old Font")

    def test_local_font_scoring_prefers_matching_category(self):
        brief = font_picker.build_brief(None, None, profile())
        sans = candidate("a", "科技黑体", "sans")
        hand = candidate("b", "手写体", "handwriting")
        self.assertGreater(font_picker.score_candidate(sans, brief),
                           font_picker.score_candidate(hand, brief))

    def test_restricted_license_is_penalized_for_commercial(self):
        brief = font_picker.build_brief(None, None, profile())
        brief["commercial"] = True
        good = candidate("a", "可商用黑体", "sans", license="OFL-1.1")
        bad = candidate("b", "非商业黑体", "sans", license="CC BY-NC 4.0")
        self.assertGreater(font_picker.score_candidate(good, brief),
                           font_picker.score_candidate(bad, brief))

    def test_license_tier(self):
        self.assertEqual(font_picker.license_tier("SIL OFL 1.1"), "permissive")
        self.assertEqual(font_picker.license_tier("CC BY-NC 4.0"), "restricted")
        self.assertEqual(font_picker.license_tier("系统字体（仅本机渲染）"), "system")
        self.assertEqual(font_picker.license_tier("unknown"), "unknown")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            candidate("local:a", "科技黑体", "sans", weight=900),
            candidate("local:b", "宋体标题", "serif", weight=700),
            candidate("emfont:c", "圆体", "rounded", source="emfont", weight=700),
        ]

    def test_fallback_without_ai(self):
        with mock.patch.object(font_picker, "local_candidates", return_value=self.candidates):
            result = font_picker.select(None, profile(), library="local",
                                        no_llm=True, log=lambda *_: None)
        self.assertEqual(result["mode"], "fallback")
        self.assertEqual(result["selected"]["id"], "local:a")
        self.assertTrue(result["unchecked"])

    def test_reference_is_auto_loaded_from_project_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project)
            (project / "work" / "reference").mkdir()
            (project / "work" / "reference" / "reference-profile.json").write_text(
                json.dumps(profile(), ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(font_picker, "local_candidates",
                                   return_value=self.candidates):
                result = font_picker.select(project, library="local", no_llm=True,
                                            log=lambda *_: None)
        self.assertIn("tech", result["brief"]["signals"])
        self.assertEqual(result["brief"]["existing_font"], "Old Font")

    def test_ai_selection_is_validated_and_used(self):
        def transport(body, key):
            return {"choices": [{"message": {"content": json.dumps({
                "selected_id": "local:b", "confidence": 0.81,
                "reason": "宋体更贴近叙事感", "usage": "caption", "weight": 700,
                "alternates": ["local:a"], "risk": "系统字体需核对", "unchecked": [],
            })}}], "usage": {"prompt_tokens": 10}}

        with mock.patch.object(font_picker, "local_candidates", return_value=self.candidates):
            result = font_picker.select(None, profile(), library="local",
                                        api_key="test", transport=transport,
                                        log=lambda *_: None)
        self.assertEqual(result["mode"], "ai")
        self.assertEqual(result["selected"]["id"], "local:b")
        self.assertEqual(result["confidence"], 0.81)

    def test_invalid_ai_output_falls_back(self):
        def transport(body, key):
            return {"choices": [{"message": {"content": json.dumps({
                "selected_id": "not-a-candidate", "confidence": 0.9,
                "reason": "乱选", "usage": "caption", "weight": 700,
                "alternates": [], "risk": "",
            })}}]}

        with mock.patch.object(font_picker, "local_candidates", return_value=self.candidates):
            result = font_picker.select(None, profile(), library="local",
                                        api_key="test", transport=transport,
                                        log=lambda *_: None)
        self.assertEqual(result["mode"], "fallback")
        self.assertTrue(any("AI 选择失败" in warning for warning in result["warnings"]))

    def test_emfont_outage_does_not_block_local(self):
        with mock.patch.object(font_picker, "local_candidates", return_value=self.candidates), \
             mock.patch.object(font_picker, "emfont_candidates",
                               side_effect=EmfontError("down")):
            result = font_picker.select(None, profile(), library="auto",
                                        no_llm=True, log=lambda *_: None)
        self.assertEqual(result["selected"]["id"], "local:a")
        self.assertTrue(any(row["item"] == "emfont 字体库" for row in result["unchecked"]))

    def test_validate_rejects_out_of_set(self):
        with self.assertRaises(font_picker.FontPickerError):
            font_picker.validate_selection({"selected_id": "x", "confidence": 0.5,
                                            "reason": "r", "usage": "caption",
                                            "weight": 700, "alternates": []},
                                           self.candidates)

    def test_strict_license_filters_unknown(self):
        rows = [
            candidate("a", "A", "sans", license="OFL-1.1"),
            candidate("b", "B", "sans", license="unknown"),
            candidate("c", "C", "sans", license="CC BY-NC"),
        ]
        self.assertEqual([row["id"] for row in font_picker.filter_license(rows, True)],
                         ["a"])


class ApplyTests(unittest.TestCase):
    def _result(self, ident="local:a", suggest="Fake Family Black", source="local"):
        selected = candidate(ident, "Fake Family Black", "sans", suggest=suggest)
        selected["source"] = source
        return {
            "schema": font_picker.SCHEMA, "generated_at": "2026-10-20T11:00:00+08:00",
            "brief": {"caption_sample": "测试字幕", "signals": ["tech"]},
            "selected": selected, "alternates": [],
            "mode": "fallback", "confidence": 0.5, "reason": "测试",
            "usage": "caption", "risk": "无", "warnings": [], "unchecked": [],
            "applied": None, "apply_blocked": None,
        }

    def test_apply_local_writes_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project)
            with mock.patch.object(font_picker, "find_font", return_value=Path("/tmp/fake.ttf")), \
                 mock.patch.object(font_picker, "has_cjk_glyphs", return_value=True), \
                 mock.patch.object(font_picker, "font_display_name", return_value="Fake Family"):
                result = font_picker.apply_selection(project, self._result(),
                                                     log=lambda *_: None)
            config = json.loads((project / "config.json").read_text(encoding="utf-8"))
            report = json.loads((project / "work" / "font-selection.json").read_text(encoding="utf-8"))
            self.assertTrue((project / "work" / "font-selection.md").is_file())
        self.assertEqual(config["captions"]["font"], "Fake Family Black")
        self.assertEqual(result["applied"]["source"], "local")
        self.assertEqual(report["applied"]["font"], "Fake Family Black")

    def test_style_lock_blocks_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project, lock_font="Locked Font")
            result = font_picker.apply_selection(project, self._result(),
                                                 log=lambda *_: None)
            config = json.loads((project / "config.json").read_text(encoding="utf-8"))
        self.assertIsNone(result["applied"])
        self.assertEqual(result["apply_blocked"]["locked_font"], "Locked Font")
        self.assertEqual(config["captions"]["font"], "Old Font")

    def test_style_lock_blocks_a_different_weight_of_the_same_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project, lock_font="Fake Family")
            result = font_picker.apply_selection(project, self._result(),
                                                 log=lambda *_: None)
            config = json.loads((project / "config.json").read_text(encoding="utf-8"))
        self.assertIsNone(result["applied"])
        self.assertEqual(config["captions"]["font"], "Old Font")

    def test_style_lock_can_be_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project, lock_font="Locked Font")
            with mock.patch.object(font_picker, "find_font", return_value=Path("/tmp/fake.ttf")), \
                 mock.patch.object(font_picker, "has_cjk_glyphs", return_value=True), \
                 mock.patch.object(font_picker, "font_display_name", return_value="Fake Family"):
                result = font_picker.apply_selection(project, self._result(), force=True,
                                                     log=lambda *_: None)
            config = json.loads((project / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(result["style_lock_conflict"])
        self.assertEqual(config["captions"]["font"], "Fake Family Black")

    def test_apply_emfont_downloads_subset_and_writes_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            make_project(project)
            selected = candidate("emfont:x", "圆体", "rounded", source="emfont",
                                 suggest="圆体", weight=700)
            selected["emfont_id"] = "x"
            selected["license"] = "OFL-1.1"
            result = {
                "schema": font_picker.SCHEMA, "generated_at": "2026-10-20T11:00:00+08:00",
                "brief": {"caption_sample": "测试字幕"}, "selected": selected,
                "alternates": [], "mode": "ai", "confidence": 0.8,
                "reason": "测试", "usage": "caption", "risk": "无",
                "warnings": [], "unchecked": [], "applied": None, "apply_blocked": None,
            }
            font_file = project / "fonts" / "emfont-x.ttf"
            font_file.parent.mkdir(parents=True, exist_ok=True)
            font_file.write_bytes(b"\x00\x01\x00\x00fake")

            def fake_generate(font_id, words, **kwargs):
                self.assertEqual(font_id, "x")
                self.assertIn("科技", words)
                return {"locations": ["https://cdn.test/x.ttf"], "words": len(words)}

            with mock.patch.object(font_picker.emfont, "generate_font", side_effect=fake_generate), \
                 mock.patch.object(font_picker.emfont, "download_first",
                                   return_value=(font_file, "https://cdn.test/x.ttf")), \
                 mock.patch.object(font_picker, "font_display_name", return_value="Emfont Family"), \
                 mock.patch.object(font_picker, "missing_glyphs", return_value=[]):
                result = font_picker.apply_selection(project, result, log=lambda *_: None)
            config = json.loads((project / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["captions"]["font"], "Emfont Family")
        self.assertEqual(result["applied"]["source"], "emfont")
        self.assertEqual(result["applied"]["emfont_id"], "x")


if __name__ == "__main__":
    unittest.main()
