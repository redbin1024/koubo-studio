"""逐条入场动效：每种都要真的画出来，位置与版式要落在它自己该在的地方。"""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults  # noqa: E402
from caption_layer import CaptionLayer  # noqa: E402
from workflow.caption_plan import ANIMS  # noqa: E402


def build_layer(directory, body: str, **captions):
    project = Path(directory)
    (project / "input").mkdir(parents=True, exist_ok=True)
    (project / "work").mkdir(parents=True, exist_ok=True)
    (project / "input" / "captions.srt").write_text(body, encoding="utf-8")
    cfg = apply_defaults({"canvas": {"width": 540, "height": 960, "fps": 30},
                          "input": {"subtitle": "captions.srt"},
                          "captions": {"font": "Noto Sans CJK SC Black", **captions}})
    return CaptionLayer(cfg, project)


def frame(layer: CaptionLayer, t: float) -> Image.Image:
    return layer.draw(Image.new("RGBA", (layer.W, layer.H), (0, 0, 0, 255)), t)


def ink(img: Image.Image) -> int:
    """画面上「不是底色」的像素数 —— 底是纯黑，字幕是白的，够区分了。"""
    return sum(1 for px in img.convert("RGB").getdata() if sum(px) > 60)


def rows_with_ink(img: Image.Image):
    w, h = img.size
    pix = img.convert("RGB").load()
    return [y for y in range(h) if any(sum(pix[x, y]) > 60 for x in range(0, w, 2))]


ONE = "1\n00:00:01,000 --> 00:00:03,000\n{@anim=%s}这句话得画出来\n"


class CaptionAnimTests(unittest.TestCase):
    def test_every_animation_draws_something(self):
        for anim in ANIMS:
            with self.subTest(anim=anim):
                with tempfile.TemporaryDirectory() as tmp:
                    layer = build_layer(tmp, ONE % anim)
                    mid = (1.0 + 3.0) / 2
                    self.assertGreater(ink(frame(layer, mid)), 200,
                                       f"{anim} 在片中没有画出内容")

    def test_animations_are_invisible_before_their_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            layer = build_layer(tmp, ONE % "pop")
            self.assertEqual(ink(frame(layer, 0.5)), 0)

    def test_layouts_place_the_text_in_different_bands(self):
        bands = {}
        for layout in ("bottom", "center", "top"):
            with tempfile.TemporaryDirectory() as tmp:
                layer = build_layer(tmp, ONE % "fade", layout=layout)
                rows = rows_with_ink(frame(layer, 2.0))
                self.assertTrue(rows, f"{layout} 没画出内容")
                bands[layout] = sum(rows) / len(rows) / layer.H
        self.assertGreater(bands["bottom"], 0.6)
        self.assertLess(bands["top"], 0.4)
        self.assertTrue(0.35 < bands["center"] < 0.65)

    def test_anim_ms_governs_how_long_the_entrance_takes(self):
        """入场没跑完时，画面上的字与settled 状态不同 —— 否则动效等于没做。"""
        with tempfile.TemporaryDirectory() as tmp:
            layer = build_layer(tmp, ONE % "rise", anim_ms=600)
            early, settled = ink(frame(layer, 1.12)), ink(frame(layer, 2.5))
            self.assertNotEqual(early, settled, "rise 的起步帧与落位帧一模一样")

    def test_karaoke_paints_progressively(self):
        with tempfile.TemporaryDirectory() as tmp:
            layer = build_layer(tmp, ONE % "karaoke")
            counts = [ink(frame(layer, 1.0 + 0.2 * i)) for i in range(1, 9)]
            self.assertGreater(counts[-1], 0)
            # 逐字上色会换颜色而不是换字数，但两个端点必然不同（起步只亮一个字）
            self.assertNotEqual(counts[0], counts[-1])


if __name__ == "__main__":
    unittest.main()
