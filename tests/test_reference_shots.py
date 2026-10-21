import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow.reference_shots import (  # noqa: E402
    build_shots, contact_sheet, plan_segments, strip_times,
)


class BuildShotsTests(unittest.TestCase):
    def test_no_cuts_splits_long_take_into_beats(self):
        shots = build_shots([], 12.0, max_beat=5.0)
        self.assertEqual([round(s["start"], 2) for s in shots], [0.0, 4.0, 8.0])
        self.assertEqual([s["cut"] for s in shots], ["hard", "beat", "beat"])
        self.assertEqual([s["id"] for s in shots], ["s01", "s02", "s03"])

    def test_cuts_are_used_and_too_close_cuts_filtered(self):
        shots = build_shots([2.0, 2.1, 6.0, 9.0], 12.0)
        self.assertEqual([(s["start"], s["end"]) for s in shots],
                         [(0.0, 2.0), (2.0, 6.0), (6.0, 9.0), (9.0, 12.0)])
        self.assertTrue(all(s["cut"] == "hard" for s in shots))

    def test_max_shots_merges_shortest_neighbours(self):
        cuts = [i * 0.5 for i in range(1, 20)]
        shots = build_shots(cuts, 10.0, min_shot=0.2, max_shots=4)
        self.assertLessEqual(len(shots), 4)
        self.assertAlmostEqual(shots[0]["start"], 0.0)
        self.assertAlmostEqual(shots[-1]["end"], 10.0)
        for left, right in zip(shots, shots[1:]):
            self.assertAlmostEqual(left["end"], right["start"])

    def test_invalid_duration_is_an_error(self):
        with self.assertRaises(Exception):
            build_shots([], 0)


class StripAndSegmentTests(unittest.TestCase):
    def setUp(self):
        self.shots = build_shots([2.0, 4.0], 8.0)

    def test_strip_times_inside_shot_and_ordered(self):
        for shot in self.shots:
            times = strip_times(shot)
            self.assertEqual(len(times), 3)
            self.assertGreaterEqual(min(times), shot["start"])
            self.assertLessEqual(max(times), shot["end"])
            self.assertLess(times[0], times[1])
            self.assertLess(times[1], times[2])

    def test_segments_cut_on_shot_boundary_and_stay_bounded(self):
        shots = build_shots([1.0, 6.0, 7.0, 12.0, 20.0, 21.0, 22.0], 30.0)
        segments = plan_segments(shots, max_sec=15.0)
        self.assertTrue(segments)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[-1]["end"], 30.0)
        known = {s["id"] for s in shots}
        seen = [ident for seg in segments for ident in seg["shots"]]
        self.assertEqual(len(seen), len(shots))
        self.assertEqual(set(seen), known)
        for segment in segments:
            self.assertLessEqual(segment["duration"], 15.01)

    def test_contact_sheet_writes_an_image(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            frames = out / "frames"
            frames.mkdir()
            rows = []
            for index, color in enumerate(((220, 30, 30), (30, 180, 180)), 1):
                path = frames / f"strip-{index:02d}.jpg"
                Image.new("RGB", (300, 120), color).save(path)
                rows.append({"id": f"s{index:02d}", "index": index,
                             "start": 0.0, "end": 1.0, "duration": 1.0,
                             "strip": f"frames/strip-{index:02d}.jpg"})
            sheet = contact_sheet(rows, out)
            self.assertTrue(sheet and Path(sheet).is_file())
            self.assertGreater(Path(sheet).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
