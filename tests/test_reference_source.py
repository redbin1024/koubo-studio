import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow.reference_source import (  # noqa: E402
    ReferenceSourceError, _clean_url, detect_platform, extract_url, load_cookie,
    normalize_item, parse_aweme_id, parse_share_html, prepare_reference,
)


def sample_item(**overrides):
    item = {
        "aweme_id": "7525538910311632128",
        "desc": "一条参考片 #口播 #测试",
        "create_time": 1752192000,
        "author": {"nickname": "参考作者", "unique_id": "ref_author"},
        "music": {"title": "参考 BGM", "author": "作曲"},
        "statistics": {"digg_count": 12, "comment_count": 3,
                       "share_count": 2, "collect_count": 7},
        "video": {
            "duration": 12345,
            "play_addr": {"url_list": ["https://x.test/aweme/v1/playwm/?video_id=1"]},
            "download_addr": {"url_list": ["https://x.test/aweme/v1/playwm/?video_id=2"]},
            "cover": {"url_list": ["https://x.test/cover.jpg"]},
        },
    }
    item.update(overrides)
    return item


def share_html(item):
    payload = {"loaderData": {"video_layout": None,
                              "video_(id)/page": {"videoInfoRes": {"item_list": [item]}}}}
    return ("<html><script>window._ROUTER_DATA = "
            + json.dumps(payload, ensure_ascii=False) + "</script></html>")


class LinkTests(unittest.TestCase):
    def test_extract_url_from_share_text(self):
        text = "7.9 复制打开抖音，看看【作者的作品】 https://v.douyin.com/drIPtQ_WPWY/ 复制此链接"
        self.assertEqual(extract_url(text), "https://v.douyin.com/drIPtQ_WPWY/")

    def test_extract_url_returns_none_for_plain_text(self):
        self.assertIsNone(extract_url("没有链接的分享文案"))

    def test_platform_and_aweme_id(self):
        self.assertEqual(detect_platform("https://v.douyin.com/x/"), "douyin")
        self.assertEqual(detect_platform("https://www.iesdouyin.com/share/video/1/"), "douyin")
        self.assertEqual(detect_platform("https://example.com/a"), "url")
        self.assertEqual(parse_aweme_id("https://www.douyin.com/video/7525082444551310602?x=1"),
                         "7525082444551310602")
        self.assertEqual(parse_aweme_id("https://www.douyin.com/discover?modal_id=7525082444551310602"),
                         "7525082444551310602")
        self.assertIsNone(parse_aweme_id("https://v.douyin.com/x/"))

    def test_resolved_url_drops_tracking_parameters(self):
        self.assertEqual(_clean_url("https://www.iesdouyin.com/share/video/1/?did=abc&share_sign=x"),
                         "https://www.iesdouyin.com/share/video/1/")

    def test_cookie_file_and_header(self):
        self.assertEqual(load_cookie("sessionid=abc; ttwid=def"), "sessionid=abc; ttwid=def")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text(
                "# Netscape HTTP Cookie File\n"
                ".douyin.com\tTRUE\t/\tFALSE\t0\tsessionid\tabc\n"
                ".example.com\tTRUE\t/\tFALSE\t0\tother\tno\n",
                encoding="utf-8")
            self.assertEqual(load_cookie(str(path)), "sessionid=abc")


class SharePageTests(unittest.TestCase):
    def test_parse_share_html_normalizes_metadata(self):
        data = parse_share_html(share_html(sample_item()))
        self.assertEqual(data["aweme_id"], "7525538910311632128")
        self.assertEqual(data["meta"]["author"], "参考作者")
        self.assertEqual(data["meta"]["duration"], 12.345)
        self.assertEqual(data["meta"]["stats"]["likes"], 12)
        self.assertEqual(data["meta"]["hashtags"], ["口播", "测试"])
        self.assertFalse(data["is_image_post"])

    def test_play_urls_prefer_unwatermarked_and_keep_fallback(self):
        data = normalize_item(sample_item())
        self.assertEqual(data["play_urls"][0], "https://x.test/aweme/v1/play/?video_id=1")
        self.assertTrue(any("/playwm/" in url for url in data["play_urls"]))
        self.assertGreaterEqual(len(data["play_urls"]), 2)

    def test_image_post_is_detected(self):
        item = sample_item(video={"duration": 0, "images": [{"url_list": ["https://x/1.jpg"]}]})
        item.pop("video")
        item["images"] = [{"url_list": ["https://x/1.jpg"]}]
        data = parse_share_html(share_html(item))
        self.assertTrue(data["is_image_post"])
        self.assertEqual(data["play_urls"], [])

    def test_page_without_router_data_explains_next_step(self):
        with self.assertRaises(ReferenceSourceError) as ctx:
            parse_share_html("<html><body>_$jsvmprt verify</body></html>")
        self.assertIn("Cookie", str(ctx.exception))

    def test_empty_item_list_is_an_error(self):
        payload = {"loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": []}}}}
        html = "<script>window._ROUTER_DATA = " + json.dumps(payload) + "</script>"
        with self.assertRaises(ReferenceSourceError):
            parse_share_html(html)


class PrepareReferenceTests(unittest.TestCase):
    def test_prepare_local_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "ref.mp4"
            video.write_bytes(b"x")
            prepared = prepare_reference(str(video), Path(tmp) / "work")
            self.assertEqual(prepared["video"], video.resolve())
            self.assertIsNone(prepared["teardown"])

    def test_prepare_profile_directory_reuses_teardown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "reference"
            (root / "douyin").mkdir(parents=True)
            video = root / "douyin" / "douyin.mp4"
            video.write_bytes(b"x")
            (root / "source.json").write_text(json.dumps({"video": str(video)}), encoding="utf-8")
            (root / "teardown.json").write_text(json.dumps({"card": None}), encoding="utf-8")
            (root / "reference-profile.json").write_text("{}", encoding="utf-8")
            prepared = prepare_reference(str(root), Path(tmp) / "work")
            self.assertTrue(prepared["reused"])
            self.assertEqual(prepared["teardown"], {"card": None})
            self.assertEqual(prepared["video"], video)

    def test_missing_file_is_an_error(self):
        with self.assertRaises(ReferenceSourceError):
            prepare_reference("/definitely/not/here.mp4", "/tmp")


if __name__ == "__main__":
    unittest.main()
