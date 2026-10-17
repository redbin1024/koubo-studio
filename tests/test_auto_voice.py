import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import apply_defaults, ensure_dirs  # noqa: E402
from workflow.auto_voice import AutoVoiceError, build_narration  # noqa: E402


def make_wav(path: Path, seconds: float = 0.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(b"\x10\x01\x10\x01" * int(48000 * seconds))
    return path


class AutoVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        ensure_dirs(self.project)
        self.cfg = apply_defaults({
            "name": "voice-test",
            "duration": 4.0,
            "audio": {"speech_mode": "narration",
                      "voice_subtitle": "voice-captions.srt",
                      "voice_cues": "voice-cues.json"},
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_voice_track_cues_and_subtitle(self):
        calls = []

        def fake_fit(text, budget, cache, index):
            calls.append((text, budget, index))
            path = make_wav(Path(cache) / f"fake-{index}.wav", 0.7)
            return path, "+5%", 0.7

        with mock.patch("workflow.auto_voice.importlib.util.find_spec",
                        return_value=object()), \
                mock.patch("tts.fit_line", side_effect=fake_fit):
            result = build_narration(self.project, self.cfg, [
                {"start": 0.2, "end": 1.5, "text": "第一句",
                 "shot_index": 1, "shot_ref": {"source": "a.mp4", "in": 0, "duration": 2}},
                {"start": 1.8, "end": 3.5, "text": "第二句"},
            ], total=4.0)
        self.assertEqual(len(result["lines"]), 2)
        self.assertEqual(calls[0][0], "第一句")
        voice = self.project / "work" / "voice.wav"
        with wave.open(str(voice), "rb") as sound:
            self.assertEqual(sound.getframerate(), 48000)
            self.assertEqual(sound.getnframes(), 4 * 48000)
        cues = json.loads((self.project / "work" / "voice-cues.json").read_text())
        self.assertEqual(cues["lines"][0]["start"], 0.2)
        self.assertEqual(cues["lines"][0]["shot_index"], 1)
        self.assertNotIn("shot_index", cues["lines"][1])
        subtitle = (self.project / "input" / "voice-captions.srt").read_text()
        self.assertIn("第一句", subtitle)
        self.assertIn("第二句", subtitle)

    def test_skips_lines_that_do_not_fit_and_errors_if_none_fit(self):
        import tts
        with mock.patch("tts.fit_line", side_effect=tts.NarrationError("装不下")):
            with self.assertRaises(AutoVoiceError):
                build_narration(self.project, self.cfg, [
                    {"start": 0.0, "end": 1.0, "text": "装不下"}], total=2.0)

    def test_no_windows_is_an_explicit_error(self):
        with self.assertRaises(AutoVoiceError):
            build_narration(self.project, self.cfg, [], total=2.0)


if __name__ == "__main__":
    unittest.main()
