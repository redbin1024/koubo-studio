import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from export_voice_review import _point_to_latest, relevant_shots, shot_spans
from _common import apply_defaults
from workflow.delivery import receipt_digest, record_render
from workflow.voice_review import (REVIEW_VERSION, file_digest, record_decision,
                                   refresh_review, review_directory, review_status)


class VoiceReviewTests(unittest.TestCase):
    def make_review(self, project):
        cfg = apply_defaults({"name": "test", "duration": 2,
                              "input": {"video": "clean-cut.mp4"},
                              "audio": {"speech_mode": "narration",
                                        "voice_cues": "voice-cues.json"}})
        (project / "input").mkdir(exist_ok=True)
        (project / "work").mkdir(exist_ok=True)
        (project / "output").mkdir(exist_ok=True)
        (project / "input/clean-cut.mp4").write_bytes(b"picture")
        (project / "config.json").write_text(json.dumps(cfg))
        windows = [{"start": 0.1, "end": 0.8, "text": "第一句"},
                   {"start": 1.1, "end": 1.8, "text": "第二句"}]
        (project / "work/voice-cues.json").write_text(json.dumps({"lines": windows}))
        movie = project / "output/final-720x1280.mp4"
        movie.write_bytes(b"rendered")
        record_render(project, movie, cfg)
        directory = review_directory(project, receipt_digest(project))
        directory.mkdir(parents=True)
        lines = []
        for number, window in enumerate(windows, 1):
            clip = directory / f"line-{number:02d}.mp4"
            clip.write_bytes(f"clip {number}".encode())
            lines.append({**window, "index": number, "clip": clip.name,
                          "clip_sha256": file_digest(clip), "shots": []})
        manifest = {"version": REVIEW_VERSION,
                    "render_receipt_sha256": receipt_digest(project),
                    "source_video": str(movie.resolve()), "lines": lines}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return cfg, directory

    def pass_checks(self):
        return {"semantics": "pass", "voice": "pass", "subtitles": "pass"}

    def test_exported_materials_start_pending_without_invented_votes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            status = refresh_review(cfg, project)
            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["summary"]["pending"], 2)
            self.assertFalse((directory / "decisions.json").exists())
            self.assertIn("待人工验收", (directory / "听审清单.md").read_text())

    def test_each_criterion_and_actual_reviewer_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            for checks, reviewer, note in [
                ({"semantics": "pass"}, "审核人", ""),
                (self.pass_checks(), "  ", ""),
                ({**self.pass_checks(), "voice": "fail"}, "审核人", "")]:
                with self.assertRaises(ValueError):
                    record_decision(cfg, project, 1, checks, reviewer, note)
            self.assertFalse((directory / "decisions.json").exists())

    def test_revisions_preserve_history_and_do_not_approve_unseen_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            failed = {**self.pass_checks(), "semantics": "fail"}
            status = record_decision(cfg, project, 1, failed, "审核人甲", "画面动作不对应")
            self.assertEqual(status["status"], "failed")
            status = record_decision(cfg, project, 1, self.pass_checks(), "审核人乙", "复核通过")
            self.assertEqual(status["status"], "pending")
            self.assertEqual(status["summary"], {"pending": 1, "failed": 0, "passed": 1})
            audit = json.loads((directory / "decisions.json").read_text())
            self.assertEqual([row["reviewer"] for row in audit["events"]], ["审核人甲", "审核人乙"])
            self.assertEqual(audit["events"][0]["note"], "画面动作不对应")
            self.assertIn("复核通过", (directory / "听审清单.md").read_text())

    def test_clip_or_manifest_changes_invalidate_existing_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            record_decision(cfg, project, 1, self.pass_checks(), "审核人")
            clip = directory / "line-01.mp4"
            original = clip.read_bytes()
            clip.write_bytes(b"edited")
            self.assertEqual(review_status(cfg, project)["status"], "stale")
            with self.assertRaises(ValueError):
                record_decision(cfg, project, 2, self.pass_checks(), "审核人")
            clip.write_bytes(original)
            manifest = directory / "manifest.json"
            manifest.write_text(manifest.read_text() + "\n")
            self.assertEqual(review_status(cfg, project)["status"], "stale")

    def test_changed_inputs_reject_old_votes_and_new_render_starts_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            for line in (1, 2):
                record_decision(cfg, project, line, self.pass_checks(), "审核人")
            cfg["duration"] = 3
            self.assertEqual(review_status(cfg, project)["status"], "stale")
            with self.assertRaises(ValueError):
                record_decision(cfg, project, 1, self.pass_checks(), "审核人")
            record_render(project, project / "output/final-720x1280.mp4", cfg)
            self.assertEqual(review_status(cfg, project)["status"], "pending")
            self.assertTrue((directory / "decisions.json").is_file())

    def test_missing_lines_and_corrupt_audit_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            path = directory / "manifest.json"
            original = path.read_text()
            manifest = json.loads(original)
            manifest["lines"] = []
            path.write_text(json.dumps(manifest))
            self.assertEqual(review_status(cfg, project)["status"], "stale")
            path.write_text(original)
            (directory / "decisions.json").write_text("{corrupt")
            with self.assertRaises(ValueError):
                record_decision(cfg, project, 1, self.pass_checks(), "审核人")

    def test_pipeline_waits_for_all_human_votes_and_tracks_requested_changes(self):
        import run_all
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, directory = self.make_review(project)
            result = {"directory": str(directory), "lines": 2}
            qc = {"output": str(project / "output/final-720x1280.mp4"),
                  "summary": {"pass": 1, "fail": 0, "unchecked": 0}}
            with patch.object(sys, "argv", ["run_all.py", str(project), "--only", "render,draft,verify,review"]), \
                    patch("workflow.speech_policy.require_speech_ready"), \
                    patch.object(run_all, "resolve_duration", return_value=2), \
                    patch.object(run_all.render, "build", return_value={}), \
                    patch.object(run_all.make_jianying_draft, "build", return_value={}), \
                    patch.object(run_all.verify, "run_checks", return_value=qc), \
                    patch("export_voice_review.export_review", return_value=result):
                run_all.main()
            pipeline = project / "work/pipeline.json"
            self.assertEqual(json.loads(pipeline.read_text())["status"], "awaiting_review")
            record_decision(cfg, project, 1, self.pass_checks(), "审核人")
            record_decision(cfg, project, 2, {**self.pass_checks(), "subtitles": "fail"}, "审核人", "遮住人物")
            self.assertEqual(json.loads(pipeline.read_text())["status"], "changes_requested")
            record_decision(cfg, project, 2, self.pass_checks(), "审核人", "复核无误")
            self.assertEqual(json.loads(pipeline.read_text())["status"], "complete")

    def test_human_votes_do_not_complete_partial_or_unrelated_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, _ = self.make_review(project)
            pipeline = project / "work/pipeline.json"
            for log in [{"status": "partial", "render_receipt_sha256": receipt_digest(project)},
                        {"status": "complete", "automation_complete": True,
                         "render_receipt_sha256": "old receipt"}]:
                pipeline.write_text(json.dumps(log))
                for line in (1, 2):
                    record_decision(cfg, project, line, self.pass_checks(), "审核人")
                self.assertEqual(json.loads(pipeline.read_text()), log)

    def test_disabling_review_after_render_cannot_mark_stale_pipeline_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            cfg, _ = self.make_review(project)
            pipeline = project / "work/pipeline.json"
            pipeline.write_text(json.dumps({"status": "awaiting_review", "automation_complete": True,
                                            "render_receipt_sha256": receipt_digest(project)}))
            cfg["audio"]["voice_cues"] = None
            refresh_review(cfg, project)
            log = json.loads(pipeline.read_text())
            self.assertEqual(log["status"], "stale")
            self.assertFalse(log["automation_complete"])

    def test_latest_pointer_moves_without_deleting_old_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "v1-first", root / "v1-second"
            first.mkdir()
            second.mkdir()
            _point_to_latest(root, first)
            _point_to_latest(root, second)
            self.assertEqual((root / "latest").resolve(), second.resolve())
            self.assertTrue(first.is_dir())

    def test_review_maps_one_line_across_two_source_shots(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            work = project / "work"
            work.mkdir()
            sources = [project / "a.mov", project / "b.mov"]
            plan = {"shots": [
                {"source": str(sources[0]), "in": 3.0, "duration": 1.0},
                {"source": str(sources[1]), "in": 5.0, "duration": 1.0}]}
            (work / "edit-plan.json").write_text(json.dumps(plan), encoding="utf-8")
            matches = relevant_shots(0.8, 1.2, shot_spans(project))
            self.assertEqual([row["index"] for row in matches], [1, 2])
            self.assertEqual([(row["source_in"], row["source_out"]) for row in matches],
                             [(3.8, 4.0), (5.0, 5.2)])


if __name__ == "__main__":
    unittest.main()
