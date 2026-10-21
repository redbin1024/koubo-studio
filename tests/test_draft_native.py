import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import draft_native  # noqa: E402


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _draft(**overrides):
    base = {
        "id": "draft-1",
        "duration": 2_000_000,
        "canvas_config": {"width": 1080, "height": 1920},
        "materials": {"videos": [{"id": "V1", "path": "/tmp/a.mp4"}], "audios": [], "texts": []},
        "tracks": [{"name": "video", "type": "video", "segments": [
            {"material_id": "V1", "target_timerange": {"start": 0, "duration": 2_000_000}},
        ]}],
    }
    base.update(overrides)
    return base


class DraftNativeTests(unittest.TestCase):
    def test_file_order_matches_platform(self):
        expected = ("draft_info.json", "draft_content.json") if sys.platform == "darwin" \
            else ("draft_content.json", "draft_info.json")
        self.assertEqual(draft_native.file_order(), expected)

    def test_active_path_falls_back_to_the_other_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "draft_content.json", _draft())
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                self.assertEqual(draft_native.active_path(root).name, "draft_content.json")
                self.assertEqual(draft_native.twin_path(root).name, "draft_info.json")

    def test_read_plaintext_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "draft_content.json", _draft())
            data, meta = draft_native.read_draft(root)
            self.assertEqual(data["id"], "draft-1")
            self.assertEqual(meta["format"], "json")
            self.assertFalse(meta["codec"])

    def test_read_encrypted_without_bridge_says_how_to_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "draft_info.json").write_text("A" * 64, encoding="utf-8")
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")), \
                 patch.object(draft_native, "probe",
                              return_value={"available": False, "hint": "跑 setup"}):
                with self.assertRaises(draft_native.DraftEncrypted) as ctx:
                    draft_native.read_draft(root)
            self.assertIn("setup", str(ctx.exception))

    def test_read_encrypted_uses_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "draft_info.json").write_text("A" * 64, encoding="utf-8")
            content = _draft()
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")), \
                 patch.object(draft_native, "probe",
                              return_value={"available": True, "python": "/fake/python",
                                            "version": "0.5.0"}), \
                 patch.object(draft_native, "_run_bridge",
                              return_value={"content": content, "format": "jianying-native",
                                            "path": str(root / "draft_info.json")}) as bridge:
                data, meta = draft_native.read_draft(root)
            self.assertEqual(data["id"], "draft-1")
            self.assertTrue(meta["codec"])
            self.assertEqual(meta["format"], "jianying-native")
            self.assertEqual(bridge.call_args[0][1][0], "read")

    def test_sync_twin_writes_plaintext_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "draft_info.json"
            twin = root / "draft_content.json"
            _write(active, _draft(id="new"))
            _write(twin, _draft(id="old"))
            now = 1_700_000_000
            os.utime(active, (now + 10, now + 10))
            os.utime(twin, (now, now))
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                result = draft_native.sync_twin(root)
            self.assertTrue(result["written"])
            self.assertEqual(json.loads(twin.read_text(encoding="utf-8"))["id"], "new")
            self.assertTrue(Path(result["backup"]).is_file())
            self.assertIn(".koubo-backups", result["backup"])
            self.assertEqual(json.loads(Path(result["backup"]).read_text(encoding="utf-8"))["id"],
                             "old")

    def test_sync_auto_takes_the_newer_side(self):
        """真实案例：行距修复只写了 draft_content，draft_info 还是旧的。

        自动方向必须按 mtime 走，不能盲信“活动文件”，否则会把修好的覆盖回旧值。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "draft_info.json"
            twin = root / "draft_content.json"
            _write(active, _draft(id="old"))
            _write(twin, _draft(id="newer"))
            now = 1_700_000_000
            os.utime(active, (now, now))
            os.utime(twin, (now + 30, now + 30))
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                result = draft_native.sync_twin(root)
            self.assertTrue(result["written"])
            self.assertEqual(result["from"], "draft_content.json")
            self.assertEqual(json.loads(active.read_text(encoding="utf-8"))["id"], "newer")

    def test_sync_explicit_active_overwrites_newer_twin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "draft_info.json"
            twin = root / "draft_content.json"
            _write(active, _draft(id="from-active"))
            _write(twin, _draft(id="from-twin"))
            now = 1_700_000_000
            os.utime(active, (now, now))
            os.utime(twin, (now + 30, now + 30))
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                result = draft_native.sync_twin(root, source="active")
            self.assertEqual(result["from"], "draft_info.json")
            self.assertEqual(json.loads(twin.read_text(encoding="utf-8"))["id"], "from-active")

    def test_sync_refuses_ambiguous_timestamps_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "draft_info.json"
            twin = root / "draft_content.json"
            _write(active, _draft(id="A"))
            _write(twin, _draft(id="B"))
            now = 1_700_000_000
            os.utime(active, (now, now))
            os.utime(twin, (now, now))
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                with self.assertRaises(draft_native.DraftNativeError):
                    draft_native.sync_twin(root)
                forced = draft_native.sync_twin(root, force=True)
            self.assertTrue(forced["written"])
            self.assertEqual(json.loads(twin.read_text(encoding="utf-8"))["id"], "A")

    def test_sync_refuses_to_rewrite_encrypted_target_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "draft_info.json"
            twin = root / "draft_content.json"
            _write(active, _draft(id="plain"))
            twin.write_text("A" * 64, encoding="utf-8")
            now = 1_700_000_000
            os.utime(active, (now + 30, now + 30))
            os.utime(twin, (now, now))
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                with self.assertRaises(draft_native.DraftNativeError):
                    draft_native.sync_twin(root, source="active")
                forced = draft_native.sync_twin(root, source="active", force=True)
            self.assertTrue(forced["written"])
            self.assertEqual(json.loads(twin.read_text(encoding="utf-8"))["id"], "plain")

    def test_ensure_twin_uses_the_newer_side_in_both_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "draft_info.json", root / "draft_content.json"
            _write(a, _draft(id="A"))
            _write(b, _draft(id="B"))
            now = 1_700_000_000
            os.utime(a, (now + 10, now + 10))
            os.utime(b, (now, now))
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")):
                draft_native.ensure_twin(root)
                self.assertEqual(json.loads(b.read_text(encoding="utf-8"))["id"], "A")
                # 反向：旧的那份被改新后，应跟着它走
                _write(b, _draft(id="C"))
                os.utime(b, (now + 20, now + 20))
                draft_native.ensure_twin(root)
            self.assertEqual(json.loads(a.read_text(encoding="utf-8"))["id"], "C")

    def test_write_all_updates_both_plaintext_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("draft_info.json", "draft_content.json"):
                _write(root / name, _draft(id="before"))
            draft_native.write_all(root, _draft(id="after"))
            for name in ("draft_info.json", "draft_content.json"):
                self.assertEqual(json.loads((root / name).read_text(encoding="utf-8"))["id"],
                                 "after")

    def test_write_all_refuses_two_encrypted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("draft_info.json", "draft_content.json"):
                (root / name).write_text("A" * 64, encoding="utf-8")
            with self.assertRaises(draft_native.DraftEncrypted):
                draft_native.write_all(root, _draft())

    def test_basic_doctor_flags_dangling_material_reference(self):
        broken = _draft()
        broken["tracks"][0]["segments"][0]["material_id"] = "MISSING"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "draft_content.json", broken)
            with patch.object(draft_native, "probe",
                              return_value={"available": False, "hint": "跑 setup"}):
                report = draft_native.doctor(root)
            self.assertEqual(report["source"], "basic")
            self.assertFalse(report["ok"])
            self.assertTrue(any("MISSING" in e for e in report["errors"]))

    def test_basic_doctor_warns_on_missing_media_and_twin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "draft_content.json", _draft())
            with patch.object(draft_native, "probe",
                              return_value={"available": False, "hint": "跑 setup"}):
                report = draft_native.doctor(root)
            self.assertTrue(report["ok"], report["errors"])
            joined = " ".join(report["warnings"])
            self.assertIn("素材文件缺失", joined)
            self.assertIn("明文副本", joined)

    def test_env_override_is_the_first_bridge_candidate(self):
        fake = str(Path(tempfile.gettempdir()) / "fake-jytool-python")
        with patch.dict(os.environ, {"KOUBO_JYTOOL_PYTHON": fake}):
            self.assertEqual(str(draft_native._candidate_pythons()[0]), fake)

    def test_doctor_unavailable_for_encrypted_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "draft_info.json").write_text("A" * 64, encoding="utf-8")
            with patch.object(draft_native, "file_order",
                              return_value=("draft_info.json", "draft_content.json")), \
                 patch.object(draft_native, "probe",
                              return_value={"available": False, "hint": "跑 setup"}):
                report = draft_native.doctor(root)
            self.assertEqual(report["source"], "unavailable")
            self.assertIsNone(report["ok"])

    def test_verify_native_draft_checks_plaintext_pair(self):
        import verify

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("draft_info.json", "draft_content.json"):
                _write(root / name, _draft())
            checks = []
            with patch.object(draft_native, "probe",
                              return_value={"available": False, "hint": "跑 setup"}):
                verify.check_native_draft(
                    root, lambda name, status, detail="": checks.append(
                        (name, status, detail)))
        got = {c[0]: c for c in checks}
        self.assertTrue(got["draft-file"][1])
        self.assertIn("两份内容一致", got["draft-file"][2])
        # 没有桥：深度诊断如实记 unchecked，不冒充 pass
        self.assertIsNone(got["draft-doctor"][1])

    def test_verify_native_draft_missing_dir_is_unchecked(self):
        import verify

        checks = []
        verify.check_native_draft(
            Path(tempfile.gettempdir()) / "definitely-missing-draft",
            lambda name, status, detail="": checks.append((name, status, detail)))
        self.assertEqual({c[0]: c[1] for c in checks},
                         {"draft-file": None, "draft-doctor": None})


if __name__ == "__main__":
    unittest.main()
