import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class AutoEditTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("auto_edit"))
        import auto_edit
        return auto_edit

    def test_talking_head_selects_speech_and_rejects_silent_clips(self):
        auto_edit = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            clip = (Path(tmp) / "talk.mp4").resolve()
            shots = auto_edit.talking_head_shots(
                [clip], {str(clip): {"duration": 6, "has_audio": True}},
                lambda _: [(0, 1), (3, 4)])
            self.assertEqual([(s["in"], s["duration"]) for s in shots],
                             [(0.9, 2.2), (3.9, 2.1)])
            self.assertTrue(all(s["reason"] == "speech" for s in shots))
            with self.assertRaises(ValueError):
                auto_edit.talking_head_shots(
                    [clip], {str(clip): {"duration": 6, "has_audio": True}},
                    lambda _: [(0, 6)])
            with self.assertRaises(ValueError):
                auto_edit.talking_head_shots(
                    [clip], {str(clip): {"duration": 6, "has_audio": False}},
                    lambda _: [])

    def test_vlog_selects_scene_windows_without_audio(self):
        auto_edit = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            first = (Path(tmp) / "first.mp4").resolve()
            second = (Path(tmp) / "second.mp4").resolve()
            info = {str(first): {"duration": 10, "has_audio": False},
                    str(second): {"duration": 3, "has_audio": True}}
            cuts = {first: [1, 9.7], second: []}
            shots = auto_edit.vlog_shots([first, second], info, lambda p: cuts[p])
            self.assertEqual([s["source"] for s in shots],
                             [str(first), str(first), str(first), str(second)])
            self.assertEqual([(s["in"], s["duration"]) for s in shots],
                             [(0, 1), (1, 8.7), (9.7, 0.3), (0, 3)])
            self.assertTrue(all(s["reason"] == "scene" for s in shots))

    def test_vlog_does_not_impose_a_shot_or_total_length_cap(self):
        auto_edit = self.module()
        clip = Path('/tmp/continuous-action.mov')
        shots = auto_edit.vlog_shots([clip], {str(clip): {"duration": 52.5}}, lambda _: [])
        self.assertEqual(shots[0]["in"], 0)
        self.assertEqual(shots[0]["duration"], 52.5)

    def test_actual_cut_length_overrides_old_config_duration(self):
        from unittest.mock import patch
        from _common import resolve_duration
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / 'input').mkdir()
            (project / 'input/clean-cut.mp4').write_bytes(b'current cut')
            cfg = {"input": {"video": "clean-cut.mp4"}, "duration": 29}
            with patch('_common.probe_media', return_value={"duration": 52.5}):
                self.assertEqual(resolve_duration(cfg, project), 52.5)

    def test_per_shot_mute_removes_unrelated_broadcast(self):
        from array import array
        from workflow.edit_plan import render_plan, validate_plan
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'source.mp4', Path(tmp) / 'cut.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                            'color=c=blue:s=64x64:r=10:d=1','-f','lavfi','-i',
                            'sine=frequency=440:duration=1','-c:v','libx264','-c:a','aac',
                            '-shortest',str(source)],check=True)
            plan={'version':1,'mode':'vlog','shots':[
                {'source':str(source),'in':0,'duration':1,'audio_gain':0}]}
            render_plan(plan,output,64,64,10)
            pcm=subprocess.run(['ffmpeg','-v','error','-i',str(output),'-map','0:a:0',
                                '-f','s16le','-'],check=True,capture_output=True).stdout
            samples=array('h');samples.frombytes(pcm)
            self.assertLess(max(abs(sample) for sample in samples),10)
            plan['shots'][0]['audio_gain']=-1
            with self.assertRaisesRegex(ValueError,'原声音量'):
                validate_plan(plan,{str(source.resolve()):1})

    def test_cli_generates_cut_and_reapplies_hand_edited_plan(self):
        self.module()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            source = project / "input" / "shot.mp4"
            source.parent.mkdir()
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x64:r=10:d=1.5", "-c:v", "libx264",
                            str(source)], check=True)
            config = project / "config.json"
            config.write_text(json.dumps({"name": "demo", "canvas": {
                "width": 64, "height": 64, "fps": 10}, "custom": "keep",
                "audio": {"speech_mode": None}}))
            cmd = [sys.executable, str(ROOT / "scripts" / "auto_edit.py"), str(project)]
            subprocess.run(cmd + ["--mode", "vlog", "--clips", "shot.mp4"],
                           check=True, capture_output=True)
            plan_path = project / "work" / "edit-plan.json"
            plan = json.loads(plan_path.read_text())
            self.assertEqual(plan["mode"], "vlog")
            self.assertEqual(len(plan["shots"]), 1)
            self.assertTrue((project / "input" / "clean-cut.mp4").is_file())
            self.assertEqual(json.loads(config.read_text())["custom"], "keep")
            self.assertEqual(json.loads(config.read_text())["mode"], "vlog")
            self.assertEqual(json.loads(config.read_text())["audio"]["speech_mode"],
                             "narration")
            plan["shots"][0]["duration"] = 0.6
            plan_path.write_text(json.dumps(plan))
            subprocess.run(cmd + ["--apply-plan"], check=True, capture_output=True)
            from _common import probe_media
            self.assertAlmostEqual(probe_media(project / "input" / "clean-cut.mp4")[
                "duration"], 0.6, delta=0.15)
            self.assertEqual(json.loads(config.read_text())["input"]["video"],
                             "clean-cut.mp4")
            old_config = config.read_bytes()
            plan["shots"][0]["in"] = 100
            plan_path.write_text(json.dumps(plan))
            failed = subprocess.run(cmd + ["--apply-plan"], capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(config.read_bytes(), old_config)

    def test_auto_captions_stages_cut_and_preserves_manual_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            source = project / "input" / "shot.mp4"
            source.parent.mkdir()
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x64:r=10:d=1.5", "-c:v", "libx264",
                            str(source)], check=True)
            config = project / "config.json"
            config.write_text(json.dumps({"name": "demo", "canvas": {
                "width": 64, "height": 64, "fps": 10}}))
            transcript = project / "prepared-transcript.json"
            transcript.write_text(json.dumps({"source": str(project / "input" / "clean-cut.mp4"),
                "duration": 1.5, "words": [
                    {"text": "你好", "start": 0.1, "end": 0.6, "confidence": 0.9}]}))
            cmd = [sys.executable, str(ROOT / "scripts" / "auto_edit.py"), str(project),
                   "--mode", "vlog", "--clips", "shot.mp4", "--auto-captions",
                   "--transcript", str(transcript)]
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
            self.assertIn(str(project / "input" / "clean-cut.mp4"), completed.stdout)
            cut = project / "input" / "clean-cut.mp4"
            srt = project / "input" / "captions.srt"
            self.assertIn("你好", srt.read_text())
            before_video, before_config = cut.read_bytes(), config.read_bytes()
            srt.write_text("人工字幕", encoding="utf-8")
            result = subprocess.run(cmd, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((cut.read_bytes(), config.read_bytes(), srt.read_text()),
                             (before_video, before_config, "人工字幕"))
            empty = project / "empty-transcript.json"
            empty.write_text(json.dumps({"duration": 1.5, "words": []}))
            result = subprocess.run(cmd[:-1] + [str(empty), "--replace-captions"],
                                    capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(srt.read_text(), "人工字幕")
            subprocess.run(cmd + ["--replace-captions"], check=True, capture_output=True)
            self.assertIn("你好", srt.read_text())


if __name__ == "__main__":
    unittest.main()
