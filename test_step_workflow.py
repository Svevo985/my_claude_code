import unittest
from pathlib import Path
import tempfile

from src.gui import OllamaBridgeGUI
from src.command_parser import CommandParser
from src.project_memory import ProjectMemory


class StepWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.gui = OllamaBridgeGUI.__new__(OllamaBridgeGUI)
        self.gui.parser = CommandParser()
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

    def test_execute_command_with_fallback_supports_set_content_append_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            ok1 = self.gui._execute_command_with_fallback(
                "Set-Content -Path 'styles.css' -Value '.cell{width:100px;height:100px;}'",
                p,
                "styles.css",
            )
            self.assertTrue(ok1)
            ok2 = self.gui._execute_command_with_fallback(
                "Set-Content -Path 'styles.css' -Append -Value 'button{padding:8px;}'",
                p,
                "styles.css",
            )
            self.assertTrue(ok2)

            written = (p / "styles.css").read_text(encoding="utf-8")
            self.assertIn(".cell{width:100px;height:100px;}", written)
            self.assertIn("button{padding:8px;}", written)

    def test_execute_command_with_fallback_repairs_overescaped_js_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cmd = (
                "Set-Content -Path 'script.js' -Value "
                "'const winPatterns = \\[\\[0,1,2\\],\\[3,4,5\\]\\];\\n"
                "function getFirst(){ return winPatterns\\[0\\]\\[0\\]; }'"
            )
            ok = self.gui._execute_command_with_fallback(cmd, p, "script.js")
            self.assertTrue(ok)
            written = (p / "script.js").read_text(encoding="utf-8")
            self.assertNotIn("\\[", written)
            self.assertNotIn("\\]", written)
            self.assertIn("const winPatterns = [[0,1,2],[3,4,5]];", written)
            self.assertIn("winPatterns[0][0]", written)

    def test_repair_overescaped_content_does_not_touch_small_regex_like_escape(self):
        content = "const re = /\\[[^\\]]+\\]/;"
        repaired = self.gui._repair_probable_overescaped_content("script.js", content)
        self.assertEqual(content, repaired)

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

    def test_extract_value_handles_unescaped_js_single_quotes(self):
        cmd = (
            "Set-Content -Path 'script.js' -Value 'const player = 'X';\\n"
            "function initGame(){ return player; }'"
        )
        content = self.gui._extract_value_from_command(cmd)
        self.assertIsNotNone(content)
        self.assertIn("const player = 'X';", content)
        self.assertIn("function initGame()", content)

    def test_extract_value_supports_powershell_herestring(self):
        cmd = (
            "Set-Content -Path 'script.js' -Value @'\n"
            "const player = 'X';\n"
            "function initGame(){ return player; }\n"
            "'@"
        )
        content = self.gui._extract_value_from_command(cmd)
        self.assertIsNotNone(content)
        self.assertIn("const player = 'X';", content)
        self.assertIn("function initGame()", content)

    def test_detects_truncated_value_command(self):
        truncated = "Set-Content -Path 'script.js' -Value 'function init(){\\n  return true;\\n\\"
        complete = "Set-Content -Path 'script.js' -Value 'function init(){\\n  return true;\\n}'"
        self.assertTrue(self.gui._is_command_likely_truncated(truncated))
        self.assertFalse(self.gui._is_command_likely_truncated(complete))

    def test_extract_value_supports_malformed_qwen_herestring(self):
        cmd = (
            "Set-Content -Path 'index.html' -Value @'<!DOCTYPE html>\\n"
            "<html><body><h1>Tris</h1></body></html>'"
        )
        content = self.gui._extract_value_from_command(cmd)
        self.assertIsNotNone(content)
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("<h1>Tris</h1>", content)

    def test_malformed_qwen_herestring_not_flagged_as_truncated_when_recoverable(self):
        cmd = (
            "Set-Content -Path 'styles.css' -Value @'.cell{display:grid;}\\n"
            "#board{gap:8px;}'"
        )
        self.assertFalse(self.gui._is_command_likely_truncated(cmd))

    def test_extract_direct_file_content_from_json_cmd(self):
        response = """{
  "cmd1": "<!DOCTYPE html>\\n<html><body><h1>Tris</h1></body></html>"
}"""
        content = self.gui._extract_direct_file_content_from_response(response, "index.html")
        self.assertIsNotNone(content)
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("<h1>Tris</h1>", content)

    def test_write_direct_step_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            content = "<!DOCTYPE html>\\n<html><body><h1>OK</h1></body></html>"
            ok = self.gui._write_direct_step_content(p, "index.html", content)
            self.assertTrue(ok)
            self.assertTrue((p / "index.html").exists())

    def test_validate_written_step_file_requires_html_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            html = "<!DOCTYPE html>\\n<html><head><link rel='stylesheet' href='style.css'></head><body><script src='script.js'></script></body></html>"
            (p / "index.html").write_text(html, encoding="utf-8")
            step_context = {
                "steps": [
                    {"num": 1, "filename": "index.html", "status": "done"},
                    {"num": 2, "filename": "style.css", "status": "pending"},
                    {"num": 3, "filename": "script.js", "status": "pending"},
                ]
            }
            ok, reason = self.gui._validate_written_step_file(p, step_context, "index.html")
            self.assertTrue(ok, reason)

            bad_html = "<!DOCTYPE html>\\n<html><head><link rel='stylesheet' href='style.css'></head><body></body></html>"
            (p / "index.html").write_text(bad_html, encoding="utf-8")
            ok2, reason2 = self.gui._validate_written_step_file(p, step_context, "index.html")
            self.assertFalse(ok2)
            self.assertIn("JS", reason2)

    def test_validate_written_step_file_css_detects_button_selector_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "index.html").write_text(
                "<!DOCTYPE html><html><body><button id='reset-btn'>Reset</button><div class='cell'></div></body></html>",
                encoding="utf-8",
            )
            (p / "style.css").write_text(
                ".cell { color: red; }\n.reset-btn { background: black; }",
                encoding="utf-8",
            )
            step_context = {
                "steps": [
                    {"num": 1, "filename": "index.html", "status": "done"},
                    {"num": 2, "filename": "style.css", "status": "in_progress"},
                ]
            }
            ok, reason = self.gui._validate_written_step_file(p, step_context, "style.css")
            self.assertFalse(ok)
            self.assertIn("azione", reason.lower())

    def test_validate_written_step_file_css_allows_non_action_button_without_specific_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "index.html").write_text(
                "<!DOCTYPE html><html><body><button id='hero-btn'>Learn More</button><div class='cell'></div></body></html>",
                encoding="utf-8",
            )
            (p / "style.css").write_text(
                ".cell { color: red; }",
                encoding="utf-8",
            )
            step_context = {
                "steps": [
                    {"num": 1, "filename": "index.html", "status": "done"},
                    {"num": 2, "filename": "style.css", "status": "in_progress"},
                ]
            }
            ok, reason = self.gui._validate_written_step_file(p, step_context, "style.css")
            self.assertTrue(ok, reason)

    def test_validate_written_step_file_js_requires_reset_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "index.html").write_text(
                "<!DOCTYPE html><html><body><button id='reset-btn'>Reset</button><div id='status'></div></body></html>",
                encoding="utf-8",
            )
            (p / "script.js").write_text(
                "const resetBtn = document.getElementById('reset-btn');\n"
                "const status = document.getElementById('status');\n"
                "function resetGame(){ status.textContent='ok'; }\n",
                encoding="utf-8",
            )
            step_context = {
                "steps": [
                    {"num": 1, "filename": "index.html", "status": "done"},
                    {"num": 2, "filename": "script.js", "status": "in_progress"},
                ]
            }
            ok, reason = self.gui._validate_written_step_file(p, step_context, "script.js")
            self.assertFalse(ok)
            self.assertIn("listener", reason.lower())

            (p / "script.js").write_text(
                "const resetBtn = document.getElementById('reset-btn');\n"
                "const status = document.getElementById('status');\n"
                "function resetGame(){ status.textContent='ok'; }\n"
                "resetBtn.addEventListener('click', resetGame);\n",
                encoding="utf-8",
            )
            ok2, reason2 = self.gui._validate_written_step_file(p, step_context, "script.js")
            self.assertTrue(ok2, reason2)

    def test_validate_written_step_file_js_allows_non_action_button_without_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "index.html").write_text(
                "<!DOCTYPE html><html><body><button id='hero-btn'>Learn More</button><div id='status'></div></body></html>",
                encoding="utf-8",
            )
            (p / "script.js").write_text(
                "const status = document.getElementById('status');\n"
                "function render(){ status.textContent='ok'; }\n",
                encoding="utf-8",
            )
            step_context = {
                "steps": [
                    {"num": 1, "filename": "index.html", "status": "done"},
                    {"num": 2, "filename": "script.js", "status": "in_progress"},
                ]
            }
            ok, reason = self.gui._validate_written_step_file(p, step_context, "script.js")
            self.assertTrue(ok, reason)

    def test_validate_written_step_file_js_requires_action_listener_from_button_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "index.html").write_text(
                "<!DOCTYPE html><html><body><button id='primary-btn'>Save</button><div id='status'></div></body></html>",
                encoding="utf-8",
            )
            (p / "script.js").write_text(
                "const status = document.getElementById('status');\n"
                "function render(){ status.textContent='ok'; }\n",
                encoding="utf-8",
            )
            step_context = {
                "steps": [
                    {"num": 1, "filename": "index.html", "status": "done"},
                    {"num": 2, "filename": "script.js", "status": "in_progress"},
                ]
            }
            ok, reason = self.gui._validate_written_step_file(p, step_context, "script.js")
            self.assertFalse(ok)
            self.assertIn("azione", reason.lower())

    def test_build_step_file_rules_generic_html_js(self):
        html_rules = self.gui._build_step_file_rules("index.html")
        js_rules = self.gui._build_step_file_rules("script.js")
        self.assertNotIn("celle gioco", html_rules.lower())
        self.assertIn("hook stabili", html_rules.lower())
        self.assertNotIn("bottone reset", js_rules.lower())

    def test_infer_project_name_has_no_tris_special_case(self):
        inferred = self.gui._infer_project_name("il tris è lento su questo laptop")
        self.assertEqual(inferred, "Nuovo Progetto")

    def test_update_memory_from_file_extracts_html_and_js_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            memory = ProjectMemory(p)

            html_content = (
                "<!DOCTYPE html><html><head>"
                "<link rel='stylesheet' href='style.css'>"
                "</head><body>"
                "<div id='board' class='cell active'></div>"
                "<button id='reset-btn'>Reset</button>"
                "<script src='script.js'></script>"
                "</body></html>"
            )
            self.gui._update_memory_from_file(memory, "index.html", html_content)
            html_contract = memory.get_file_contract("index.html")
            self.assertIsNotNone(html_contract)
            elements = html_contract["elements"]
            self.assertIn("board", elements.get("ids", []))
            self.assertIn("cell", elements.get("classes", []))
            self.assertIn("active", elements.get("classes", []))
            self.assertIn("reset-btn", elements.get("button_ids", []))
            self.assertEqual(elements.get("has_css_link", ["False"])[0], "True")
            self.assertEqual(elements.get("has_js_link", ["False"])[0], "True")

            js_content = (
                "const resetBtn = document.getElementById('reset-btn');\n"
                "const cells = document.querySelectorAll('.cell');\n"
                "resetBtn.addEventListener('click', () => {});\n"
            )
            self.gui._update_memory_from_file(memory, "script.js", js_content)
            js_contract = memory.get_file_contract("script.js")
            self.assertIsNotNone(js_contract)
            js_elements = js_contract["elements"]
            self.assertIn("reset-btn", js_elements.get("used_ids", []))
            self.assertIn(".cell", js_elements.get("used_classes", []))

    def test_build_planning_prompt_fix_includes_existing_files_and_diagnostics(self):
        prompt = self.gui._build_planning_prompt(
            "fixa il tris che non resetta",
            mode="fix",
            existing_files=["index.html", "style.css", "script.js"],
            diagnostics=[("script.js", "listener reset mancante")],
        )
        self.assertIn("CONTESTO FIX", prompt)
        self.assertIn("script.js", prompt)
        self.assertIn("listener reset mancante", prompt)
        self.assertIn("REGOLE FIX AGGIUNTIVE", prompt)

    def test_strip_doc_steps_for_new_mode(self):
        steps = [
            {"num": 1, "filename": "index.html", "goal": "html"},
            {"num": 2, "filename": "styles.css", "goal": "css"},
            {"num": 3, "filename": "README.md", "goal": "docs"},
            {"num": 4, "filename": "script.js", "goal": "js"},
        ]
        filtered, removed = self.gui._strip_doc_steps_for_new_mode(steps, "crea un gioco del tris")
        self.assertEqual(removed, ["README.md"])
        self.assertEqual([s["filename"] for s in filtered], ["index.html", "styles.css", "script.js"])
        self.assertEqual([s["num"] for s in filtered], [1, 2, 3])

        kept, removed2 = self.gui._strip_doc_steps_for_new_mode(steps, "crea un gioco del tris con readme")
        self.assertEqual(removed2, [])
        self.assertEqual(len(kept), 4)

    def test_validate_file_content_css_one_line_is_allowed(self):
        css = ".board{display:grid;grid-template-columns:repeat(3,1fr);} .cell{width:80px;height:80px;}"
        result = self.gui._validate_file_content("styles.css", css)
        self.assertTrue(result["valid"], result["reason"])


if __name__ == "__main__":
    unittest.main()
