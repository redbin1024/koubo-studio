import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StoryAudioTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("story_audio"))
        import story_audio
        return story_audio

    def plan(self):
        return {"version": 1, "mode": "vlog", "shots": [
            {"source": "/tmp/one.mp4", "in": 0, "duration": 2},
            {"source": "/tmp/two.mp4", "in": 0, "duration": 2},
        ]}

    def story(self):
        return {"status": "proposal", "review_required": True,
                "order": ["shot_1", "shot_2"], "duration": 4,
                "shot_refs": {"shot_1": {"source": "/tmp/one.mp4", "in": 0, "duration": 2},
                              "shot_2": {"source": "/tmp/two.mp4", "in": 0, "duration": 2}},
                "music_mood": "warm", "narration": [
                    {"shot_id": "shot_2", "text": "蓝色背景",
                     "evidence": ["shot_2"], "start": 2}]}

    def test_rejects_misaligned_story(self):
        story_audio = self.module()
        self.assertEqual(story_audio.validate_audio_story(
            self.story(), self.plan())["windows"],
            [{"start": 2.0, "end": 4.0, "text": "蓝色背景"}])
        for edit in ({"order": ["shot_2", "shot_1"]},
                     {"review_required": False},
                     {"narration": [{**self.story()["narration"][0], "start": 1}]}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                story_audio.validate_audio_story({**self.story(), **edit}, self.plan())
        with self.assertRaises(ValueError):
            story_audio.validate_audio_story(
                self.story(), {**self.plan(), "mode": "talking-head"})
        reordered = {**self.story(), "order": ["shot_2", "shot_1"],
                     "narration": [{"shot_id": "shot_2", "text": "先看户外",
                                    "evidence": ["shot_2"], "start": 0}]}
        reordered_plan = {**self.plan(), "shots": list(reversed(self.plan()["shots"]))}
        self.assertEqual(story_audio.validate_audio_story(
            reordered, reordered_plan)["windows"][0]["start"], 0.0)
        with self.assertRaises(ValueError):
            story_audio.validate_audio_story(reordered, self.plan())

    def test_builds_voice_and_bgm_with_correct_duration(self):
        story_audio = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            def synth(_text, target):
                with wave.open(str(target), "wb") as out:
                    out.setnchannels(2)
                    out.setsampwidth(2)
                    out.setframerate(48000)
                    out.writeframes(b"\x10\x01\x10\x01" * 4800)
                return target

            voice, bgm = root / "voice.wav", root / "bgm.wav"
            cues = story_audio.build_voice(
                [{"start": 0, "end": 1, "text": "你好"}], 1.5, voice, synth=synth)
            self.assertEqual(cues, [{"start": 0.0, "end": 0.1, "text": "你好"}])
            story_audio.build_bgm(1.5, "warm", bgm)
            for path in (voice, bgm):
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual(wav.getframerate(), 48000)
                    self.assertEqual(wav.getnframes(), 72000)
                    self.assertTrue(any(wav.readframes(72000)))
            with self.assertRaises(ValueError):
                story_audio.build_voice(
                    [{"start": 0, "end": 0.12, "text": "你好"}], 1.5,
                    root / "bad.wav", synth=synth)
            self.assertFalse((root / "bad.wav").exists())

    def test_cli_requires_approval_and_preserves_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            fake_bin = project / "fake-bin"
            fake_bin.mkdir()
            fake_say = fake_bin / "say"
            fake_say.write_text(
                "#!/bin/sh\n"
                'out=""\n'
                'while [ $# -gt 0 ]; do\n'
                '  case "$1" in\n'
                '    -o) out="$2"; shift 2 ;;\n'
                '    *) shift ;;\n'
                '  esac\n'
                'done\n'
                '[ -n "$out" ] || exit 2\n'
                'exec ffmpeg -v error -y -f lavfi -i "sine=frequency=440:duration=0.10" '
                '-ac 2 -ar 48000 -c:a pcm_s16le "$out"\n',
                encoding="utf-8")
            fake_say.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            (project / "work").mkdir()
            (project / "work" / "edit-plan.json").write_text(json.dumps(self.plan()))
            (project / "work" / "storyboard.json").write_text(json.dumps(self.story()))
            cmd = [sys.executable, str(ROOT / "scripts" / "story_audio.py"), str(project)]
            no_approval = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(no_approval.returncode, 0)
            self.assertIn("--approve-story", no_approval.stderr)
            self.assertFalse((project / "work" / "bgm.wav").exists())
            voice = project / "work" / "voice.wav"
            voice.write_bytes(b"human")
            collision = subprocess.run(cmd + ["--approve-story"], capture_output=True)
            self.assertNotEqual(collision.returncode, 0)
            self.assertEqual(voice.read_bytes(), b"human")
            input_dir = project / "input"
            input_dir.mkdir()
            captions = input_dir / "captions.srt"
            captions.write_text("人工字幕", encoding="utf-8")
            blocked = subprocess.run(cmd + ["--approve-story", "--replace-audio"],
                                     capture_output=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(captions.read_text(), "人工字幕")
            complete = subprocess.run(cmd + ["--approve-story", "--replace-audio"],
                                      capture_output=True, text=True)
            self.assertNotEqual(complete.returncode, 0)
            complete = subprocess.run(cmd + ["--approve-story", "--replace-audio",
                                              "--replace-captions"],
                                      capture_output=True, text=True, env=env)
            self.assertEqual(complete.returncode, 0, complete.stderr)
            self.assertNotEqual(voice.read_bytes(), b"human")
            self.assertTrue((project / "work" / "bgm.wav").is_file())
            self.assertIn("蓝色背景", captions.read_text())


if __name__ == "__main__":
    unittest.main()
