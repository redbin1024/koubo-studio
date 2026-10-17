"""插图：画得出来、没触发词不准上、不压字幕带、关掉时要如实记没查。"""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults, find_font  # noqa: E402
from make_assets import insert_card  # noqa: E402
from workflow.caption_plan import (  # noqa: E402
    INSERT_KINDS, CaptionPlanError, build_plan, caption_band_top,
)

SRT = ("1\n00:00:00,000 --> 00:00:02,000\n第一句话\n\n"
       "2\n00:00:02,000 --> 00:00:06,400\n那一份份被准时送到的营养餐\n\n"
       "3\n00:00:06,400 --> 00:00:08,000\n第三句话")


def make_project(directory: Path, items, **inserts):
    project = Path(directory)
    (project / "input").mkdir(parents=True, exist_ok=True)
    (project / "work").mkdir(parents=True, exist_ok=True)
    (project / "input" / "captions.srt").write_text(SRT, encoding="utf-8")
    block = {"enabled": True, "items": items}
    block.update(inserts)
    cfg = apply_defaults({"input": {"subtitle": "captions.srt"}, "inserts": block})
    return project, cfg


GOOD = {"kind": "icon-label", "trigger": {"cue": 2, "keyword": "准时"},
        "icon": "clock", "title": "准时送达", "text": "精致的营养餐", "hold": 2.4}


class InsertPlanTests(unittest.TestCase):
    def test_disabled_inserts_do_not_change_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), [GOOD], enabled=False)
            plan = build_plan(cfg, project)
            self.assertFalse(plan["inserts"]["enabled"])
            self.assertEqual(plan["inserts"]["items"], [])
            self.assertNotIn("insert-1.png", str(plan))

    def test_a_grounded_insert_resolves_to_a_window_inside_its_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), [GOOD])
            item = build_plan(cfg, project)["inserts"]["items"][0]
            self.assertEqual(item["asset"], "insert-1.png")
            self.assertEqual(item["trigger_cue"], 2)
            self.assertGreaterEqual(item["start"], 2.0)
            self.assertLessEqual(item["end"], 6.4)

    def test_insert_without_a_real_trigger_word_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {**GOOD, "trigger": {"cue": 2, "keyword": "高端"}}
            project, cfg = make_project(Path(tmp), [bad])
            with self.assertRaisesRegex(CaptionPlanError, "必须由字幕触发"):
                build_plan(cfg, project)

    def test_insert_pointing_at_a_missing_cue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {**GOOD, "trigger": {"cue": 99, "keyword": "准时"}}
            project, cfg = make_project(Path(tmp), [bad])
            with self.assertRaisesRegex(CaptionPlanError, "#99"):
                build_plan(cfg, project)

    def test_insert_that_would_cover_the_caption_band_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {**GOOD, "box": [0.10, 0.55, 0.90, 0.95]}
            project, cfg = make_project(Path(tmp), [bad])
            with self.assertRaisesRegex(CaptionPlanError, "压进字幕带"):
                build_plan(cfg, project)

    def test_insert_longer_than_its_cue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {**GOOD, "hold": 9.0}
            project, cfg = make_project(Path(tmp), [bad])
            with self.assertRaisesRegex(CaptionPlanError, "超出它的触发范围"):
                build_plan(cfg, project)

    def test_unknown_kind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {**GOOD, "kind": "sparkle"}
            project, cfg = make_project(Path(tmp), [bad])
            with self.assertRaisesRegex(CaptionPlanError, "kind"):
                build_plan(cfg, project)

    def test_caption_band_top_is_a_conservative_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), [GOOD])
            top = caption_band_top(cfg)
            self.assertLess(top, 1.0)
            self.assertGreater(top, 0.5)


class InsertDrawingTests(unittest.TestCase):
    def draw(self, spec, box=(100, 1000, 980, 1360)):
        font = find_font("Noto Sans CJK SC Black", ROOT)
        return insert_card(1080, 1920, box, spec,
                           {"bg": "#FBF7EF", "fg": "#241F1A", "accent": "#E8B84B"},
                           font, font, 28)

    def test_every_kind_draws_opaque_pixels_inside_its_box(self):
        for kind in INSERT_KINDS:
            with self.subTest(kind=kind):
                spec = {"kind": kind, "icon": "clock", "title": "准时送达",
                        "text": "精致的营养餐", "rows": ["一条", "两条"]}
                art = self.draw(spec)
                self.assertEqual(art.size, (1080, 1920))
                inside = art.crop((100, 1000, 980, 1360)).getchannel("A")
                self.assertGreater(inside.getextrema()[1], 200)

    def test_every_icon_draws_something_without_crashing(self):
        for icon in ("leaf", "clock", "bowl", "heart", "home", "check", "star", "shield"):
            with self.subTest(icon=icon):
                art = self.draw({"kind": "icon-label", "icon": icon, "title": "标题",
                                 "text": "副标题"})
                self.assertGreater(art.getchannel("A").getextrema()[1], 200)

    def test_card_stays_inside_its_box(self):
        art = self.draw({"kind": "quote", "icon": "check", "title": "", "text": "一段引语"})
        outside = art.crop((0, 0, 1080, 900)).getchannel("A")
        self.assertEqual(outside.getextrema()[1], 0)


if __name__ == "__main__":
    unittest.main()
