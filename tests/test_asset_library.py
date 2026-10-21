from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import asset_library as lib  # noqa: E402


def write(path: Path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def project(tmp: Path, *, broll_source: str | None = None) -> Path:
    p = tmp / "proj"
    (p / "input").mkdir(parents=True)
    (p / "work").mkdir(parents=True)
    write(p / "input" / "video.mp4")
    write(p / "work" / "bgm.wav")
    (p / "input" / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:03,000\n城市通勤路上的营养餐\n\n"
        "2\n00:00:03,000 --> 00:00:06,000\n那一句放心我们一直都在\n", encoding="utf-8")
    cfg = {
        "name": "demo", "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "duration": 6.0,
        "input": {"video": "video.mp4", "subtitle": "captions.srt"},
        "captions": {"font": "Noto Sans CJK SC"},
        "audio": {"bgm": {"enabled": True}, "bgm_volume": 0.12},
        "sfx": {"events": [{"t": 1.0, "clip": "pop"}]},
    }
    if broll_source:
        cfg["broll"] = {"enabled": True, "items": [{
            "cue": 2, "keyword": "放心", "source": broll_source,
            "in": 0.0, "dur": 1.5}]}
    (p / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "lib"
        lib.init_library(self.root, seed=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_layout(self):
        self.assertTrue((self.root / "registry.jsonl").is_file())
        for rel in ("audio/bgm", "audio/sfx", "video/broll", "graphics/stickers"):
            self.assertTrue((self.root / rel).is_dir())

    def test_ingest_search_and_resolve(self):
        src = write(Path(self.tmp.name) / "city.mp4", b"fake-video")
        entry = lib.ingest_file(
            src, kind="broll", license_key="CC0-1.0", library_root=self.root,
            title="城市夜景", tags="city,night,street", mood="calm",
            source_url="https://example.com/city")
        self.assertEqual(entry["id"], "broll/city")
        self.assertTrue((self.root / entry["path"]).is_file())
        self.assertTrue(lib.sidecar_path(self.root / entry["path"]).is_file())
        entries = lib.load_registry(self.root)
        hits = lib.search(entries, "城市 夜景", kinds=["broll"], library_root=self.root)
        self.assertEqual(hits[0]["entry"]["id"], "broll/city")
        got = lib.resolve_ref("asset:broll/city", library_root=self.root)
        self.assertEqual(Path(got["path"]), (self.root / entry["path"]).resolve())

    def test_license_is_required(self):
        src = write(Path(self.tmp.name) / "x.mp4")
        with self.assertRaises(lib.AssetError):
            lib.ingest_file(src, kind="broll", license_key="unknown", library_root=self.root)
        entry = lib.ingest_file(src, kind="broll", license_key="unknown",
                                library_root=self.root, allow_unknown=True)
        self.assertEqual(entry["license"], "unknown")

    def test_duplicate_content_reuses_entry(self):
        src = write(Path(self.tmp.name) / "night.mp4")
        first = lib.ingest_file(src, kind="broll", license_key="CC0-1.0",
                                library_root=self.root, title="Night")
        second = lib.ingest_file(src, kind="broll", license_key="CC0-1.0",
                                 library_root=self.root, title="Again")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(lib.load_registry(self.root)), 1)

    def test_scan_marks_unknown_then_set_license(self):
        write(self.root / "audio" / "sfx" / "custom.wav")
        got = lib.scan_library(self.root)
        self.assertEqual(got["added"], ["sfx/custom"])
        entry = lib.load_registry(self.root)[0]
        self.assertEqual(entry["license"], "unknown")
        checked = lib.verify_entries([entry], library_root=self.root)
        self.assertEqual(checked["counts"]["unchecked"], 1)
        strict = lib.verify_entries([entry], library_root=self.root, strict=True)
        self.assertEqual(strict["counts"]["fail"], 1)
        fixed = lib.apply_license(entry, "CC0-1.0")
        lib.save_registry([fixed], self.root)
        self.assertEqual(
            lib.verify_entries(lib.load_registry(self.root), library_root=self.root)["counts"]["pass"],
            1)

    def test_verify_missing_and_hash_mismatch(self):
        src = write(Path(self.tmp.name) / "x.wav", b"one")
        entry = lib.ingest_file(src, kind="sfx", license_key="CC0-1.0",
                                library_root=self.root)
        path = self.root / entry["path"]
        path.write_bytes(b"two")
        got = lib.verify_entries(lib.load_registry(self.root), library_root=self.root)
        self.assertEqual(got["counts"]["fail"], 1)
        self.assertTrue(any("sha256" in r for r in got["issues"][0]["reasons"]))
        path.unlink()
        got = lib.verify_entries(lib.load_registry(self.root), library_root=self.root)
        self.assertEqual(got["counts"]["fail"], 1)

    def test_stats(self):
        src = write(Path(self.tmp.name) / "x.mp3")
        lib.ingest_file(src, kind="bgm", license_key="CC0-1.0",
                        library_root=self.root, tags="calm")
        got = lib.stats(lib.load_registry(self.root))
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["by_kind"]["bgm"], 1)


class ProjectAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "lib"
        lib.init_library(self.root, seed=True)
        self.project = project(self.base)
        write(self.base / "city.mp4", b"fake-video")
        self.broll = lib.ingest_file(
            self.base / "city.mp4", kind="broll", license_key="CC0-1.0",
            library_root=self.root, title="City night", tags="city,night",
            source_url="https://example.com/city")

    def tearDown(self):
        self.tmp.cleanup()

    def test_audit_writes_manifest_and_outputs(self):
        cfg = json.loads((self.project / "config.json").read_text(encoding="utf-8"))
        cfg["broll"] = {"enabled": True, "items": [{
            "cue": 2, "keyword": "放心", "source": f"asset:{self.broll['id']}",
            "in": 0.0, "dur": 1.5}]}
        cfg["assets"] = {"library": str(self.root)}
        (self.project / "config.json").write_text(json.dumps(cfg, ensure_ascii=False),
                                                  encoding="utf-8")
        got = lib.audit_project(self.project, library_root=self.root)
        self.assertIn("items", got)
        self.assertTrue((self.project / "work" / "asset-manifest.json").is_file())
        self.assertTrue((self.project / "output" / "asset-licenses.csv").is_file())
        self.assertTrue((self.project / "output" / "CREDITS.md").is_file())
        broll = next(x for x in got["items"] if x["kind"] == "broll")
        self.assertEqual(broll["id"], self.broll["id"])
        self.assertEqual(broll["status"], "pass")
        source = next(x for x in got["items"] if x["kind"] == "source")
        self.assertEqual(source["status"], "unchecked")
        self.assertIn(got["overall"], ("unchecked", "fail"))

    def test_broll_asset_ref(self):
        from workflow import broll
        cfg = {"assets": {"library": str(self.root)},
               "broll": {"enabled": True, "items": [{
                   "cue": 2, "keyword": "放心", "source": f"asset:{self.broll['id']}",
                   "in": 0.0, "dur": 1.5}]}}
        cues = [{"index": 2, "start": 3.0, "end": 6.0, "lines": ["那一句[[放心]]我们"]}]
        plans, errors = broll.resolve(cfg, self.project, cues)
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]["start"], 3.12)
        self.assertTrue(Path(plans[0]["source"]).is_file())

    def test_preflight_reports_bad_asset_ref(self):
        from workflow.preflight import check
        cfg = json.loads((self.project / "config.json").read_text(encoding="utf-8"))
        cfg["broll"] = {"enabled": True, "items": [{
            "cue": 2, "keyword": "放心", "source": "asset:broll/does-not-exist",
            "in": 0.0, "dur": 1.5}]}
        cfg["assets"] = {"library": str(self.root)}
        # preflight 只需要片长；假 mp4 没法 ffprobe，去掉 input.video 让它走 duration
        cfg["input"].pop("video", None)
        (self.project / "config.json").write_text(json.dumps(cfg, ensure_ascii=False),
                                                  encoding="utf-8")
        (self.project / "work" / "bgm.wav").unlink(missing_ok=True)
        got = check(self.project)
        self.assertFalse(got["ok"])
        self.assertTrue(any("does-not-exist" in e for e in got["errors"]))

    def test_suggest_returns_explainable_hits(self):
        got = lib.suggest(self.project, 1, library_root=self.root)
        self.assertEqual(got["cue"]["index"], 1)
        self.assertTrue(got["tokens"])
        self.assertTrue(all(h["reasons"] for h in got["suggestions"]))


if __name__ == "__main__":
    unittest.main()
