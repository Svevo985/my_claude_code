import unittest

from src.gui import OllamaBridgeGUI


class StepWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.gui = OllamaBridgeGUI.__new__(OllamaBridgeGUI)
        self.gui.config = {
            "workflow": {
                "step_num_predict": 1200,
                "step_max_response_chars": 20000,
                "max_step_retries": 2,
            }
        }

    def test_parse_plan_steps_generic(self):
        plan = """
## App Summary
- Crea una CLI per note
- Salva i dati su file JSON

## Steps
### Step 1 - `notes.py`
Goal: definire modello dati e funzioni CRUD
Key references:
- funzione save_notes(path)

### Step 2 - `main.py`
Goal: implementare menu CLI e parser input
Key references:
- usa funzioni esportate da notes.py
"""
        parsed = self.gui._parse_plan_steps(plan)
        self.assertEqual(len(parsed["steps"]), 2)
        self.assertEqual(parsed["steps"][0]["filename"], "notes.py")
        self.assertEqual(parsed["steps"][1]["filename"], "main.py")
        self.assertTrue(parsed["app_summary"])

    def test_build_step_brief_uses_previous_refs_only(self):
        step_context = {
            "app_summary": ["App note CLI", "Persistenza JSON"],
            "steps": [
                {"num": 1, "filename": "notes.py", "status": "done"},
                {"num": 2, "filename": "main.py", "status": "in_progress"},
            ],
        }
        step = {
            "num": 2,
            "filename": "main.py",
            "goal": "Implementa menu",
            "plan_references": ["usa funzioni CRUD"],
        }
        refs = {
            "notes.py": {"functions": ["save_notes", "load_notes"]},
            "main.py": {"functions": ["main"]},
        }
        brief = self.gui._build_step_brief("crea app note", step_context, step, refs)
        self.assertIn("ADESSO SIAMO NELLO STEP 2", brief)
        self.assertIn("save_notes", brief)
        self.assertNotIn("main.py:\n- functions: main", brief)

    def test_commands_target_expected_file(self):
        ok_commands = [
            "Set-Content -Path 'main.py' -Value 'print(1)'",
            "Add-Content -Path 'main.py' -Value 'print(2)'",
        ]
        bad_commands = [
            "Set-Content -Path 'utils.py' -Value 'print(1)'",
        ]
        self.assertTrue(self.gui._commands_target_expected_file(ok_commands, "main.py"))
        self.assertFalse(self.gui._commands_target_expected_file(bad_commands, "main.py"))

    def test_validate_plan_schema_requires_acceptance_checks(self):
        plan_obj = {
            "app_summary": ["CLI note", "Persistenza JSON"],
            "steps": [
                {
                    "num": 1,
                    "filename": "notes.py",
                    "goal": "Definisce funzioni CRUD",
                    "key_refs": ["save_notes(path)", "load_notes(path)"],
                    "acceptance_checks": ["def save_notes presente", "def load_notes presente"],
                },
                {
                    "num": 2,
                    "filename": "main.py",
                    "goal": "Implementa menu CLI",
                    "key_refs": ["usa notes.py", "arg parsing"],
                    "acceptance_checks": ["main() presente", "menu loop gestito"],
                },
            ],
        }
        ok, err, normalized = self.gui._validate_plan_schema(plan_obj)
        self.assertTrue(ok, err)
        self.assertIsNotNone(normalized)
        self.assertEqual(len(normalized["steps"]), 2)
        self.assertIn("acceptance_checks", normalized["steps"][0])

    def test_render_claude_md_from_schema(self):
        app_summary = ["App note CLI", "Persistenza locale"]
        steps = [
            {
                "num": 1,
                "filename": "notes.py",
                "goal": "CRUD note",
                "plan_references": ["save_notes", "load_notes"],
                "acceptance_checks": ["save_notes presente", "load_notes presente"],
            }
        ]
        md = self.gui._render_claude_md(app_summary, steps)
        self.assertIn("## App Summary", md)
        self.assertIn("### Step 1 - `notes.py`", md)
        self.assertIn("Acceptance checks:", md)

    def test_step_retry_hint_mentions_target_file(self):
        hint = self.gui._build_step_retry_hint("script.js", "JSON non valido")
        self.assertIn("script.js", hint)
        self.assertIn("JSON", hint)


if __name__ == "__main__":
    unittest.main()
