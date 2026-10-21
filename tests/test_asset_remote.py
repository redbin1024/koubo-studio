from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import asset_library as lib  # noqa: E402
from workflow import asset_remote as remote  # noqa: E402


PEXELS_VIDEO = {
    "videos": [{
        "id": 123, "width": 1920, "height": 1080, "duration": 12,
        "url": "https://www.pexels.com/video/123/", "image": "https://img/123.jpg",
        "user": {"name": "Ann", "url": "https://www.pexels.com/@ann"},
        "video_files": [
            {"file_type": "video/mp4", "link": "https://v/720.mp4", "width": 1280, "height": 720},
            {"file_type": "video/mp4", "link": "https://v/1080.mp4", "width": 1920, "height": 1080},
        ],
    }],
}

PIXABAY_VIDEO = {
    "hits": [{
        "id": 9, "pageURL": "https://pixabay.com/videos/9/", "tags": "city,night",
        "duration": 8, "user": "Bob", "user_id": 7,
        "videos": {
            "large": {"url": "https://v/large.mp4", "width": 1920, "height": 1080},
            "medium": {"url": "https://v/med.mp4", "width": 1280, "height": 720},
        },
    }],
}

PEXELS_PHOTO = {
    "photos": [{
        "id": 55, "width": 3000, "height": 2000, "url": "https://www.pexels.com/photo/55/",
        "alt": "City at night", "photographer": "Cara",
        "photographer_url": "https://www.pexels.com/@cara",
        "src": {"original": "https://img/55.jpg", "medium": "https://img/55-m.jpg"},
    }],
}


class RemoteParseTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "PEXELS_API_KEY": "test", "PIXABAY_API_KEY": "test"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_pexels_video_picks_quality_and_metadata(self):
        items = remote.search("pexels", "video", "city",
                              fetch=lambda url, headers: PEXELS_VIDEO)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["provider_id"], "123")
        self.assertTrue(item["download_url"].endswith("1080.mp4"))
        self.assertEqual(item["creator"], "Ann")
        self.assertEqual(item["license"], "Pexels-License")
        self.assertEqual(item["duration"], 12.0)

    def test_pixabay_video(self):
        items = remote.search("pixabay", "video", "city",
                              fetch=lambda url, headers: PIXABAY_VIDEO)
        self.assertEqual(items[0]["provider_id"], "9")
        self.assertTrue(items[0]["download_url"].endswith("large.mp4"))
        self.assertEqual(items[0]["tags"], ["city", "night"])

    def test_pexels_photo(self):
        items = remote.search("pexels", "photo", "city",
                              fetch=lambda url, headers: PEXELS_PHOTO)
        self.assertEqual(items[0]["download_url"], "https://img/55.jpg")
        self.assertEqual(items[0]["creator"], "Cara")

    def test_missing_key_is_explicit(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(remote.RemoteError):
                remote.search("pexels", "video", "city",
                              fetch=lambda url, headers: PEXELS_VIDEO)

    def test_find_matches_id(self):
        item = remote.find("pexels", "video", "123", query="city",
                           fetch=lambda url, headers: PEXELS_VIDEO)
        self.assertEqual(item["provider_id"], "123")


class AddAndImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "lib"
        lib.init_library(self.root, seed=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_uses_download_and_registers(self):
        item = {
            "provider": "pexels", "media": "video", "provider_id": "123",
            "title": "City night", "page_url": "https://www.pexels.com/video/123/",
            "download_url": "https://v/1080.mp4", "creator": "Ann",
            "creator_url": "https://www.pexels.com/@ann",
            "license": "Pexels-License", "query": "city", "tags": ["city"],
            "width": 1920, "height": 1080, "duration": 12,
        }

        def fake_download(_, dest):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"fake video")
            return Path(dest)

        with mock.patch.object(remote, "download", side_effect=fake_download):
            entry = remote.add(item, library_root=self.root)
        self.assertEqual(entry["provider"], "pexels")
        self.assertEqual(entry["license"], "Pexels-License")
        self.assertEqual(entry["source_url"], item["page_url"])
        self.assertEqual(len(lib.load_registry(self.root)), 1)

    def test_import_sfx_kit(self):
        kit = Path(self.tmp.name) / "kit"
        sound = kit / "sounds" / "whooshes" / "whoosh-test.wav"
        sound.parent.mkdir(parents=True)
        with wave.open(str(sound), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(48000)
            f.writeframes(b"\x00\x00" * 4800)
        (kit / "sounds.json").write_text(json.dumps({
            "license": "CC0-1.0", "homepage": "https://github.com/wyzowl/sfx-kit",
            "sounds": [{
                "id": "whoosh-test", "name": "Test whoosh", "category": "whooshes",
                "file": "sounds/whooshes/whoosh-test.wav", "tags": ["whoosh"],
                "duration": 0.1, "sync": {"at": 0.02, "meets": "move-peak"},
            }],
        }), encoding="utf-8")
        got = remote.import_sfx_kit(kit, library_root=self.root)
        self.assertEqual(got["added"], ["sfx/sfx-kit-whoosh-test"])
        entry = lib.load_registry(self.root)[0]
        self.assertEqual(entry["provider"], "sfx-kit")
        self.assertEqual(entry["license"], "CC0-1.0")
        self.assertEqual(entry["sync"]["at"], 0.02)

    def test_import_sfx_kit_rejects_non_cc0(self):
        kit = Path(self.tmp.name) / "kit2"
        kit.mkdir()
        (kit / "sounds.json").write_text(json.dumps({"license": "CC-BY-NC-4.0",
                                                     "sounds": []}), encoding="utf-8")
        with self.assertRaises(remote.RemoteError):
            remote.import_sfx_kit(kit, library_root=self.root)


if __name__ == "__main__":
    unittest.main()
