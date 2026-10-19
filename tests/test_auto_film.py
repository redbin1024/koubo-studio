import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import apply_defaults, ensure_dirs  # noqa: E402
from auto_film import (  # noqa: E402
    _fix_overlaps, _merge_scene_candidates, _prepare_voice, _repair,
    _strip_line_punct, _wrap_highlights,
)
from workflow.auto_director import DirectorResult  # noqa: E402
from workflow.auto_voice import AutoVoiceError  # noqa: E402
from unittest import mock  # noqa: E402


class AutoFilmHelperTests(unittest.TestCase):
    def test_strip_line_punct_keeps_markup(self):
        self.assertEqual(_strip_line_punct("大家好，[[重点]]。((反差))！"),
                         "大家好[[重点]]((反差))")

    def test_wrap_highlights_skips_existing_markup(self):
        text, budget = _wrap_highlights("今天分享方法。重点在这里", ["方法", "重点"], 2)
        self.assertEqual(text, "今天分享[[方法]]。[[重点]]在这里")
        self.assertEqual(budget, 0)
        wrapped, _ = _wrap_highlights("已经[[方法]]了", ["方法"], 1)
        self.assertEqual(wrapped, "已经[[方法]]了")

    def test_merge_scene_candidates_only_merges_contiguous_same_source(self):
        shots = [
            {"id": "shot_1", "source": "/tmp/a.mp4", "in": 0.0, "duration": 1.0,
             "transcript": "一"},
            {"id": "shot_2", "source": "/tmp/a.mp4", "in": 1.0, "duration": 1.0,
             "transcript": "二"},
            {"id": "shot_3", "source": "/tmp/b.mp4", "in": 0.0, "duration": 1.0,
             "transcript": "三"},
        ]
        merged = _merge_scene_candidates(shots, limit=2)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["duration"], 2.0)
        self.assertEqual(merged[0]["transcript"], "一二")
        self.assertEqual(merged[1]["id"], "shot_3")

    def test_fix_overlaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = Path(tmp) / "captions.srt"
            srt.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n第一句\n\n"
                "2\n00:00:01,500 --> 00:00:03,000\n第二句\n", encoding="utf-8")
            self.assertTrue(_fix_overlaps(srt, 30, 5.0))
            text = srt.read_text(encoding="utf-8")
            self.assertIn("第二句", text)
            self.assertNotIn("00:00:01,500", text)

    def test_repair_long_silence_and_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            ensure_dirs(project)
            cfg = apply_defaults({"name": "repair", "duration": 3.0,
                                  "audio": {"speech_mode": "none", "bgm": {"enabled": False}}})
            cfg["card"]["enabled"] = True
            qc = {"checks": [
                {"name": "long-silence", "status": "fail", "detail": ""},
                {"name": "card-rendered", "status": "fail", "detail": ""},
            ]}
            changed, notes = _repair(cfg, project, qc, 3.0)
            self.assertTrue(changed)
            self.assertTrue(cfg["audio"]["bgm"]["enabled"])
            self.assertFalse(cfg["card"]["enabled"])
            self.assertEqual(len(notes), 2)

    def test_burned_in_captions_do_not_generate_duplicate_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            ensure_dirs(project)
            cfg = apply_defaults({"name": "burned", "duration": 3.0,
                                  "audio": {"speech_mode": "source"},
                                  "captions": {"mode": "burned-in"}})
            plan = {"version": 1, "mode": "talking-head",
                    "shots": [{"source": "/tmp/a.mp4", "in": 0, "duration": 3}]}
            result = DirectorResult(
                shots=[{"id": "shot_1", "source": "/tmp/a.mp4", "in": 0,
                        "duration": 3, "transcript": "现场"}],
                mode="talking-head")
            clean = project / "input" / "clean-cut.mp4"
            clean.write_bytes(b"x")
            with mock.patch("auto_film._transcribe_cut",
                            return_value={"words": [], "duration": 3.0}), \
                    mock.patch("auto_film._source_evidence",
                               return_value=({"signature": "s"}, True, "3 秒语音")):
                mode, notes, voice = _prepare_voice(
                    project, cfg, "talking-head", result, plan, clean, 3.0,
                    "small", False)
            self.assertEqual(mode, "source")
            self.assertIsNone(voice)
            self.assertEqual((project / "input" / "captions.srt").read_text(), "")
            self.assertTrue(any("不重复生成" in note for note in notes))

    def test_prepare_voice_narration_and_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            ensure_dirs(project)
            cfg = apply_defaults({"name": "voice", "duration": 3.0,
                                  "audio": {"speech_mode": "none"}})
            plan = {"version": 1, "mode": "vlog",
                    "shots": [{"source": "/tmp/a.mp4", "in": 0, "duration": 3}]}
            result = DirectorResult(
                shots=[{"id": "shot_1", "source": "/tmp/a.mp4", "in": 0,
                        "duration": 3, "transcript": "现场"}],
                mode="vlog", narration=[{"shot_id": "shot_1", "text": "旁白"}])
            clean = project / "input" / "clean-cut.mp4"
            clean.write_bytes(b"x")
            with mock.patch("auto_film._transcribe_cut", return_value=None), \
                    mock.patch("auto_film._narration_windows",
                               return_value=[{"start": 0.2, "end": 2.5, "text": "旁白"}]), \
                    mock.patch("auto_film.build_narration",
                               return_value={"lines": [{"text": "旁白"}],
                                             "skipped": [], "voice": "v"}):
                mode, notes, voice = _prepare_voice(
                    project, cfg, "vlog", result, plan, clean, 3.0, "small", False)
            self.assertEqual(mode, "narration")
            self.assertEqual(cfg["audio"]["speech_mode"], "narration")
            self.assertEqual(cfg["audio"]["voice_cues"], "voice-cues.json")
            self.assertIsNotNone(voice)

            cfg2 = apply_defaults({"name": "voice2", "duration": 3.0,
                                   "audio": {"speech_mode": "none"}})
            with mock.patch("auto_film._transcribe_cut", return_value=None), \
                    mock.patch("auto_film._narration_windows",
                               return_value=[{"start": 0.2, "end": 2.5, "text": "旁白"}]), \
                    mock.patch("auto_film.build_narration",
                               side_effect=AutoVoiceError("429")):
                mode2, notes2, voice2 = _prepare_voice(
                    project, cfg2, "vlog", result, plan, clean, 3.0, "small", False)
            self.assertEqual(mode2, "none")
            self.assertIsNone(voice2)
            self.assertNotIn("voice_cues", cfg2["audio"])


if __name__ == "__main__":
    unittest.main()
