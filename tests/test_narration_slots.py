"""解说槽：只能从真实静音里留出来，旁白只能落在槽里，装在装不下时报错。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import apply_defaults  # noqa: E402
from merge_cut import narration_slots  # noqa: E402
from workflow.speech_policy import narration_slot_status  # noqa: E402
import auto_edit  # noqa: E402
import tts  # noqa: E402


class NarrationSlotTests(unittest.TestCase):
    def test_picks_the_longest_gaps_in_timeline_order(self):
        sils = [(0.0, 2.0), (5.0, 5.4), (9.0, 10.5), (20.0, 21.2)]
        picked = narration_slots(30.0, sils, 1.0, 2)
        self.assertEqual(picked, [(0.0, 2.0), (9.0, 10.5)])

    def test_short_gaps_are_not_slots(self):
        self.assertEqual(narration_slots(30.0, [(5.0, 5.5)], 1.0, 3), [])

    def test_slots_are_the_real_silence_not_an_inflated_window(self):
        sils = [(0.0, 2.0), (6.0, 7.4), (12.0, 13.1)]
        slots = narration_slots(20.0, sils, 1.0, 3)
        self.assertEqual(slots, [(0.0, 2.0), (6.0, 7.4), (12.0, 13.1)])
        self.assertTrue(all(slot in sils for slot in slots))

    def test_cut_keeps_slots_and_tags_every_shot(self):
        calls = {"/x/a.mp4": [(0.0, 2.0), (6.0, 7.4), (12.0, 13.1)]}
        shots = auto_edit.talking_head_shots(
            [Path("/x/a.mp4")], {"/x/a.mp4": {"duration": 20.0, "has_audio": True}},
            detect_silences=lambda clip: calls[str(clip)],
            narration_slot_count=2, min_slot=1.0)
        kinds = [shot["kind"] for shot in shots]
        self.assertIn("narration-slot", kinds)
        self.assertEqual(len([k for k in kinds if k == "narration-slot"]), 2)
        self.assertTrue(all(k in ("speech", "narration-slot") for k in kinds))
        # 槽与说话段在时间轴上不许互相盖住（否则成片会把同一段声音播两遍）
        spans = []
        for shot in shots:
            spans.append((shot["in"], shot["in"] + shot["duration"], shot["kind"]))
        spans.sort()
        for (a0, a1, _), (b0, b1, _) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0 + 1e-6)

    def test_no_slots_means_todays_behaviour(self):
        shots = auto_edit.talking_head_shots(
            [Path("/x/a.mp4")], {"/x/a.mp4": {"duration": 20.0, "has_audio": True}},
            detect_silences=lambda clip: [(6.0, 7.4)],
            narration_slot_count=0)
        self.assertEqual({shot["kind"] for shot in shots}, {"speech"})


class NarrationPolicyTests(unittest.TestCase):
    def project(self, tmp: Path, shots):
        project = Path(tmp)
        (project / "work").mkdir(parents=True, exist_ok=True)
        (project / "work" / "edit-plan.json").write_text(
            json.dumps({"shots": shots}), encoding="utf-8")
        return project

    def config(self):
        return apply_defaults({"canvas": {"width": 1080, "height": 1920, "fps": 30},
                               "audio": {"speech_mode": "mixed",
                                         "voice_cues": "voice-cues.json"}})

    def write_cues(self, project: Path, lines) -> None:
        (project / "work" / "voice-cues.json").write_text(
            json.dumps({"lines": lines}), encoding="utf-8")

    def test_narration_outside_a_slot_is_rejected(self):
        shots = [{"source": "/x.mp4", "in": 0, "duration": 4, "kind": "speech"},
                 {"source": "/x.mp4", "in": 4, "duration": 2, "kind": "narration-slot"}]
        with tempfile.TemporaryDirectory() as tmp:
            project = self.project(Path(tmp), shots)
            self.write_cues(project, [{"start": 1.0, "end": 2.4, "text": "压在人说话上"}])
            ok, detail = narration_slot_status(self.config(), project)
            self.assertIs(ok, False)
            self.assertIn("不落在任何解说槽", detail)

    def test_narration_inside_a_slot_passes(self):
        shots = [{"source": "/x.mp4", "in": 0, "duration": 4, "kind": "speech"},
                 {"source": "/x.mp4", "in": 4, "duration": 2, "kind": "narration-slot"}]
        with tempfile.TemporaryDirectory() as tmp:
            project = self.project(Path(tmp), shots)
            self.write_cues(project, [{"start": 4.2, "end": 5.6, "text": "落在空隙里"}])
            ok, detail = narration_slot_status(self.config(), project)
            self.assertIs(ok, True, detail)
            self.assertIn("解说槽", detail)

    def test_without_slots_the_answer_is_unknown_not_pass(self):
        shots = [{"source": "/x.mp4", "in": 0, "duration": 4, "kind": "speech"}]
        with tempfile.TemporaryDirectory() as tmp:
            project = self.project(Path(tmp), shots)
            self.write_cues(project, [{"start": 0.2, "end": 1.6, "text": "没有槽"}])
            ok, detail = narration_slot_status(self.config(), project)
            self.assertIs(ok, False)
            self.assertIn("narration-slot", detail)

    def test_not_a_mixed_project_is_unchecked_not_a_failure(self):
        cfg = apply_defaults({"audio": {"speech_mode": "source"}})
        with tempfile.TemporaryDirectory() as tmp:
            ok, detail = narration_slot_status(cfg, Path(tmp))
            self.assertIsNone(ok)
            self.assertIn("本项没查", detail)


class NarrationFitTests(unittest.TestCase):
    def test_spans_come_from_the_slot_shots_only(self):
        shots = [{"source": "/x", "in": 0, "duration": 3, "kind": "speech"},
                 {"source": "/x", "in": 3, "duration": 2, "kind": "narration-slot"},
                 {"source": "/x", "in": 5, "duration": 1, "kind": "speech"},
                 {"source": "/x", "in": 6, "duration": 2, "kind": "narration-slot"}]
        self.assertEqual(tts.narration_spans(shots), [(3.0, 5.0, 1), (6.0, 8.0, 2)])

    def test_spans_are_frame_aligned_like_the_renderer(self):
        """每段向上取整到整帧 —— 与 render_plan 的 fps 滤镜同一套规则。

        不这么做的话，段数一多累计偏差能有零点几秒，槽在文件里一个位置、
        在画面里另一个位置，表现是「解说比画面差一点点」。
        """
        from workflow.narration import shot_spans
        shots = [{"source": "/x", "in": 0, "duration": 1.01, "kind": "speech"},
                 {"source": "/x", "in": 1, "duration": 2.0, "kind": "narration-slot"}]
        spans = shot_spans(shots, 30)
        self.assertEqual([(round(a, 3), round(b, 3)) for a, b, _ in spans],
                         [(0.0, 1.033), (1.033, 3.033)])
        self.assertEqual(tts.narration_spans(shots, 30), [(1.033, 3.033, 1)])

    def test_a_slot_index_that_does_not_exist_is_an_error(self):
        shots = [{"source": "/x", "in": 0, "duration": 3, "kind": "speech"}]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "work").mkdir(parents=True)
            (project / "work" / "narration-lines.json").write_text(
                json.dumps({"lines": [{"text": "一句话", "slot": 1}]}), encoding="utf-8")
            (project / "work" / "edit-plan.json").write_text(
                json.dumps({"shots": shots}), encoding="utf-8")
            cfg = apply_defaults({"duration": 3.0, "audio": {"speech_mode": "mixed"}})
            with self.assertRaisesRegex(tts.NarrationError, "narration-slot"):
                tts.build(cfg, project, probe_only=True)

    def test_fitting_escalates_speed_and_then_refuses_to_truncate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            seen = []

            def fake_synth(text, rate, target):
                seen.append(rate)
                target.write_bytes(b"")          # 只为记账，不真合成
                return target

            original_synth, original_dur = tts.synth_line, tts._duration
            tts.synth_line = fake_synth
            tts._duration = lambda path: 99.0        # 永远超过预算
            try:
                with self.assertRaises(tts.NarrationError) as caught:
                    tts.fit_line("一句话", 1.0, cache, 1)
                self.assertIn("装不进", str(caught.exception))
                self.assertEqual(seen, list(tts.RATES))   # 每档速率都试过才拒绝
            finally:
                tts.synth_line, tts._duration = original_synth, original_dur


if __name__ == "__main__":
    unittest.main()
