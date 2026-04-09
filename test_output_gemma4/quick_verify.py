#!/usr/bin/env python3
"""Quick verify that the parser fix handles missing Unicode chars."""
import sys, os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding="utf-8", errors="replace")
    except: pass

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
from src.command_parser import CommandParser

p = CommandParser()
tests = [
    # U+2212 minus sign in flags
    ('{"cmd1": "New-Item \u2212ItemType Directory \u2212Force \u2212Path \'proj\'"}', "minus_sign"),
    # U+2026 ellipsis in path
    ('{"cmd1": "Set-Content -Path \'C:\\\\proj\\\\\u2026\\\\main.py\' -Value \'hi\'"}', "ellipsis"),
    # U+2011 non-breaking hyphen
    ('{"cmd1": "Get\u2011ChildItem \u2011Path \'proj\'"}', "nb_hyphen"),
    # All together
    ('{"cmd1": "New\u2011Item \u2212ItemType Directory", "cmd2": "Set\u2011Content \u2212Path \'C:\\\\\u2026\\\\f.py\' \u2212Value \'x\'"}', "all_combined"),
]

ok = 0
for input_str, name in tests:
    r = p.parse(input_str)
    passed = r.is_valid and len(r.commands) > 0
    # Check that typographic chars were cleaned from commands
    has_bad = any(c in cmd for cmd in r.commands for c in '\u2212\u2026\u2011\u2013\u2014')
    status = "PASS" if passed and not has_bad else "FAIL"
    if passed and not has_bad:
        ok += 1
    print(f"  {'✓' if status == 'PASS' else '✗'} {name}: {status}")
    if r.commands:
        for i, cmd in enumerate(r.commands, 1):
            print(f"      cmd{i}: {cmd}")
    if has_bad:
        print(f"      ⚠ Typographic chars survived cleanup!")

print(f"\n  Result: {ok}/{len(tests)} passed")
sys.exit(0 if ok == len(tests) else 1)
