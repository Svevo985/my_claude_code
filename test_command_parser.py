import unittest

from src.command_parser import CommandParser


class CommandParserRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.parser = CommandParser()

    def test_parse_malformed_json_with_herestring_preserves_full_command(self):
        # JSON volutamente malformato (doppi apici non escaped nel contenuto HTML)
        raw = """{
  "cmd1": "Set-Content -Path 'index.html' -Value @'
<!DOCTYPE html>
<html lang="it">
<body>
  <div class="cell" data-index="8"></div>
</body>
</html>
'@
}
"""
        parsed = self.parser.parse(raw)
        self.assertTrue(parsed.is_valid, parsed.error)
        self.assertEqual(len(parsed.commands), 1)
        cmd = parsed.commands[0]
        self.assertIn("Set-Content -Path 'index.html' -Value @'", cmd)
        self.assertIn('<div class="cell" data-index="8"></div>', cmd)
        self.assertTrue(cmd.rstrip().endswith("'@"))

    def test_extract_direct_powershell_write_commands(self):
        raw = """
texto libero
Set-Content -Path 'style.css' -Value @'
.cell { color: red; }
'@
altro testo
"""
        commands = self.parser._extract_powershell_write_commands(raw)
        self.assertEqual(len(commands), 1)
        self.assertIn("-Path 'style.css'", commands[0])
        self.assertIn(".cell { color: red; }", commands[0])
        self.assertTrue(commands[0].rstrip().endswith("'@"))


if __name__ == "__main__":
    unittest.main()
