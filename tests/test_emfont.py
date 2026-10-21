import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import emfont  # noqa: E402


def response(payload, content_type="application/json", status=200):
    return status, content_type, json.dumps(payload, ensure_ascii=False).encode("utf-8")


class NormalizeTests(unittest.TestCase):
    def test_normalize_list_shape(self):
        font = emfont.normalize_font({
            "id": "jfOpenHuninn", "name": "jf open 粉圓", "weight": [400, 700],
            "name_zh": "粉圓", "category": "fantasy", "tags": ["圓體"],
            "family": "jf open 粉圓", "license": "OFL-1.1",
        })
        self.assertEqual(font["id"], "jfOpenHuninn")
        self.assertEqual(font["name"], "粉圓")
        self.assertEqual(font["weights"], [400, 700])
        self.assertEqual(font["tags"], ["圓體"])

    def test_normalize_info_shape(self):
        font = emfont.normalize_font({
            "name": {"zh": "辰宇落雁體", "en": "Chenyuluoyan", "original": "辰宇落雁體"},
            "tag": ["手寫"], "weight": [400], "license": "OFL-1.1",
            "description": "手寫風格",
        })
        self.assertEqual(font["name"], "辰宇落雁體")
        self.assertEqual(font["name_en"], "Chenyuluoyan")
        self.assertEqual(font["license"], "OFL-1.1")


class RequestTests(unittest.TestCase):
    def test_list_fonts_parses_and_skips_broken_rows(self):
        payload = [
            {"id": "a", "name": "A", "weight": [400]},
            {"id": "", "name": "broken"},
            {"id": "b", "name": "B", "weight": ["700"]},
        ]
        with mock.patch.object(emfont, "_request", return_value=response(payload)):
            rows = emfont.list_fonts()
        self.assertEqual([row["id"] for row in rows], ["a", "b"])

    def test_generate_font_posts_words_and_returns_locations(self):
        captured = {}

        def fake(url, *, method="GET", body=None, timeout=20.0):
            captured.update({"url": url, "method": method, "body": body})
            return response({"status": "success", "name": "子集",
                             "location": ["https://cdn.test/font.ttf"]})

        with mock.patch.object(emfont, "_request", side_effect=fake):
            result = emfont.generate_font("abc", "你好世界", weight=700)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["words"], "你好世界")
        self.assertEqual(captured["body"]["format"], "ttf")
        self.assertEqual(result["locations"], ["https://cdn.test/font.ttf"])

    def test_generate_font_rejects_failed_status(self):
        with mock.patch.object(emfont, "_request",
                               return_value=response({"status": "error",
                                                      "message": "缺字"})):
            with self.assertRaises(emfont.EmfontError):
                emfont.generate_font("abc", "你好")

    def test_html_response_is_a_clear_error(self):
        with mock.patch.object(emfont, "_request",
                               return_value=(200, "text/html", b"<html>down</html>")):
            with self.assertRaises(emfont.EmfontError) as ctx:
                emfont.list_fonts()
        self.assertIn("服务可能暂时不可用", str(ctx.exception))

    def test_download_rejects_html(self):
        class FakeResponse:
            def __init__(self, data, ctype):
                self.data, self.pos = data, 0
                self.headers = {"Content-Type": ctype}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                chunk = self.data[self.pos:self.pos + size]
                self.pos += len(chunk)
                return chunk

        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeResponse(b"<html>not a font</html>", "text/html")
            with mock.patch.object(emfont.urllib.request, "urlopen", return_value=fake):
                with self.assertRaises(emfont.EmfontError):
                    emfont.download("https://cdn.test/x.ttf", Path(tmp) / "x.ttf")


class CatalogTests(unittest.TestCase):
    def test_live_catalog_is_cached(self):
        payload = [{"id": "a", "name": "A", "weight": [400]}]
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "catalog.json"
            with mock.patch.object(emfont, "CATALOG_FILE", cache), \
                 mock.patch.object(emfont, "_request", return_value=response(payload)) as req:
                first = emfont.catalog()
                second = emfont.catalog()
            self.assertFalse(first["from_cache"])
            self.assertTrue(second["from_cache"])
            self.assertEqual(req.call_count, 1)
            self.assertTrue(cache.is_file())

    def test_stale_cache_survives_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "catalog.json"
            cache.write_text(json.dumps({"fetched_at": 0,
                                         "fonts": [{"id": "old", "name": "Old"}]}),
                             encoding="utf-8")
            with mock.patch.object(emfont, "CATALOG_FILE", cache), \
                 mock.patch.object(emfont, "list_fonts",
                                   side_effect=emfont.EmfontError("down")):
                data = emfont.catalog()
            self.assertTrue(data["stale"])
            self.assertEqual(data["fonts"][0]["id"], "old")
            self.assertIn("down", data["warning"])

    def test_info_cache_hits_without_network(self):
        cached = {"abc": {"fetched_at": 9_999_999_999,
                          "info": {"id": "abc", "name": "Cached", "license": "OFL-1.1"}}}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "info.json"
            cache.write_text(json.dumps(cached), encoding="utf-8")
            with mock.patch.object(emfont, "INFO_FILE", cache), \
                 mock.patch.object(emfont, "font_info") as info:
                row = emfont.font_info_cached("abc")
        self.assertEqual(row["name"], "Cached")
        info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
