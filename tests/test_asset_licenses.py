import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import asset_licenses as lic  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(lic.normalize_license("CC0-1.0"), "CC0-1.0")
        self.assertEqual(lic.normalize_license("SIL OFL 1.1"), "OFL-1.1")
        self.assertEqual(lic.normalize_license("CC BY-NC 4.0"), "CC-BY-NC-4.0")
        self.assertEqual(lic.normalize_license("CC BY-SA 4.0"), "CC-BY-SA-4.0")
        self.assertEqual(lic.normalize_license("pixabay content license"),
                         "Pixabay-Content-License")
        self.assertEqual(lic.normalize_license("https://mixkit.co/license/#videoFree"),
                         "Mixkit-Free-License")
        self.assertEqual(lic.normalize_license("系统字体（仅本机渲染）"), "system-font")
        self.assertEqual(lic.normalize_license("免费商用（需核对）"), "custom-free")
        self.assertEqual(lic.normalize_license("没听说过的协议"), "unknown")

    def test_tiers(self):
        self.assertEqual(lic.license_tier("SIL OFL 1.1"), "permissive")
        self.assertEqual(lic.license_tier("CC BY-NC 4.0"), "restricted")
        self.assertEqual(lic.license_tier("系统字体"), "system")
        self.assertEqual(lic.license_tier("unknown"), "unknown")


class CheckTests(unittest.TestCase):
    def test_nc_fails_for_commercial(self):
        got = lic.check("CC-BY-NC-4.0", commercial=True)
        self.assertEqual(got["status"], "fail")
        self.assertTrue(any("不允许商业" in x for x in got["reasons"]))

    def test_nc_passes_for_non_commercial(self):
        got = lic.check("CC-BY-NC-4.0", commercial=False)
        self.assertEqual(got["status"], "unchecked")  # 还要署名

    def test_cc_by_needs_credits(self):
        self.assertEqual(lic.check("CC-BY-4.0")["status"], "unchecked")
        self.assertEqual(lic.check("CC-BY-4.0", attribution_exported=True)["status"], "pass")

    def test_unknown_is_unchecked_unless_strict(self):
        self.assertEqual(lic.check("unknown")["status"], "unchecked")
        self.assertEqual(lic.check("unknown", strict=True)["status"], "fail")

    def test_stale_check_is_unchecked(self):
        got = lic.check("CC0-1.0", checked_at="2020-01-01", now=date(2026, 10, 21))
        self.assertEqual(got["status"], "unchecked")
        self.assertTrue(any("365" in x for x in got["reasons"]))

    def test_snapshot_change_is_unchecked(self):
        got = lic.check("CC-BY-4.0", attribution_exported=True,
                        snapshot={"commercial": False, "checked_at": "2026-10-01"},
                        now=date(2026, 10, 21))
        self.assertEqual(got["status"], "unchecked")
        self.assertTrue(any("快照" in x for x in got["reasons"]))

    def test_platform_licenses_pass_commercial(self):
        for key in ("Pixabay-Content-License", "Mixkit-Free-License", "Pexels-License"):
            self.assertEqual(lic.check(key)["status"], "pass", key)


class FontLicenseTests(unittest.TestCase):
    def test_records_are_loaded(self):
        noto = lic.font_license_for("Noto Sans CJK SC")
        self.assertEqual(noto["id"], "OFL-1.1")
        self.assertEqual(noto["matched"], "record")
        self.assertFalse(noto["review_required"])

        douyin = lic.font_license_for("抖音美好体")
        self.assertEqual(douyin["id"], "OFL-1.1")

        ali = lic.font_license_for("阿里巴巴普惠体")
        self.assertEqual(ali["id"], "Alibaba-PuHuiTi")
        self.assertTrue(ali["review_required"])

    def test_unknown_font_is_conservative(self):
        info = lic.font_license_for("某不存在的标题体")
        self.assertEqual(info["id"], "unknown")
        self.assertEqual(info["matched"], "heuristic")

    def test_attribution_line(self):
        info = lic.license_info("CC-BY-4.0")
        line = lic.attribution_line("City", "Ann", info, "https://example.com/c")
        self.assertIn("City", line)
        self.assertIn("Ann", line)
        self.assertIn("CC BY 4.0", line)


if __name__ == "__main__":
    unittest.main()
