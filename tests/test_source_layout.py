import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class SourceLayoutTests(unittest.TestCase):
    def test_legacy_names_reference_workflow_implementations(self):
        import edit_plan
        import storyboard
        import visual_analysis
        from workflow import edit_plan as plan_core
        from workflow import storyboard as story_core
        from workflow import visual_analysis as vision_core

        self.assertIs(edit_plan.validate_plan, plan_core.validate_plan)
        self.assertIs(edit_plan.render_plan, plan_core.render_plan)
        self.assertIs(visual_analysis.analyze_shots, vision_core.analyze_shots)
        self.assertIs(visual_analysis._http_transport, vision_core._http_transport)
        self.assertIs(storyboard.suggest_story, story_core.suggest_story)
        self.assertIs(storyboard.MOODS, story_core.MOODS)

    def test_cli_imports_internal_workflow_directly(self):
        expected = {
            "auto_edit.py": {"workflow.edit_plan", "workflow.visual_analysis",
                             "workflow.storyboard"},
            "story_audio.py": {"workflow.storyboard"},
        }
        for filename, imports in expected.items():
            with self.subTest(filename=filename):
                tree = ast.parse((ROOT / "scripts" / filename).read_text(encoding="utf-8"))
                found = {node.module for node in ast.walk(tree)
                         if isinstance(node, ast.ImportFrom)}
                self.assertTrue(imports <= found, f"{filename}: {imports - found}")


if __name__ == "__main__":
    unittest.main()
