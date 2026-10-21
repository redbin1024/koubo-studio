import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow import reference_vision as vision  # noqa: E402


def good_overview():
    return {"overview": {
        "hook": "前 3 秒用问题抓住人",
        "structure": "痛点→展示→对比→促单",
        "visual_style": "暖色、近景、白字黑边字幕",
        "rhythm": "平均 2.5 秒一刀",
        "audio": "口播在解释三个步骤",
        "why_it_works": ["问题具体", "对比明确", "结尾有行动"],
        "adaptation": ["保留前 3 秒的信息顺序"],
        "target_audience": "想学剪辑的人",
    }}


def good_shot(ident):
    return {
        "id": ident, "shot_size": "近景", "camera": "固定",
        "subject": "一个人", "action": "对着镜头说话",
        "action_phases": ["看向镜头", "开口"], "end_state": "settled",
        "scene": "室内", "lighting": "柔光", "on_screen_text": "无",
        "transition": "硬切", "hook_role": "钩子", "hidden_cut": False,
        "evidence": "左中右三格人物位置一致，只有口型变化", "confidence": 0.8,
    }


def api(payload, tokens=10):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": 5}}


class FakeTransport:
    """按提示词里的镜头 id 返回合法的分镜；可注入一次失败。"""

    def __init__(self, fail_batches=0):
        self.calls = []
        self.fail_batches = fail_batches
        self.batch_calls = 0

    def __call__(self, body, key):
        self.calls.append(body)
        text = json.dumps(body, ensure_ascii=False)
        if "全片拆解" in text:
            return api(good_overview())
        match = re.search(r"只返回这些镜头，顺序一致，不多不少：([^。]+)。", text)
        ids = [x.strip() for x in (match.group(1) if match else "").split(",") if x.strip()]
        self.batch_calls += 1
        if self.batch_calls <= self.fail_batches:
            return api({"shots": [{"id": "unknown", "shot_size": "近景"}]})
        return api({"shots": [good_shot(ident) for ident in ids]})


class ValidateTests(unittest.TestCase):
    def test_validate_overview_requires_the_core_fields(self):
        self.assertEqual(vision.validate_overview(good_overview())["structure"],
                         "痛点→展示→对比→促单")
        broken = good_overview()
        broken["overview"]["hook"] = ""
        with self.assertRaises(ValueError):
            vision.validate_overview(broken)

    def test_validate_shot_payload_rejects_bad_values(self):
        payload = {"shots": [good_shot("s01"), good_shot("s02")]}
        self.assertEqual(set(vision.validate_shot_payload(payload, ["s01", "s02"])),
                         {"s01", "s02"})

        for field, value in (("shot_size", "超广角"), ("end_state", "done"),
                             ("confidence", 1.5), ("evidence", "")):
            broken = {"shots": [dict(good_shot("s01"), **{field: value})]}
            with self.assertRaises(ValueError):
                vision.validate_shot_payload(broken, ["s01"])

    def test_validate_shot_payload_rejects_missing_and_unknown_ids(self):
        with self.assertRaises(ValueError):
            vision.validate_shot_payload({"shots": [good_shot("s01")]}, ["s01", "s02"])
        with self.assertRaises(ValueError):
            vision.validate_shot_payload({"shots": [good_shot("s09")]}, ["s01"])

    def test_parse_json_strips_code_fences(self):
        self.assertEqual(vision._parse_json('```json\n{"overview": {}}\n```'),
                         {"overview": {}})


class AnalyzeTests(unittest.TestCase):
    def _shots(self, root, count=4):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        frames = Path(root) / "frames"
        frames.mkdir(parents=True)
        shots = []
        for index in range(1, count + 1):
            rel = f"frames/strip-{index:02d}.jpg"
            Image.new("RGB", (48, 32), (40 * index, 60, 120)).save(Path(root) / rel)
            shots.append({"id": f"s{index:02d}", "index": index, "start": index - 1.0,
                          "end": float(index), "duration": 1.0, "strip": rel,
                          "strip_times": [index - 0.9, index - 0.5, index - 0.1],
                          "status": "ok"})
        return shots

    def test_analyze_returns_overview_and_every_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = self._shots(tmp)
            fake = FakeTransport()
            result = vision.analyze(shots, tmp, api_key="test", transport=fake,
                                    pacing={"shot_count": 4}, transcript="测试口播",
                                    meta={"title": "标题"})
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["overview"]["hook"], "前 3 秒用问题抓住人")
            self.assertEqual(set(result["shots"]), {"s01", "s02", "s03", "s04"})
            self.assertEqual(result["usage"]["prompt_tokens"], 30)  # 1 + 2 批
            self.assertEqual(len(fake.calls), 3)

    def test_invalid_batch_is_retried_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = self._shots(tmp, 2)
            fake = FakeTransport(fail_batches=1)
            result = vision.analyze(shots, tmp, api_key="test", transport=fake)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["warnings"], [])
            self.assertEqual(set(result["shots"]), {"s01", "s02"})

    def test_persistent_failure_marks_only_that_batch_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = self._shots(tmp, 2)
            fake = FakeTransport(fail_batches=2)
            result = vision.analyze(shots, tmp, api_key="test", transport=fake)
            self.assertEqual(result["status"], "partial")
            self.assertTrue(result["warnings"])
            self.assertTrue(result["shots"]["s01"].get("unchecked"))

    def test_missing_key_raises_instead_of_faking_analysis(self):
        with self.assertRaises(vision.VisionError):
            vision.analyze([{"id": "s01", "strip": "x", "status": "ok"}], "/tmp",
                           api_key="")


if __name__ == "__main__":
    unittest.main()
