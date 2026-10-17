import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class VisualAnalysisTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("visual_analysis"))
        import visual_analysis
        return visual_analysis

    def make_video(self, root):
        video = root / "frame.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=blue:s=64x64:r=10:d=1", "-c:v", "libx264",
                        str(video)], check=True)
        return video

    def test_transport_posts_only_to_deepseek(self):
        visual = self.module()
        seen = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"choices":[]}'

        def open_request(request, timeout):
            seen.append((request, timeout))
            return Response()

        with patch.object(visual.urllib.request, "urlopen", side_effect=open_request):
            visual._http_transport({"model": "deepseek-flash"}, "dummy-key")
        request, timeout = seen[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer dummy-key")
        self.assertEqual(timeout, 90)

    def test_only_deepseek_environment_key_is_accepted(self):
        visual = self.module()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "other-provider-key"}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                visual.analyze_shots({"shots": []})

    def test_extracts_a_jpeg_without_changing_source(self):
        visual = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            video = self.make_video(root)
            original = video.stat().st_size
            image = root / "frame.jpg"
            visual.extract_frame(video, 0.2, image)
            self.assertGreater(image.stat().st_size, 0)
            self.assertEqual(video.stat().st_size, original)
            with self.assertRaises(ValueError):
                visual.extract_frame(video, -1, image)

    def test_attaches_only_valid_id_matched_suggestions(self):
        visual = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            video = self.make_video(Path(tmp).resolve())
            plan = {"version": 1, "mode": "vlog", "shots": [
                {"source": str(video), "in": 0.1, "duration": 0.6}]}
            seen = []

            def transport(body, key):
                seen.append((body, key))
                return {"choices": [{"message": {"content": json.dumps({"shots": [
                    {"id": "shot_1", "description": "蓝色画面", "usable": True,
                     "confidence": 0.9, "caption_suggestion": "蓝色背景"}]})}}]}

            annotated = visual.analyze_shots(plan, transport=transport, api_key="test-key")
            self.assertNotIn("visual", plan["shots"][0])
            self.assertEqual(annotated["shots"][0]["visual"]["description"], "蓝色画面")
            self.assertNotIn(str(video), json.dumps(seen[0][0]))
            self.assertIn("data:image/jpeg;base64,", json.dumps(seen[0][0]))
            self.assertEqual(seen[0][0]["model"], "deepseek-flash")
            self.assertEqual(seen[0][0]["max_tokens"], 1200)
            self.assertEqual(seen[0][0]["messages"][1]["content"][-1]["image_url"]["detail"],
                             "low")
            self.assertEqual(seen[0][1], "test-key")

            def wrong_id(_body, _key):
                return {"choices": [{"message": {"content": json.dumps({"shots": [
                    {"id": "shot_9", "description": "蓝色", "usable": True,
                     "confidence": 0.9, "caption_suggestion": ""}]})}}]}

            with self.assertRaises(ValueError):
                visual.analyze_shots(plan, transport=wrong_id, api_key="test-key")
            with self.assertRaises(ValueError):
                visual.analyze_shots(plan, transport=transport, api_key="")
            with self.assertRaises(ValueError):
                visual.analyze_shots({**plan, "shots": plan["shots"] * 25},
                                     transport=transport, api_key="test-key")

    def test_cli_missing_key_does_not_touch_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            (project / "input").mkdir()
            source = self.make_video(project / "input")
            config = project / "config.json"
            config.write_text(json.dumps({"canvas": {"width": 64, "height": 64, "fps": 10}}))
            cmd = [sys.executable, str(ROOT / "scripts" / "auto_edit.py"), str(project)]
            subprocess.run(cmd + ["--mode", "vlog", "--clips", source.name],
                           check=True, capture_output=True)
            before = (project / "input" / "clean-cut.mp4").read_bytes(), config.read_bytes()
            env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
            env["OPENAI_API_KEY"] = "other-provider-key"
            result = subprocess.run(cmd + ["--apply-plan", "--vision"], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DEEPSEEK_API_KEY", result.stderr)
            self.assertEqual(((project / "input" / "clean-cut.mp4").read_bytes(),
                              config.read_bytes()), before)
            story_only = subprocess.run(cmd + ["--apply-plan", "--story"], env=env,
                                        capture_output=True, text=True)
            self.assertNotEqual(story_only.returncode, 0)
            self.assertIn("--story 需要 --vision", story_only.stderr)


if __name__ == "__main__":
    unittest.main()
