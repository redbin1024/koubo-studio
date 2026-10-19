import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class JianyingAudioTests(unittest.TestCase):
    def test_audio_span_never_exceeds_source_or_video(self):
        from make_jianying_draft import _audio_span

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice.wav"
            with wave.open(str(path), "wb") as sound:
                sound.setnchannels(2)
                sound.setsampwidth(2)
                sound.setframerate(48000)
                sound.writeframes(struct.pack("<hh", 0, 0) * 24000)
            self.assertAlmostEqual(_audio_span(path, 1.0), 0.5, places=3)
            self.assertAlmostEqual(_audio_span(path, 0.25), 0.25, places=3)


if __name__ == "__main__":
    unittest.main()
