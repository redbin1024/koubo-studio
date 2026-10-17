"""逐条字幕样式计划：默认行为不许漂、指令写错要炸、动效映射要齐。"""
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults, caption_plain  # noqa: E402
from workflow.caption_plan import (  # noqa: E402
    ANIM_PLAN, ANIMS, JY_ANIM, CaptionPlanError, build_plan, parse_cue_directives,
)


def make_project(directory: Path, body: str, **captions) -> Path:
    project = Path(directory)
    (project / "input").mkdir(parents=True, exist_ok=True)
    (project / "work").mkdir(parents=True, exist_ok=True)
    (project / "input" / "captions.srt").write_text(body, encoding="utf-8")
    cfg = apply_defaults({"input": {"subtitle": "captions.srt"},
                          "captions": dict(captions)})
    return project, cfg


PLAIN = ("1\n00:00:00,000 --> 00:00:02,000\n第一句话\n\n"
         "2\n00:00:02,000 --> 00:00:04,000\n第二句话\n\n"
         "3\n00:00:04,000 --> 00:00:06,000\n第三句话")


class CaptionPlanDefaults(unittest.TestCase):
    """没有指令、没有自定义样式时，逐条行为必须等于加这套东西之前。"""

    def test_first_cue_hooks_and_the_rest_fade(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), PLAIN)
            plan = build_plan(cfg, project)
            self.assertEqual([c["anim"] for c in plan["cues"]], ["hook", "fade", "fade"])

    def test_hook_disabled_means_every_cue_fades(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(
                Path(tmp), PLAIN, hook={"enabled": False, "scale": 330, "accel": 2.6, "ms": 600})
            plan = build_plan(cfg, project)
            self.assertEqual({c["anim"] for c in plan["cues"]}, {"fade"})

    def test_look_comes_from_config_and_draft_anim_keeps_the_old_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), PLAIN)
            plan = build_plan(cfg, project)
            first = plan["cues"][0]
            self.assertEqual(first["size"], cfg["captions"]["size"])
            self.assertEqual(first["outline"], cfg["captions"]["outline"])
            self.assertEqual(first["layout"], "bottom")
            self.assertEqual([c["jy_anim"] for c in plan["cues"]],
                             list(ANIM_PLAN[:3]))

    def test_skipped_cues_do_not_shift_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), PLAIN, skip=[1])
            plan = build_plan(cfg, project)
            self.assertEqual([c["index"] for c in plan["cues"]], [2, 3])
            # 跳过的那条不占位：剩下第一条仍然吃 hook。
            self.assertEqual(plan["cues"][0]["anim"], "hook")


class CaptionPlanDirectives(unittest.TestCase):
    def test_named_style_and_overrides_apply_to_one_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = PLAIN.replace("第二句话", "{@default layout=center anim=pop}第二句话")
            project, cfg = make_project(Path(tmp), body)
            plan = build_plan(cfg, project)
            self.assertEqual(plan["cues"][1]["layout"], "center")
            self.assertEqual(plan["cues"][1]["anim"], "pop")
            self.assertEqual(plan["cues"][1]["lines"], ["第二句话"])
            self.assertEqual(plan["cues"][0]["layout"], "bottom")

    def test_custom_style_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = PLAIN.replace("第三句话", "{@hero}第三句话")
            project, cfg = make_project(Path(tmp), body,
                                        styles={"hero": {"size": 120, "layout": "center"}})
            plan = build_plan(cfg, project)
            hero = plan["cues"][2]
            self.assertEqual((hero["style"], hero["size"], hero["layout"]),
                             ("hero", 120, "center"))

    def test_bare_override_without_style_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = PLAIN.replace("第三句话", "{@layout=side anim=rise}第三句话")
            project, cfg = make_project(Path(tmp), body)
            plan = build_plan(cfg, project)
            self.assertEqual((plan["cues"][2]["style"], plan["cues"][2]["layout"],
                              plan["cues"][2]["anim"]), ("default", "side", "rise"))

    def test_directive_never_reaches_the_text(self):
        directive, cleaned = parse_cue_directives("{@big layout=center}大字卡")
        self.assertEqual(cleaned, "大字卡")
        self.assertEqual(directive["style"], "big")
        self.assertEqual(caption_plain("{@big layout=center}大字[[卡]]"), "大字卡")

    def test_malformed_directives_raise(self):
        for raw in ("{@}", "{@hero anim=fly}", "{@hero size=120}", "{@hero 密钥}",
                    "{@hero anim=pop", "{@default layout=middle}"):
            with self.subTest(raw=raw), self.assertRaises(CaptionPlanError):
                parse_cue_directives(raw)

    def test_unknown_style_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = PLAIN.replace("第二句话", "{@nope}第二句话")
            project, cfg = make_project(Path(tmp), body)
            with self.assertRaisesRegex(CaptionPlanError, "nope"):
                build_plan(cfg, project)


class CaptionPlanBigCard(unittest.TestCase):
    def test_big_card_may_not_open_the_film(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = PLAIN.replace("第一句话", "{@big}大字卡")
            project, cfg = make_project(Path(tmp), body)
            with self.assertRaisesRegex(CaptionPlanError, "开头封面"):
                build_plan(cfg, project)

    def test_big_card_later_is_fine_and_uses_the_big_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = PLAIN.replace("第三句话", "{@big}大字卡")
            project, cfg = make_project(Path(tmp), body)
            plan = build_plan(cfg, project)
            big = plan["cues"][2]
            self.assertTrue(big["big"])
            self.assertEqual(big["size"], cfg["captions"]["big"]["size"])
            self.assertEqual(big["layout"], "center")


class CaptionPlanContract(unittest.TestCase):
    def test_every_animation_maps_to_a_draft_animation(self):
        self.assertEqual(set(ANIMS), set(JY_ANIM))

    def test_plan_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), PLAIN)
            self.assertEqual(build_plan(cfg, project), build_plan(cfg, project))

    def test_theme_overrides_font_and_accents(self):
        """主题要真的能一键换观感：生成的工程总是显式写着 font/palette，
        如果主题只是「当默认值」，它就永远不会生效。"""
        with tempfile.TemporaryDirectory() as tmp:
            project, cfg = make_project(Path(tmp), PLAIN, theme="screen-clean",
                                        palette={"accent": "#123456"})
            self.assertEqual(cfg["captions"]["font"], "Hiragino Sans GB W6")
            self.assertEqual(cfg["captions"]["palette"]["accent"], "#4DD0E1")
            self.assertEqual(cfg["captions"]["palette"]["white"], "#FFFFFF")   # 主题不管的键不动

    def test_unknown_theme_raises(self):
        with self.assertRaisesRegex(ValueError, "没有这个字幕主题"):
            apply_defaults({"captions": {"theme": "no-such-theme"}})


if __name__ == "__main__":
    unittest.main()
