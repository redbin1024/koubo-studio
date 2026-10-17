import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class StoryboardTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("storyboard"))
        import storyboard
        return storyboard

    def review(self):
        return {"mode": "vlog", "shots": [
            {"source": "/private/a.mp4", "in": 0, "duration": 2,
             "visual": {"description": "蓝色背景", "usable": True, "confidence": 0.9}},
            {"source": "/private/b.mp4", "in": 1, "duration": 3,
             "visual": {"description": "户外建筑", "usable": True, "confidence": 0.8}},
        ]}

    def response(self):
        return {"order": ["shot_2", "shot_1"], "narration": [
            {"shot_id": "shot_1", "text": "蓝色背景", "evidence": ["shot_1"]}],
                "music_mood": "calm"}

    def test_validates_evidence_and_computes_timeline(self):
        story = self.module()
        result = story.validate_story(self.review(), self.response())
        self.assertEqual(result["narration"][0]["start"], 3.0)
        self.assertEqual(result["order"], ["shot_2", "shot_1"])
        self.assertEqual(result["shot_refs"]["shot_2"]["source"], "/private/b.mp4")
        for change in (
            {"order": ["shot_1", "shot_1"]},
            {"narration": [{"shot_id": "shot_1", "text": "编造", "evidence": []}]},
            {"narration": [{"shot_id": "shot_9", "text": "编造", "evidence": ["shot_9"]}]},
            {"narration": [{"shot_id": "shot_1", "text": "很" * 31, "evidence": ["shot_1"]}]},
            {"music_mood": "aggressive"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                story.validate_story(self.review(), {**self.response(), **change})
        with self.assertRaises(ValueError):
            story.validate_story({**self.review(), "mode": "talking-head"}, self.response())

    def test_sends_only_sanitized_evidence_and_requires_key(self):
        story = self.module()
        seen = []

        def transport(body, key):
            seen.append((body, key))
            return {"choices": [{"message": {"content": json.dumps(self.response())}}]}

        result = story.suggest_story(self.review(), "现场口播", api_key="key",
                                     transport=transport)
        self.assertTrue(result["review_required"])
        self.assertEqual(result["narration"][0]["start"], 3.0)
        self.assertNotIn("/private/", json.dumps(seen[0][0]))
        self.assertIn("现场口播", json.dumps(seen[0][0], ensure_ascii=False))
        self.assertEqual(seen[0][0]["model"], "deepseek-flash")
        self.assertEqual(seen[0][0]["max_tokens"], 2200)
        with self.assertRaises(ValueError):
            story.suggest_story(self.review(), "", api_key="", transport=transport)

    def test_story_uses_only_deepseek_environment_key(self):
        story = self.module()
        seen = []

        def transport(_body, key):
            seen.append(key)
            return {"choices": [{"message": {"content": json.dumps(self.response())}}]}

        with patch.dict(os.environ, {"OPENAI_API_KEY": "other-provider-key"}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                story.suggest_story(self.review(), transport=transport)
        self.assertEqual(seen, [])
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "dummy-deepseek-key"}, clear=True):
            story.suggest_story(self.review(), transport=transport)
        self.assertEqual(seen, ["dummy-deepseek-key"])

    def test_effect_beats_must_reference_unique_shots(self):
        story = self.module()
        valid = {**self.response(), "beats": [
            {"shot_id": "shot_2", "cue": "reveal"}]}
        self.assertEqual(story.validate_story(self.review(), valid)["beats"],
                         valid["beats"])
        for beats in ([{"shot_id": "shot_9", "cue": "cut"}],
                      [{"shot_id": "shot_2", "cue": "unknown"}],
                      [{"shot_id": "shot_2", "cue": "cut"},
                       {"shot_id": "shot_2", "cue": "wipe"}]):
            with self.subTest(beats=beats), self.assertRaises(ValueError):
                story.validate_story(self.review(), {**valid, "beats": beats})


if __name__ == "__main__":
    unittest.main()
