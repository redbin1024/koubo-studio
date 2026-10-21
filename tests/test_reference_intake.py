import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reference_intake as intake  # noqa: E402


def fixture_teardown(card_area=0.2):
    return {
        "accent_colors": [
            {"hex": "#F0C030", "hue": "yellow", "share": 0.4},
            {"hex": "#E05028", "hue": "red", "share": 0.2},
        ],
        "caption_band": {"detected": True, "y_top_norm": 0.72, "y_bottom_norm": 0.9,
                         "x_min_norm": 0.08, "x_max_norm": 0.92},
        "card": {"start": 2.0, "end": 5.0, "bbox_norm": [0.1, 0.2, 0.9, 0.8],
                 "fill_hex": "#222222", "area": card_area},
        "pip": {"bbox_norm": [0.55, 0.55, 0.95, 0.9], "area": 0.1},
        "flat_bands": [{"y_from": 0.0, "y_to": 0.1, "gradient": 1.2},
                       {"y_from": 0.9, "y_to": 1.0, "gradient": 4.0}],
    }


def fixture_pacing(duration=10.0):
    return {
        "duration": duration, "width": 1080, "height": 1920, "avg_fps": 30.0,
        "vfr_suspect": False, "loudness": {"input_i": -14.2, "input_tp": -1.1},
        "pacing": {"shot_count": 3, "cut_count": 2, "cuts_per_minute": 12.0,
                   "avg_shot_duration": 3.3, "median_shot_duration": 3.2,
                   "min_shot_duration": 2.0, "max_shot_duration": 4.0},
        "cuts": [{"t": 2.0, "score": 0.5}, {"t": 5.0, "score": 0.7}],
    }


def fixture_rows():
    return [
        {"id": "s01", "index": 1, "start": 0.0, "end": 2.0, "duration": 2.0,
         "cut": "hard", "status": "ok", "strip": "frames/strip-01.jpg",
         "keyframe": "frames/shot-01.jpg", "strip_times": [0.1, 1.0, 1.9]},
        {"id": "s02", "index": 2, "start": 2.0, "end": 5.0, "duration": 3.0,
         "cut": "hard", "status": "ok", "strip": "frames/strip-02.jpg",
         "keyframe": "frames/shot-02.jpg", "strip_times": [2.1, 3.5, 4.9]},
    ]


def fixture_breakdown():
    shot = {"shot_size": "近景", "camera": "固定", "subject": "人", "action": "说话",
            "action_phases": ["开口"], "end_state": "settled", "scene": "室内",
            "lighting": "柔光", "on_screen_text": "无", "transition": "硬切",
            "hook_role": "钩子", "hidden_cut": False, "evidence": "三格人物一致",
            "confidence": 0.8}
    return {
        "status": "ok",
        "overview": {"hook": "先抛问题", "structure": "问题→方法→对比",
                     "visual_style": "暖色近景", "rhythm": "2-3 秒一刀",
                     "audio": "口播解释", "why_it_works": ["问题具体"],
                     "adaptation": ["保留前 3 秒顺序"], "target_audience": "新手"},
        "shots": {"s01": dict(shot), "s02": dict(shot, hook_role="展开")},
        "warnings": [], "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def fixture_source():
    return {
        "platform": "douyin", "engine": "share_page",
        "input": "https://v.douyin.com/x/", "resolved_url": "https://www.iesdouyin.com/...",
        "aweme_id": "7525538910311632128", "fetched_at": "2026-10-20T11:00:00+08:00",
        "meta": {"title": "参考片", "author": "作者", "duration": 10.0},
        "warnings": [],
    }


def fixture_profile():
    transcript = {
        "status": "ok", "model": "small", "language": "zh", "duration": 10.0,
        "words": [{"text": "第一句", "start": 0.0, "end": 1.0, "confidence": 0.9}],
        "chars": 3, "chars_per_minute": 18.0,
        "hook": "第一句", "cta": "最后一句话", "text": "第一句……最后一句话",
    }
    return intake.build_profile(
        source=fixture_source(), probe={"duration": 10.0, "width": 1080, "height": 1920,
                                        "fps": 30.0, "video_codec": "h264",
                                        "audio_codec": "aac"},
        pacing=fixture_pacing(), teardown=fixture_teardown(), rows=fixture_rows(),
        segments=[{"index": 1, "start": 0.0, "end": 5.0, "duration": 5.0,
                   "shots": ["s01", "s02"], "oversize": False}],
        contact_sheet="contact-sheet.jpg", transcript=transcript,
        breakdown=fixture_breakdown(), unchecked=[], generated_at="2026-10-20T11:00:00+08:00")


class ProfileTests(unittest.TestCase):
    def test_style_hints_map_measurements_to_config(self):
        profile = fixture_profile()
        hints = profile["style"]["config_hints"]
        self.assertEqual(hints["captions.palette.accent"], "#F0C030")
        self.assertEqual(hints["captions.palette.contrast"], "#E05028")
        self.assertEqual(hints["card.start"], 2.0)
        self.assertEqual(hints["pip.enabled"], True)
        self.assertNotIn("captions.margin_v", hints)
        self.assertIn("margin_v", profile["style"]["caption_band_note"])

    def test_full_frame_card_is_not_suggested_as_a_card(self):
        profile = intake.build_profile(
            source=fixture_source(), probe={"duration": 10.0, "width": 1080,
                                            "height": 1920, "fps": 30},
            pacing=fixture_pacing(), teardown=fixture_teardown(card_area=0.9),
            rows=fixture_rows(), segments=[], contact_sheet=None, transcript=None,
            breakdown={"status": "unchecked", "overview": None, "shots": {},
                       "warnings": [], "usage": {}},
            unchecked=[], generated_at="2026-10-20T11:00:00+08:00")
        self.assertIsNone(profile["style"]["card"])
        self.assertNotIn("card.enabled", profile["style"]["config_hints"])
        self.assertTrue(profile["style"]["card_rejected"])

    def test_profile_merges_vision_and_marks_missing_shots(self):
        profile = fixture_profile()
        self.assertEqual(profile["shots"][0]["analysis_status"], "ok")
        self.assertEqual(profile["shots"][0]["analysis"]["shot_size"], "近景")
        self.assertEqual(profile["recommendations"]["copy"]["hook"], "第一句")
        self.assertEqual(profile["pacing"]["used_shot_count"], 2)
        self.assertEqual(profile["pacing"]["used_cuts_per_minute"], 6.0)

    def test_unchecked_shot_stays_visible(self):
        breakdown = fixture_breakdown()
        breakdown["shots"]["s02"] = {"unchecked": True, "reason": "接口超时"}
        profile = intake.build_profile(
            source=fixture_source(), probe={"duration": 10.0, "width": 1080,
                                            "height": 1920, "fps": 30},
            pacing=fixture_pacing(), teardown=fixture_teardown(), rows=fixture_rows(),
            segments=[], contact_sheet=None, transcript=None, breakdown=breakdown,
            unchecked=[{"item": "视觉拆解批次", "reason": "接口超时"}],
            generated_at="2026-10-20T11:00:00+08:00")
        self.assertEqual(profile["shots"][1]["analysis_status"], "unchecked")
        self.assertEqual(profile["shots"][1]["analysis_reason"], "接口超时")
        self.assertEqual(profile["unchecked"][0]["item"], "视觉拆解批次")

    def test_report_has_the_sections_a_reviewer_needs(self):
        profile = fixture_profile()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "contact-sheet.jpg").write_bytes(b"x")
            report = intake._report(profile, out)
        for heading in ("# 参考片拆解报告", "## 技术参数", "## 节奏",
                        "## 视觉风格", "## 镜头表", "## 口播与结构",
                        "## 怎么借鉴", "## 未检查", "## 产物"):
            self.assertIn(heading, report)
        self.assertIn("![contact sheet](contact-sheet.jpg)", report)
        self.assertIn("近景", report)
        self.assertIn("2.00–5.00s", report)

    def test_transcript_join_does_not_insert_spaces_between_chinese(self):
        text = intake._transcript_from_words(
            [{"text": "先"}, {"text": "抛"}, {"text": "问题"}, {"text": "，"},
             {"text": "再"}, {"text": "解释"}])
        self.assertEqual(text, "先抛问题，再解释")


class SceneCutParserTests(unittest.TestCase):
    def test_score_pairs_with_the_preceding_pts(self):
        import analyze_reference
        stderr = ("pts_time:1.5\nlavfi.scene_score=0.42\n"
                  "pts_time:3.0\nlavfi.scene_score=0.8\n")
        with mock.patch.object(analyze_reference, "run",
                               return_value=SimpleNamespace(stderr=stderr, returncode=0)):
            cuts = analyze_reference.scene_cuts(Path("ref.mp4"), 0.15)
        self.assertEqual(cuts, [{"t": 1.5, "score": 0.42},
                                {"t": 3.0, "score": 0.8}])


class CardGuardTests(unittest.TestCase):
    def test_full_frame_card_is_not_written_into_config(self):
        from new_project import build_config
        cfg = build_config("demo", "9:16", "/tmp/in.mp4", [], {
            "card": {"start": 0.0, "end": 2.0, "bbox_norm": [0, 0, 1, 1],
                     "fill_hex": "#222222", "area": 0.99},
        }, mode="talking-head")
        self.assertFalse(cfg["card"]["enabled"])


@unittest.skipUnless(shutil.which("ffmpeg"), "需要 ffmpeg")
class EndToEndTests(unittest.TestCase):
    def test_local_video_without_llm_or_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "ref.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=0xE4572E:s=540x960:d=1.5:r=30",
                "-f", "lavfi", "-i", "color=c=0x17BEBB:s=540x960:d=1.5:r=30",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
                "-pix_fmt", "yuv420p", str(video),
            ], check=True, capture_output=True)
            out = root / "out"
            profile = intake.run(video, out, no_asr=True, no_llm=True, force=True,
                                 pick_font=True, font_library="local",
                                 log=lambda *_: None)
            self.assertEqual(profile["schema"], intake.SCHEMA)
            self.assertTrue((out / intake.PROFILE_NAME).is_file())
            self.assertTrue((out / intake.REPORT_NAME).is_file())
            self.assertTrue((out / "shots.json").is_file())
            self.assertGreaterEqual(profile["coverage"]["shots"], 1)
            self.assertTrue(profile["unchecked"])
            items = {entry["item"] for entry in profile["unchecked"]}
            self.assertIn("口播转写", items)
            self.assertIn("镜头语义 / 全片结构", items)
            self.assertTrue((out / "font-selection.json").is_file())
            self.assertEqual(profile["font_selection"]["mode"], "fallback")


if __name__ == "__main__":
    unittest.main()
