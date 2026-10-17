import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from array import array
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults
import render
import run_all
import verify


def voice_file(path: Path, duration: float, active: bool) -> None:
    frames = round(duration * 48000)
    sample = 800 if active else 0
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(array("h", [sample, sample] * frames).tobytes())


class SpeechPolicyTests(unittest.TestCase):
    def config(self, mode="narration"):
        return apply_defaults({"name": "demo", "duration": 1.0,
                               "audio": {"speech_mode": mode}})

    def source_fixture(self, project: Path) -> tuple[dict, Path]:
        video = project / "input" / "clip.mp4"
        video.parent.mkdir(exist_ok=True)
        cfg = self.config("source")
        cfg["input"]["video"] = "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=s=64x64:r=10:d=1", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1", "-c:v", "libx264",
                        "-c:a", "aac", str(video)], check=True)
        return cfg, video

    def evidence(self, video: Path, *, status: str = "ok", confidence: float = 0.9,
                 language: str = "zh") -> dict:
        from workflow.source_speech import source_signature
        from _common import probe_media
        return {"source": str(video.resolve()),
                "signature": source_signature(video, probe_media(video)["duration"]),
                "duration": 1.0, "status": status, "language": language,
                "language_probability": 0.98,
                "words": [{"text": char, "start": at, "end": at + 0.14,
                           "confidence": confidence}
                          for char, at in zip("你好呀", (.1, .35, .6))]
                if status == "ok" else []}

    def test_default_mode_follows_new_edit_plan(self):
        self.assertEqual(apply_defaults({"mode": "vlog"})["audio"]["speech_mode"],
                         "narration")
        self.assertEqual(apply_defaults({"mode": "talking-head"})["audio"]["speech_mode"],
                         "source")
        self.assertIsNone(apply_defaults({})["audio"]["speech_mode"])

    def test_new_vlog_project_records_narration_requirement(self):
        from new_project import build_config

        cfg = build_config("demo", "9:16", None, ["clip.mp4"], None, mode="vlog")
        self.assertEqual(cfg["audio"]["speech_mode"], "narration")
        self.assertEqual(cfg["mode"], "vlog")

    def test_new_vlog_project_instructs_voice_before_delivery(self):
        from new_project import main

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with patch.object(sys, "argv", ["new_project.py", tmp,
                                            "--clips", "shot.mp4", "--mode", "vlog"]):
                with redirect_stdout(output):
                    main()
            self.assertIn("story_audio.py", output.getvalue())
            self.assertLess(output.getvalue().index("story_audio.py"),
                            output.getvalue().index("run_all.py"))

    def test_narration_requires_audible_voice_with_matching_duration(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            work = project / "work"
            work.mkdir()
            ready, message = speech_readiness(self.config(), project)
            self.assertFalse(ready)
            self.assertIn("voice.wav", message)
            voice_file(work / "voice.wav", 1.0, False)
            self.assertFalse(speech_readiness(self.config(), project)[0])
            voice_file(work / "voice.wav", 2.0, True)
            self.assertFalse(speech_readiness(self.config(), project)[0])
            voice_file(work / "voice.wav", 1.0, True)
            self.assertTrue(speech_readiness(self.config(), project)[0])

    def test_unknown_or_invalid_policy_fails_explicitly(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            for mode in (None, "music"):
                with self.subTest(mode=mode):
                    self.assertFalse(speech_readiness(self.config(mode), Path(tmp))[0])
            self.assertTrue(speech_readiness(self.config("none"), Path(tmp))[0])

    def test_source_mode_rejects_music_only_audio_without_asr_evidence(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, _video = self.source_fixture(project)
            self.assertFalse(speech_readiness(cfg, project)[0])
            report = verify.run_checks(cfg, project)
            speech = next(c for c in report["checks"] if c["name"] == "speech-presence")
            self.assertEqual(speech["status"], "fail")
            self.assertIn("转写", speech["detail"])

    def test_source_evidence_rejects_no_speech_and_stale_or_low_confidence(self):
        from workflow.speech_policy import speech_readiness

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, video = self.source_fixture(project)
            work = project / "work"
            work.mkdir()
            target = work / "source-speech.json"
            for record in (self.evidence(video, status="no_speech"),
                           self.evidence(video, confidence=0.1),
                           self.evidence(video, language="en")):
                target.write_text(json.dumps(record), encoding="utf-8")
                self.assertFalse(speech_readiness(cfg, project)[0])
            target.write_text(json.dumps(self.evidence(video)), encoding="utf-8")
            ready, detail = speech_readiness(cfg, project)
            self.assertTrue(ready, detail)
            self.assertIn("覆盖", detail)
            report = verify.run_checks(cfg, project)
            self.assertEqual(next(c for c in report["checks"]
                                  if c["name"] == "speech-presence")["status"], "pass")
            stat = video.stat()
            os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            self.assertFalse(speech_readiness(cfg, project)[0])

    def test_source_evidence_cached_and_asr_failure_preserves_previous_result(self):
        from workflow.source_speech import prepare_source_evidence

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, video = self.source_fixture(project)
            calls = []

            def transcriber(src, output, model_name):
                calls.append((src, model_name))
                result = self.evidence(video)
                output.write_text(json.dumps(result), encoding="utf-8")
                return result

            first = prepare_source_evidence(cfg, project, transcriber=transcriber)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["status"], "ok")
            self.assertEqual(prepare_source_evidence(
                cfg, project, transcriber=transcriber), first)
            self.assertEqual(len(calls), 1)
            stat = video.stat()
            os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            before = (project / "work" / "source-speech.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "ASR unavailable"):
                prepare_source_evidence(
                    cfg, project, transcriber=lambda *_: (
                        _ for _ in ()).throw(RuntimeError("ASR unavailable")))
            self.assertEqual((project / "work" / "source-speech.json").read_bytes(), before)

    def test_pipeline_runs_source_asr_before_render_and_rejects_no_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, video = self.source_fixture(project)
            (project / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

            def transcriber(_source, output, _model):
                result = self.evidence(video, status="no_speech")
                output.write_text(json.dumps(result), encoding="utf-8")
                return result

            with patch("transcribe_audio.transcribe", side_effect=transcriber):
                with patch.object(sys, "argv", ["run_all.py", str(project),
                                                "--only", "render"]):
                    with self.assertRaisesRegex(SystemExit, "no_speech|未检测到"):
                        run_all.main()
            self.assertEqual(json.loads((project / "work" / "source-speech.json").read_text())[
                "status"], "no_speech")
            self.assertFalse((project / "output").exists())

    def test_source_speech_cli_accepts_matching_existing_asr_without_rendering(self):
        from prepare_source_speech import main

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, video = self.source_fixture(project)
            (project / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            transcript = project / "verified-transcript.json"
            result = self.evidence(video)
            result.pop("signature")
            transcript.write_text(json.dumps(result), encoding="utf-8")
            with patch.object(sys, "argv", ["prepare_source_speech.py", str(project),
                                            "--transcript", str(transcript)]):
                with redirect_stdout(io.StringIO()):
                    main()
            cache = json.loads((project / "work" / "source-speech.json").read_text())
            self.assertEqual(cache["source"], str(video.resolve()))
            self.assertIn("signature", cache)
            self.assertFalse((project / "output").exists())

    def test_source_speech_import_rejects_mismatched_source_or_duration_without_overwriting(self):
        from workflow.source_speech import import_source_evidence

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, video = self.source_fixture(project)
            work = project / "work"
            work.mkdir()
            cache = work / "source-speech.json"
            cache.write_text('{"previous": true}\n', encoding="utf-8")
            transcript = project / "transcript.json"
            for change in ({"source": str(project / "other.mp4")},
                           {"duration": 5.0}):
                record = {**self.evidence(video), **change}
                record.pop("signature")
                transcript.write_text(json.dumps(record), encoding="utf-8")
                with self.subTest(change=change):
                    with self.assertRaisesRegex(ValueError, "素材|时长"):
                        import_source_evidence(cfg, project, transcript)
                    self.assertEqual(cache.read_text(encoding="utf-8"),
                                     '{"previous": true}\n')

    def test_render_is_guarded_before_frame_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "voice.wav"):
                render.build(self.config(), Path(tmp), 1.0)

    def test_pipeline_rejects_missing_voice_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "config.json").write_text(
                json.dumps(self.config()), encoding="utf-8")
            with patch.object(sys, "argv", ["run_all.py", str(project),
                                            "--only", "render"]):
                with self.assertRaisesRegex(SystemExit, "voice.wav"):
                    run_all.main()
            self.assertFalse((project / "work" / "pipeline.json").exists())

    def test_verify_reports_missing_voice_even_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = verify.run_checks(self.config(), Path(tmp))
            speech = next(c for c in report["checks"]
                          if c["name"] == "speech-presence")
            self.assertEqual(speech["status"], "fail")
            self.assertIn("voice.wav", speech["detail"])

    def test_verify_only_still_reports_failed_speech_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "config.json").write_text(json.dumps(self.config()), encoding="utf-8")
            with patch.object(sys, "argv", ["run_all.py", str(project),
                                            "--only", "verify"]):
                with self.assertRaisesRegex(SystemExit, "质检未通过"):
                    run_all.main()
            report = json.loads((project / "work" / "qc-report.json").read_text())
            self.assertEqual(next(c for c in report["checks"]
                                  if c["name"] == "speech-presence")["status"], "fail")


if __name__ == "__main__":
    unittest.main()
