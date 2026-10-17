import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class AutoCaptionsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("auto_captions"))
        import auto_captions
        return auto_captions

    def test_groups_words_on_pauses_without_punctuation(self):
        auto_captions = self.module()
        words = [
            {"text": "你好，", "start": 0.1, "end": 0.4, "confidence": 0.9},
            {"text": "世界", "start": 0.4, "end": 0.7, "confidence": 0.9},
            {"text": "今天。", "start": 1.5, "end": 1.9, "confidence": 0.9},
        ]
        self.assertEqual(auto_captions.make_cues(words), [
            {"start": 0.1, "end": 0.7, "text": "你好世界"},
            {"start": 1.5, "end": 1.9, "text": "今天"},
        ])

    def test_writes_srt_and_preserves_manual_file(self):
        auto_captions = self.module()
        transcript = {"duration": 2, "words": [
            {"text": "示例", "start": 0.1, "end": 0.6, "confidence": 0.9}]}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "input" / "captions.srt"
            result = auto_captions.write_srt(transcript, output)
            self.assertEqual(result["status"], "ok")
            self.assertIn("00:00:00,100 --> 00:00:00,600", output.read_text())
            output.write_text("人工文案", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                auto_captions.write_srt(transcript, output)
            self.assertEqual(output.read_text(), "人工文案")
            self.assertEqual(auto_captions.write_srt(
                {"duration": 2, "words": []}, output, force=True)["status"], "no_speech")
            self.assertEqual(output.read_text(), "人工文案")
            auto_captions.write_srt(transcript, output, force=True)
            self.assertNotEqual(output.read_text(), "人工文案")

    def test_adjacent_cues_do_not_overlap_when_word_timestamps_overlap(self):
        auto_captions = self.module()
        words = [
            {"text": "这是一个比较长的中文口播句子", "start": 0.1,
             "end": 1.5, "confidence": 0.9},
            {"text": "下一句", "start": 1.4, "end": 2.0, "confidence": 0.8},
        ]
        cues = auto_captions.make_cues(words)
        self.assertEqual(len(cues), 2)
        self.assertLessEqual(cues[0]["end"], cues[1]["start"])


if __name__ == "__main__":
    unittest.main()
