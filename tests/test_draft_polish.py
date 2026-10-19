import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class DraftPolishTests(unittest.TestCase):
    def test_line_spacing_is_written_to_every_text_material(self):
        from make_jianying_draft import set_text_line_spacing

        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp)
            (draft / "draft_content.json").write_text(json.dumps({
                "materials": {"texts": [
                    {"content": "{}", "line_spacing": 0.02},
                    {"content": "{}", "line_spacing": 0.02},
                ]}
            }), encoding="utf-8")
            set_text_line_spacing(draft, 0.22)
            data = json.loads((draft / "draft_content.json").read_text())
            self.assertEqual([t["line_spacing"] for t in data["materials"]["texts"]],
                             [0.22, 0.22])

    def test_sticker_is_a_transparent_full_canvas_layer(self):
        from make_assets import _sticker_layer

        image = _sticker_layer(1080, 1920, {
            "icon": "heart", "x": 0.82, "y": 0.22,
            "size": 0.085, "color": "#B9824A"})
        self.assertEqual(image.size, (1080, 1920))
        bbox = image.getchannel("A").getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreater(bbox[0], 700)
        self.assertLess(bbox[2], 1000)


if __name__ == "__main__":
    unittest.main()
