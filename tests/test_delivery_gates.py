import json
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults
import verify


class DeliveryGateTests(unittest.TestCase):
    def config(self):
        return apply_defaults({"name": "sample", "duration": 1.0,
                               "audio": {"speech_mode": "none"}})

    def test_verify_rejects_old_named_video_without_render_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            output = project / "output"
            output.mkdir()
            (output / "final-720x1280.mp4").write_bytes(b"old output")
            report = verify.run_checks(self.config(), project)
            check = next(c for c in report["checks"] if c["name"] == "output-exists")
            self.assertEqual(check["status"], "fail")
            self.assertIn("本轮", check["detail"])

    def test_verify_rejects_receipt_after_configuration_changes(self):
        from workflow.delivery import record_render

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            output = project / "output"
            output.mkdir()
            movie = output / "final-720x1280.mp4"
            movie.write_bytes(b"old output")
            cfg = self.config()
            record_render(project, movie, cfg)
            cfg["duration"] = 3.0
            report = verify.run_checks(cfg, project)
            check = next(c for c in report["checks"] if c["name"] == "output-exists")
            self.assertEqual(check["status"], "fail")
            self.assertIn("本轮", check["detail"])

    def test_receipt_rejects_rewritten_media_inputs(self):
        from workflow.delivery import current_output, record_render

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "output").mkdir()
            (project / "input").mkdir()
            (project / "work").mkdir()
            movie = project / "output/final-720x1280.mp4"
            movie.write_bytes(b"rendered")
            source = project / "input/clean-cut.mp4"
            body = project / "work/body-anim-silent.mp4"
            source.write_bytes(b"cut v1")
            body.write_bytes(b"body v1")
            cfg = self.config()
            cfg["input"]["video"] = "clean-cut.mp4"
            record_render(project, movie, cfg)
            self.assertEqual(current_output(project, cfg)[0], movie.resolve())
            source.write_bytes(b"cut v2")
            self.assertIsNone(current_output(project, cfg)[0])
            source.write_bytes(b"cut v1")
            body.write_bytes(b"body v2")
            self.assertIsNone(current_output(project, cfg)[0])

    def test_receipt_rejects_a_rewritten_style_plan(self):
        """改了逐条样式/插图计划但没重渲，旧凭据不许继续匹配。"""
        from workflow.delivery import current_output, record_render

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "output").mkdir()
            (project / "input").mkdir()
            (project / "work").mkdir()
            movie = project / "output/final-720x1280.mp4"
            movie.write_bytes(b"rendered")
            plan = project / "work/style-plan.json"
            plan.write_text('{"version": 1, "cues": []}')
            cfg = self.config()
            record_render(project, movie, cfg)
            self.assertEqual(current_output(project, cfg)[0], movie.resolve())
            plan.write_text('{"version": 1, "cues": [{"style": "big"}]}')
            self.assertIsNone(current_output(project, cfg)[0])

    def test_receipt_rejects_redrawn_insert_assets(self):
        from workflow.delivery import current_output, record_render

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "output").mkdir()
            (project / "assets").mkdir()
            movie = project / "output/final-720x1280.mp4"
            movie.write_bytes(b"rendered")
            art = project / "assets/insert-1.png"
            art.write_bytes(b"inset v1")
            cfg = self.config()
            record_render(project, movie, cfg)
            self.assertEqual(current_output(project, cfg)[0], movie.resolve())
            art.write_bytes(b"inset v2")
            self.assertIsNone(current_output(project, cfg)[0])

    def test_every_check_can_be_reported_when_there_is_no_output(self):
        """没成片时每一项都要以 unchecked 出现 —— 名字漏登记就等于「缺席当通过」。

        这条守的是 verify.py 里那张 `out is None` 名单：新加检查项忘了登记，
        报告里就少一项，而少的那项会被读成「通过」。
        """
        import re

        source = (ROOT / "scripts" / "verify.py").read_text(encoding="utf-8")
        block = re.search(r"if out is None:.*?return _write", source, re.S).group(0)
        registered = set(re.findall(r'"([a-z][a-z0-9-]+)"', block))
        # 顶层直接 add() 的项本来就走正常路径，永远会被报出来；
        # 只有**由辅助函数产出的**项，才可能在没成片时整项消失。
        direct = set(re.findall(r'add\(\s*"([a-z][a-z0-9-]+)"', source))
        helper_only = set()
        for helper in ("_slot_check", "_insert_checks"):
            body = re.search(rf"def {helper}\(.*?\n(?=def )", source, re.S).group(0)
            # 只认 (名字, …) 这种元组首位；带逗号才匹配，免得把 get("enabled") 也算进来
            helper_only |= set(re.findall(r'\(\s*"([a-z][a-z0-9-]+)"\s*,', body))
        missing = sorted(helper_only - registered - direct)
        self.assertEqual(missing, [], f"这些检查项没登记进「没成片」名单：{missing}")

    def test_old_draft_does_not_match_a_new_render(self):
        from workflow.delivery import (draft_matches_receipt, receipt_digest,
                                       record_render)

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            movie = project / "output/final-720x1280.mp4"
            movie.parent.mkdir()
            movie.write_bytes(b"first render")
            draft = project / "draft-store/sample"
            draft.mkdir(parents=True)
            (draft / "draft_info.json").write_text("{}")
            (draft / "draft_content.json").write_text("{}")
            cfg = self.config()
            record_render(project, movie, cfg)
            report = {"draft": str(draft), "render_receipt_sha256": receipt_digest(project)}
            self.assertTrue(draft_matches_receipt(project, draft, report))
            movie.write_bytes(b"second render")
            record_render(project, movie, cfg)
            self.assertFalse(draft_matches_receipt(project, draft, report))

    def narration_project(self, project: Path, *, second_audible: bool,
                          second_caption: bool) -> dict:
        cfg = apply_defaults({"name": "sample", "duration": 1.0,
                              "audio": {"speech_mode": "narration",
                                        "voice_cues": "voice-cues.json",
                                        "voice_subtitle": "voice-captions.srt"}})
        work, inputs = project / "work", project / "input"
        work.mkdir()
        inputs.mkdir()
        (work / "voice-cues.json").write_text(json.dumps({"lines": [
            {"start": 0.10, "end": 0.35, "text": "第一句"},
            {"start": 0.55, "end": 0.80, "text": "第二句"}]}), encoding="utf-8")
        srt = ("1\n00:00:00,100 --> 00:00:00,350\n第一句\n\n" +
               ("2\n00:00:00,550 --> 00:00:00,800\n第二句\n" if second_caption else ""))
        (inputs / "voice-captions.srt").write_text(srt, encoding="utf-8")
        samples = array("h", (800 if .10 <= i / 48000 < .35 or
                             second_audible and .55 <= i / 48000 < .80 else 0
                             for i in range(48000) for _ in range(2)))
        with wave.open(str(work / "voice.wav"), "wb") as sound:
            sound.setnchannels(2)
            sound.setsampwidth(2)
            sound.setframerate(48000)
            sound.writeframes(samples.tobytes())
        return cfg

    def test_narration_rejects_missing_second_spoken_window(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg = self.narration_project(project, second_audible=False,
                                         second_caption=True)
            ready, detail = speech_readiness(cfg, project)
            self.assertFalse(ready)
            self.assertIn("第二句", detail)

    def test_narration_rejects_missing_spoken_subtitle(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg = self.narration_project(project, second_audible=True,
                                         second_caption=False)
            ready, detail = speech_readiness(cfg, project)
            self.assertFalse(ready)
            self.assertIn("第二句", detail)

    def test_narration_rejects_shifted_shot_anchor(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg = self.narration_project(project, second_audible=True,
                                         second_caption=True)
            shots = [{"source": "/tmp/a.mov", "in": 1, "duration": 0.5},
                     {"source": "/tmp/b.mov", "in": 2, "duration": 0.5}]
            (project / "work/edit-plan.json").write_text(json.dumps({"shots": shots}))
            cues_path = project / "work/voice-cues.json"
            cues = json.loads(cues_path.read_text())
            for index, line in enumerate(cues["lines"]):
                line.update({"shot_index": index + 1, "shot_ref": shots[index].copy()})
            cues_path.write_text(json.dumps(cues))
            self.assertTrue(speech_readiness(cfg, project)[0])
            shots[1]["in"] = 3
            (project / "work/edit-plan.json").write_text(json.dumps({"shots": shots}))
            ready, detail = speech_readiness(cfg, project)
            self.assertFalse(ready)
            self.assertIn("第二句", detail)

    def test_narration_rejects_overlapping_spoken_subtitles(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg = self.narration_project(project, second_audible=True,
                                         second_caption=True)
            cues_path = project / "work/voice-cues.json"
            cues = json.loads(cues_path.read_text())
            cues["lines"][0]["end"] = 0.65
            cues_path.write_text(json.dumps(cues))
            (project / "input/voice-captions.srt").write_text(
                "1\n00:00:00,100 --> 00:00:00,650\n第一句\n\n"
                "2\n00:00:00,550 --> 00:00:00,800\n第二句\n")
            ready, detail = speech_readiness(cfg, project)
            self.assertFalse(ready)
            self.assertIn("旁白字幕预检", detail)

    def test_narration_cues_stay_one_unit_each(self):
        """`story_audio.main` must persist one cue per line, one subtitle per line."""
        from unittest.mock import patch
        from workflow.speech_policy import speech_readiness
        import story_audio

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            work, inputs = project / "work", project / "input"
            work.mkdir()
            inputs.mkdir()
            cfg = apply_defaults({"name": "sample", "duration": 4.0, "mode": "vlog",
                                  "audio": {"speech_mode": "narration",
                                            "voice_cues": "voice-cues.json",
                                            "voice_subtitle": "voice-captions.srt"}})
            (project / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            plan = {"version": 1, "mode": "vlog", "shots": [
                {"source": "/tmp/one.mp4", "in": 0, "duration": 2},
                {"source": "/tmp/two.mp4", "in": 0, "duration": 2}]}
            (work / "edit-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (work / "storyboard.json").write_text(json.dumps({
                "status": "proposal", "review_required": True,
                "order": ["shot_1", "shot_2"], "duration": 4,
                "shot_refs": {"shot_1": {"source": "/tmp/one.mp4", "in": 0, "duration": 2},
                              "shot_2": {"source": "/tmp/two.mp4", "in": 0, "duration": 2}},
                "music_mood": "none", "narration": [
                    {"shot_id": "shot_1", "text": "第一句", "evidence": ["shot_1"], "start": 0.0},
                    {"shot_id": "shot_2", "text": "第二句", "evidence": ["shot_2"], "start": 2.0}]}
            ), encoding="utf-8")

            def synth(text: str, target: Path) -> Path:
                frames = int(round(0.15 * 48000))
                with wave.open(str(target), "wb") as sound:
                    sound.setnchannels(2)
                    sound.setsampwidth(2)
                    sound.setframerate(48000)
                    sound.writeframes(array("h", [800, 800] * frames).tobytes())
                return target

            argv = ["story_audio.py", str(project), "--approve-story"]
            with patch.object(sys, "argv", argv), patch.object(story_audio, "_say", synth):
                story_audio.main()

            self.assertTrue((work / "voice-cues.json").is_file(),
                            "main 没有落盘逐句证据，逐句门禁无从查起")
            body = (inputs / "voice-captions.srt").read_text(encoding="utf-8")
            # One cue per narration line: the ASR splitter merged them into one.
            self.assertEqual(body.count("-->"), 2)
            self.assertIn("第一句", body)

            # The evidence main just wrote must satisfy the gate that reads it.
            ready, detail = speech_readiness(cfg, project)
            self.assertTrue(ready, detail)

    def test_generated_cue_file_passes_its_own_readiness_check(self):
        """The writer and the checker must agree, or the gate blocks real deliveries."""
        from auto_captions import write_cues
        from workflow.speech_policy import speech_readiness
        import story_audio

        def synth(text: str, target: Path) -> Path:
            frames = int(round(0.15 * 48000))
            with wave.open(str(target), "wb") as sound:
                sound.setnchannels(2)
                sound.setsampwidth(2)
                sound.setframerate(48000)
                sound.writeframes(array("h", [800, 800] * frames).tobytes())
            return target

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            work, inputs = project / "work", project / "input"
            work.mkdir()
            inputs.mkdir()
            cfg = apply_defaults({"name": "sample", "duration": 1.10,
                                  "audio": {"speech_mode": "narration",
                                            "voice_cues": "voice-cues.json",
                                            "voice_subtitle": "voice-captions.srt"}})
            windows = [{"start": 0.10, "end": 0.40, "text": "第一句"},
                       {"start": 0.60, "end": 0.90, "text": "第二句"}]
            cues = story_audio.build_voice(windows, 1.10, work / "voice.wav", synth=synth)
            # Mirror exactly what `story_audio.main` persists, then read it back.
            story_audio._atomic_json(work / "voice-cues.json", {
                "version": 1, "duration": 1.10, "subtitle": "voice-captions.srt",
                "lines": [{"start": c["start"], "end": c["end"], "text": c["text"]}
                          for c in cues]})
            write_cues(cues, inputs / "voice-captions.srt")

            ready, detail = speech_readiness(cfg, project)
            self.assertTrue(ready, detail)

            # Silence only the second spoken line: its caption still exists, so
            # only the per-line audio check can catch this.
            second = cues[1]
            samples = bytearray((work / "voice.wav").read_bytes())
            start = 44 + int(round(second["start"] * 48000)) * 4
            end = 44 + int(round(second["end"] * 48000)) * 4
            samples[start:end] = bytes(end - start)
            (work / "voice.wav").write_bytes(bytes(samples))
            ready, detail = speech_readiness(cfg, project)
            self.assertFalse(ready)
            self.assertIn("第二句", detail)


if __name__ == "__main__":
    unittest.main()
