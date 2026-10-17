"""剪映资源的解析（写错要炸）与本地 BGM（长度/格式/可复现）。"""
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults  # noqa: E402
from make_jianying_draft import resolve_fx  # noqa: E402
import make_bgm  # noqa: E402


MAIN = [("seg-1", 0.0, 10.0), ("seg-2", 10.0, 22.5), ("seg-3", 22.5, 40.0)]


def config(**fx):
    return apply_defaults({"duration": 40.0,
                           "jianying_fx": {"enabled": True, **fx}})


class ResolveFxTests(unittest.TestCase):
    def test_disabled_means_no_calls(self):
        cfg = apply_defaults({"duration": 40.0})
        self.assertEqual(resolve_fx(cfg, MAIN, 40.0), ([], []))

    def test_effect_filter_sfx_and_transition_resolve(self):
        cfg = config(
            effects=[{"name": "90s画质", "at": 1.0, "dur": 1.5}],
            filters=[{"name": "ABG"}],
            transitions=[{"at": 22.5, "name": "上移", "dur": 0.4}],
            sfx=[{"name": "回音", "at": 5.0, "dur": 0.8, "volume": 0.5}])
        plans, errors = resolve_fx(cfg, MAIN, 40.0)
        self.assertEqual(errors, [])
        kinds = [p["kind"] for p in plans]
        self.assertEqual(kinds, ["effect", "filter", "transition", "sfx"])
        self.assertTrue(plans[1]["full"], "不写 dur 的滤镜应当覆盖到片尾")
        # 转场挂在**切点前**那一段的尾巴上（剪映里就是这么一条），不是后一段
        self.assertEqual(plans[2]["segment_id"], "seg-2",
                         "at=22.5 是 seg-2 的尾/seg-3 的头，转场归前一段")

    def test_effect_can_be_given_by_resource_id(self):
        cfg = config(effects=[{"resource_id": "6760946510910722564", "at": 0.0, "dur": 1.0}])
        plans, errors = resolve_fx(cfg, MAIN, 40.0)
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]["resource_id"], "6760946510910722564")

    def test_errors_are_collected_before_anything_is_written(self):
        cfg = config(
            effects=[{"at": 0, "dur": 1}],                         # 没名字也没 id
            filters=[{"name": "ABG", "dur": 99}],                  # 越界
            transitions=[{"at": 7.0, "name": "叠化"}],              # 不是切点
            sfx=[{"name": "回音", "at": 39.5, "dur": 2.0}])        # 越界
        plans, errors = resolve_fx(cfg, MAIN, 40.0)
        self.assertEqual(plans, [])
        joined = " / ".join(errors)
        for fragment in ("name 与 resource_id", "越界", "不是主轨切点"):
            self.assertIn(fragment, joined)


class LocalBgmTests(unittest.TestCase):
    def build(self, tmp: Path, mood="warm", duration=3.0):
        project = tmp / "p"
        (project / "work").mkdir(parents=True)
        cfg = apply_defaults({"duration": duration,
                              "audio": {"bgm": {"enabled": True, "mood": mood}}})
        return make_bgm.build(cfg, project), project / "work" / "bgm.wav"

    def test_writes_48k_stereo_with_exact_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            info, path = self.build(Path(tmp), duration=3.0)
            with wave.open(str(path), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getframerate(),
                                  wav.getsampwidth()), (2, 48000, 2))
                self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 3.0, places=3)
            self.assertEqual(info["mood"], "warm")

    def test_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, first = self.build(Path(tmp) / "a")
            _, second = self.build(Path(tmp) / "b")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_unknown_mood_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "未知 BGM 情绪"):
                self.build(Path(tmp), mood="epic")


if __name__ == "__main__":
    unittest.main()
