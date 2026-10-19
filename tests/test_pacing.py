import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class PacingTests(unittest.TestCase):
    def test_adaptive_threshold_ignores_low_scores_and_keeps_best_peak(self):
        from workflow.pacing import adaptive_cuts
        scores = [(0.0, 0.01), (0.5, 0.02), (1.0, 0.55),
                  (1.1, 0.72), (2.0, 0.03)]
        cuts = adaptive_cuts(scores, min_gap=0.5)
        self.assertEqual([c["t"] for c in cuts], [1.1])

    def test_empty_scores_are_safe(self):
        from workflow.pacing import adaptive_cuts
        self.assertEqual(adaptive_cuts([]), [])


if __name__ == "__main__":
    unittest.main()
