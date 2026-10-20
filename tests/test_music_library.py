import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class MusicLibraryTests(unittest.TestCase):
    def test_scan_draft_music_and_search(self):
        from music_library import scan_drafts, search
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "demo"
            project.mkdir()
            (project / "draft_content.json").write_text(json.dumps({
                "materials": {"audios": [
                    {"type": "music", "music_id": "7377847594314287123",
                     "name": "企业形象进取创新", "duration": 130_000_000,
                     "category_name": "VLOG", "url": "https://example.com/a.m4a"},
                ]}
            }), encoding="utf-8")
            cache = root / "cache.json"
            result = scan_drafts([root], cache_path=cache, include_history=False)
            self.assertEqual(result["count"], 1)
            hits = search("企业", cache)
            self.assertEqual(hits[0]["music_id"], "7377847594314287123")

    def test_import_csv_merges_rows(self):
        from music_library import import_csv, find
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache.json"
            csv_path = root / "music.csv"
            csv_path.write_text(
                "music_id,title,duration_s,categories,url\n"
                "7176685873453500417,More of My Time (Lofi),136.53,VLOG,\n",
                encoding="utf-8")
            result = import_csv(csv_path, cache)
            self.assertEqual(result["count"], 1)
            row = find("7176685873453500417", cache)
            self.assertEqual(row["title"], "More of My Time (Lofi)")


    def test_tts_voice_changes_cache_identity(self):
        from tts import _line_path
        a = _line_path(Path('/tmp'), 1, "同一句", "-5%", "zh-CN-XiaoxiaoNeural")
        b = _line_path(Path('/tmp'), 1, "同一句", "-5%", "zh-CN-YunxiNeural")
        self.assertNotEqual(a.name, b.name)


if __name__ == "__main__":
    unittest.main()
