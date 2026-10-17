import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StoryEffectsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("story_effects"))
        import story_effects
        return story_effects

    def story(self):
        return {"status": "proposal", "review_required": True,
                "order": ["shot_1", "shot_2"], "duration": 4,
                "shot_refs": {
                    "shot_1": {"source": "/tmp/one.mp4", "in": 0, "duration": 2},
                    "shot_2": {"source": "/tmp/two.mp4", "in": 0, "duration": 2}},
                "narration": [], "music_mood": "warm",
                "beats": [{"shot_id": "shot_2", "cue": "reveal"}]}

    def test_maps_only_evidenced_effect_beats(self):
        effects = self.module()
        self.assertEqual(effects.suggest_events(self.story()),
                         [{"t": 2.0, "cue": "reveal"}])
        self.assertEqual(effects.suggest_events({**self.story(), "beats": []}), [])
        with self.assertRaises(ValueError):
            effects.suggest_events({**self.story(), "beats": [
                {"shot_id": "shot_9", "cue": "wipe"}]})

    def test_cli_requires_approval_and_preserves_manual_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            (project / "work").mkdir()
            plan = {"version": 1, "mode": "vlog", "shots": [
                {"source": "/tmp/one.mp4", "in": 0, "duration": 2},
                {"source": "/tmp/two.mp4", "in": 0, "duration": 2}]}
            (project / "work" / "edit-plan.json").write_text(json.dumps(plan))
            (project / "work" / "storyboard.json").write_text(json.dumps(self.story()))
            config = project / "config.json"
            config.write_text(json.dumps({"name": "custom", "sfx": {"events": [
                {"t": 1, "cue": "tick"}]}}))
            cmd = [sys.executable, str(ROOT / "scripts" / "story_effects.py"),
                   str(project)]
            unapproved = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(unapproved.returncode, 0)
            self.assertIn("--approve-story", unapproved.stderr)
            collision = subprocess.run(cmd + ["--approve-story"], capture_output=True)
            self.assertNotEqual(collision.returncode, 0)
            self.assertEqual(json.loads(config.read_text())["sfx"]["events"],
                             [{"t": 1, "cue": "tick"}])
            applied = subprocess.run(cmd + ["--approve-story", "--replace-events"],
                                     capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(json.loads(config.read_text())["name"], "custom")
            self.assertEqual(json.loads(config.read_text())["sfx"]["events"],
                             [{"t": 2.0, "cue": "reveal"}])


if __name__ == "__main__":
    unittest.main()
