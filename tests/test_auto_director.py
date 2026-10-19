import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import auto_director  # noqa: E402


def candidates(durations=(2.0, 2.0, 2.0)):
    return [
        {"id": f"shot_{i + 1}", "source": f"/tmp/clip-{i}.mp4",
         "in": 0.0, "duration": float(d), "transcript": text}
        for i, (d, text) in enumerate(zip(durations, (
            "大家好今天分享方法", "第一个方法是列清单", "第二个方法是关通知")))
    ]


def response(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class TalkingHeadDirectorTests(unittest.TestCase):
    def test_no_key_falls_back_to_all_candidates(self):
        result = auto_director.direct_talking_head(candidates(), api_key="")
        self.assertEqual(result.source, "local")
        self.assertEqual([s["id"] for s in result.shots], ["shot_1", "shot_2", "shot_3"])
        self.assertIn("没有 DEEPSEEK_API_KEY", result.notes[0])

    def test_llm_selection_order_and_highlight_validation(self):
        seen = {}

        def transport(body, key):
            seen.update(json.loads(body["messages"][1]["content"]))
            return response({
                "shots": ["shot_3", "shot_1"],
                "highlights": ["方法", "不存在", "方"],
                "music_mood": "calm",
                "beats": [{"shot_id": "shot_3", "cue": "cut"},
                          {"shot_id": "shot_3", "cue": "wipe"},
                          {"shot_id": "shot_9", "cue": "reveal"}],
                "notes": "保留信息量",
            })

        result = auto_director.direct_talking_head(candidates(), api_key="k",
                                                   transport=transport)
        self.assertEqual(result.source, "llm")
        self.assertEqual([s["id"] for s in result.shots], ["shot_3", "shot_1"])
        self.assertEqual(result.highlights, ["方法"])
        self.assertEqual(result.beats, [{"shot_id": "shot_3", "cue": "cut"}])
        self.assertEqual(result.music_mood, "calm")
        self.assertEqual(seen["candidates"][0]["id"], "shot_1")
        self.assertNotIn("/tmp/clip", json.dumps(seen, ensure_ascii=False))

    def test_selection_that_drops_too_much_is_rejected(self):
        result = auto_director.direct_talking_head(
            candidates(), api_key="k",
            transport=lambda body, key: response({"shots": ["shot_1"]}))
        self.assertEqual(result.source, "local")
        self.assertEqual(len(result.shots), 3)

    def test_unknown_shot_id_is_rejected(self):
        result = auto_director.direct_talking_head(
            candidates(), api_key="k",
            transport=lambda body, key: response({"shots": ["shot_9"]}))
        self.assertEqual(result.source, "local")

    def test_invalid_mood_falls_back_but_selection_survives(self):
        result = auto_director.direct_talking_head(
            candidates(), api_key="k",
            transport=lambda body, key: response({
                "shots": ["shot_1", "shot_2"], "music_mood": "epic"}))
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.music_mood, "warm")


class VlogDirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.shots = []
        for i in range(2):
            path = self.dir / f"clip-{i}.mp4"
            path.write_bytes(b"placeholder")
            self.shots.append({"id": f"shot_{i + 1}", "source": str(path),
                               "in": 0.0, "duration": 2.0, "transcript": "现场"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_key_keeps_local_order(self):
        result = auto_director.direct_vlog(self.shots, api_key="")
        self.assertEqual(result.source, "local")
        self.assertEqual([s["id"] for s in result.shots], ["shot_1", "shot_2"])

    def test_visual_then_story_requests_are_validated(self):
        calls = []

        def transport(body, key):
            calls.append(body)
            if len(calls) == 1:
                return response({"shots": [
                    {"id": "shot_1", "description": "室内", "usable": True,
                     "confidence": 0.9, "caption_suggestion": "室内"},
                    {"id": "shot_2", "description": "室外", "usable": True,
                     "confidence": 0.8, "caption_suggestion": "室外"},
                ]})
            return response({
                "order": ["shot_2", "shot_1"],
                "narration": [{"shot_id": "shot_2", "text": "先看室外",
                               "evidence": ["shot_2"]}],
                "music_mood": "warm", "beats": [],
            })

        with mock.patch("workflow.visual_analysis.extract_frame") as extract, \
                mock.patch("workflow.visual_analysis.probe_media",
                           return_value={"duration": 4.0}):
            extract.side_effect = lambda source, at, output: Path(output).write_bytes(b"jpeg")
            result = auto_director.direct_vlog(self.shots, transcript_text="现场",
                                               api_key="k", transport=transport)
        self.assertEqual(result.source, "llm")
        self.assertEqual([s["id"] for s in result.shots], ["shot_2", "shot_1"])
        self.assertEqual(result.story["order"], ["shot_2", "shot_1"])
        self.assertEqual(result.narration[0]["text"], "先看室外")
        self.assertEqual(len(calls), 2)
        self.assertIn("spoken_text", calls[1]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()


class HostDirectorTests(unittest.TestCase):
    def test_host_talking_head_uses_same_validation(self):
        result = auto_director.from_host_talking_head(candidates(), {
            "shots": ["shot_2", "shot_1"],
            "highlights": ["方法"],
            "music_mood": "calm",
            "beats": [{"shot_id": "shot_2", "cue": "cut"}],
        })
        self.assertEqual(result.source, "host")
        self.assertEqual([s["id"] for s in result.shots], ["shot_2", "shot_1"])
        self.assertEqual(result.highlights, ["方法"])
        with self.assertRaises(ValueError):
            auto_director.from_host_talking_head(candidates(), {"shots": ["shot_9"]})
        with self.assertRaises(ValueError):
            auto_director.from_host_talking_head(candidates(), {"shots": ["shot_1"]})

    def test_host_vlog_builds_story_and_validates_narration(self):
        vlog = [
            {"id": "shot_1", "source": "/tmp/a.mp4", "in": 0.0, "duration": 2.0,
             "transcript": "一"},
            {"id": "shot_2", "source": "/tmp/b.mp4", "in": 0.0, "duration": 3.0,
             "transcript": "二"},
        ]
        result = auto_director.from_host_vlog(vlog, {
            "order": ["shot_2", "shot_1"],
            "narration": [{"shot_id": "shot_2", "text": "先看第二段",
                           "evidence": ["shot_2"]}],
            "music_mood": "warm",
        })
        self.assertEqual(result.source, "host")
        self.assertEqual([s["id"] for s in result.shots], ["shot_2", "shot_1"])
        self.assertEqual(result.story["order"], ["shot_2", "shot_1"])
        self.assertEqual(result.story["narration"][0]["start"], 0.0)
        with self.assertRaises(ValueError):
            auto_director.from_host_vlog(vlog, {"order": ["shot_1"]})
        with self.assertRaises(ValueError):
            auto_director.from_host_vlog(vlog, {
                "order": ["shot_1", "shot_2"],
                "narration": [{"shot_id": "shot_1", "text": "太" * 31,
                               "evidence": ["shot_1"]}],
            })
