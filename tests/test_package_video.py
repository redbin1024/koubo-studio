import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class PackageVideoTests(unittest.TestCase):
    def test_prepare_uses_existing_edit_without_clips(self):
        from package_video import prepare
        from _common import find_ffmpeg, load_config, project_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "already-edited.mp4"
            srt = root / "already-edited.srt"
            subprocess.run([
                find_ffmpeg(), "-v", "error", "-y",
                "-f", "lavfi", "-i", "color=c=#223344:s=720x1280:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(video)], check=True)
            srt.write_text("1\n00:00:00,000 --> 00:00:00,900\n示例\n",
                           encoding="utf-8")
            project = root / "project"
            prepare(project, video, srt, captions="burned-in", name="pkg")
            cfg = load_config(project_paths(project)["config"])
            self.assertEqual(cfg["input"]["video"], str(video.resolve()))
            self.assertEqual(cfg["input"]["clips"], [])
            self.assertEqual(cfg["audio"]["speech_mode"], "source")
            self.assertEqual(cfg["captions"]["mode"], "burned-in")
            self.assertEqual(cfg["jianying"]["name"], "pkg")
            self.assertTrue((project / "input" / "captions.srt").is_file())
            marker = json.loads((project / "work" / "package-only.json").read_text())
            self.assertEqual(marker["captions_mode"], "burned-in")


if __name__ == "__main__":
    unittest.main()
