#!/usr/bin/env python3
"""Test singolo per un modello."""

import json, requests, subprocess, re
from pathlib import Path
from datetime import datetime

MODEL = "qwen3-reap"
FOLDER = "quiz_tabelline_test"
BASE_PATH = Path("/home/vik/Documenti/progetti")
BASE_URL = "http://localhost:11434"

PROMPT = """Crea app web per tabelline (1-10) per bambina di 7 anni. 
Path: {path}. Max 200 righe/file. HTML self-contained, vanilla JS, Web Audio API.
Menu 10 bottoni colorati, quiz, feedback animato, risultati.
Rispondi SOLO con JSON {{"cmd1":"...", "cmd2":"..."}} - NO spiegazioni, NO <think>."""

def remove_thinking(text):
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)

def extract_commands(response):
    response = remove_thinking(response).strip()
    if '{"cmd' in response:
        start = response.find('{"cmd')
        depth, in_string, escape_next, end = 0, False, False, start
        for i in range(start, len(response)):
            c = response[i]
            if escape_next: escape_next = False
            elif c == '\\': escape_next = True
            elif c == '"' and not escape_next: in_string = not in_string
            elif not in_string:
                if c == '{': depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        json_str = response[start:end]
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                return [data[k] for k in sorted(data.keys()) if k.startswith('cmd')]
        except Exception as e:
            print(f"Parser error: {e}")
    return []

path = BASE_PATH / FOLDER
path.mkdir(parents=True, exist_ok=True)
prompt = PROMPT.format(path=path)

print(f"🧪 Testing {MODEL} → {FOLDER}\n")
print(f"Prompt inviato...")

response = requests.post(f"{BASE_URL}/api/generate",
    json={"model": MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2, "num_predict": -1}},
    timeout=300)

llm_response = response.json()["response"]
log_file = path / f"response_{datetime.now().strftime('%H%M%S')}.txt"
log_file.write_text(llm_response)
print(f"📝 Response salvata: {log_file} ({len(llm_response)} chars)\n")

commands = extract_commands(llm_response)
print(f"📋 {len(commands)} comandi estratti\n")

for i, cmd in enumerate(commands, 1):
    print(f"[{i}] {cmd[:80]}...")
    cmd = cmd.replace('$HOME', str(Path.home())).replace('\\n', '\n')
    try:
        result = subprocess.run(cmd, shell=True, cwd=str(path), capture_output=True, text=True, timeout=60)
        status = "✓" if result.returncode == 0 else "✗"
        print(f"    [{status}] {result.stderr[:100] if result.stderr else 'OK'}")
    except Exception as e:
        print(f"    [✗] {e}")

files = list(path.glob("*.html"))
print(f"\n📁 File HTML creati: {len(files)}")
for f in files:
    lines = len(f.read_text().split('\n'))
    print(f"  - {f.name}: {lines} righe")
