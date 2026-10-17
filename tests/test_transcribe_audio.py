import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class TranscribeAudioTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("transcribe_audio"))
        import transcribe_audio
        return transcribe_audio

    def test_normalize_words_checks_boundaries(self):
        transcribe_audio = self.module()
        word = {"text": "你好", "start": 0.1, "end": 0.5, "confidence": 0.9}
        self.assertEqual(transcribe_audio.normalize_words([word], 2), [word])
        zero_tail = {"text": "的", "start": 2.0, "end": 2.0, "confidence": 0.7}
        self.assertEqual(transcribe_audio.normalize_words([word, zero_tail], 2)[-1],
                         {"text": "的", "start": 1.98, "end": 2.0, "confidence": 0.7})
        for bad in ({"text": "", "start": 0, "end": 1, "confidence": 0.9},
                    {"text": "你好", "start": 1, "end": 0.5, "confidence": 0.9},
                    {"text": "你好", "start": float("nan"), "end": 1, "confidence": 0.9},
                    {"text": "你好", "start": 2.0, "end": 2.5, "confidence": 0.9}):
            with self.subTest(word=bad), self.assertRaises(ValueError):
                transcribe_audio.normalize_words([bad], 2)
        with self.assertRaises(ValueError):
            transcribe_audio.normalize_words([word, {**word, "start": 0.0}], 2)

    def test_transcribe_writes_words_and_reports_no_speech(self):
        transcribe_audio = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "audio.wav", Path(tmp) / "transcript.json"
            src.touch()

            class FakeModel:
                def __init__(self, words):
                    self.words = words

                def transcribe(self, *_args, **_kwargs):
                    segment = SimpleNamespace(start=0.1, end=0.5, text="你好",
                                              words=self.words)
                    return iter([segment]), SimpleNamespace(
                        language="zh", language_probability=0.99, duration=2.0)

            word = SimpleNamespace(word="你好", start=0.1, end=0.5, probability=0.9)
            result = transcribe_audio.transcribe(src, out, model_factory=lambda _: FakeModel([word]))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(json.loads(out.read_text())["words"][0]["text"], "你好")
            empty = transcribe_audio.transcribe(src, out, model_factory=lambda _: FakeModel([]))
            self.assertEqual(empty["status"], "no_speech")
            self.assertEqual(json.loads(out.read_text())["words"], [])


if __name__ == "__main__":
    unittest.main()
