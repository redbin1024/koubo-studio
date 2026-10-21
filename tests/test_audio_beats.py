import sys, unittest
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class BeatTests(unittest.TestCase):
    def test_detects_loud_pulses(self):
        from workflow.audio_beats import detect, SR
        audio = np.zeros(SR * 3, dtype=np.float32)
        for t in (0.8, 1.8, 2.8):
            start = int(t * SR)
            audio[start:start + int(0.12 * SR)] = 0.3
        result = detect(audio, fps=30)
        self.assertGreaterEqual(len(result["beats"]), 2)
        self.assertLessEqual(len(result["beats"]), 4)
        self.assertTrue(all(0 <= b["frame"] <= 90 for b in result["beats"]))


if __name__ == "__main__":
    unittest.main()
