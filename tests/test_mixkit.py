import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class MixkitParseTests(unittest.TestCase):
    def test_parse_video_jsonld(self):
        from mixkit import _parse_video
        page = ('<script type="application/ld+json">' + json.dumps({
            "@type": "VideoObject", "name": "Coffee pour",
            "description": "A cup", "duration": "PT12S",
            "contentUrl": "https://assets.mixkit.co/videos/41859/41859-1080.mp4",
            "thumbnailUrl": "https://assets.mixkit.co/videos/41859/41859-thumb-360-0.jpg",
            "license": "https://mixkit.co/license/#videoFree",
            "url": "https://mixkit.co/free-stock-video/coffee/",
        }) + "</script>")
        items = _parse_video(page)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "41859")
        self.assertTrue(items[0]["url"].endswith("-1080.mp4"))

    def test_parse_music_jsonld(self):
        from mixkit import _parse_music
        page = ('<script type="application/ld+json">' + json.dumps({
            "@type": "ItemList", "itemListElement": [{
                "@type": "MusicRecording", "name": "Serene View", "genre": "Chillout",
                "byArtist": "Arulo", "duration": "PT1M54S",
                "url": "https://assets.mixkit.co/music/443/443.mp3",
            }],
        }) + "</script>")
        items = _parse_music(page)
        self.assertEqual(items[0]["id"], "443")
        self.assertEqual(items[0]["artist"], "Arulo")

    def test_parse_sfx_html(self):
        from mixkit import _parse_sfx
        page = ('<div data-audio-player-preview-url-value="https://assets.mixkit.co/sfx/1-preview.mp3" '
                'data-audio-player-item-id-value="715"></div><h2>Clown horn</h2>')
        items = _parse_sfx(page)
        self.assertEqual(items[0]["id"], "715")
        self.assertEqual(items[0]["title"], "Clown horn")


if __name__ == "__main__":
    unittest.main()
