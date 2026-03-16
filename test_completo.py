#!/usr/bin/env python3
"""Test con system prompt completo dal Modelfile."""

import json, requests, subprocess, re
from pathlib import Path
from datetime import datetime

MODEL = "qwen3-reap"
FOLDER = "quiz_tabelline_completo"
BASE_PATH = Path("/home/vik/Documenti/progetti")
BASE_URL = "http://localhost:11434"

SYSTEM_PROMPT = """
You are a senior software architect. You answer ONLY with a JSON object for a file system bridge.

CRITICAL RULES:
1. Reply ONLY with a valid JSON object: {"cmd1": "...", "cmd2": "...", ...}
2. Each value is a RAW SHELL COMMAND string
3. NO nested objects, NO arrays, NO extra keys
4. NO explanations, NO markdown, NO text outside the JSON object
5. The JSON must be complete and valid — never truncate

PROJECT CREATION ORDER - MANDATORY:
STEP 1: mkdir -p /path/to/project
STEP 2: Create readme.md WITH structure (title, description, technologies, files list, status)
STEP 3: Create source files (MAX 250 LINES PER FILE)
STEP 4: Update readme.md status after each file

FILE SIZE LIMIT: MAX 250 LINES PER FILE - split if needed!

IMPORTANT: readme.md is ALWAYS created BEFORE any code file. Use cat << 'EOF' for files.
"""

USER_PROMPT = """
Crea app web COMPLETA per tabelline (1-10) per bambina di 7 anni.
Path: {path}

REQUISITI:
- Unico file HTML con CSS e JS inline (self-contained)
- Max 200 righe
- Menu con 10 bottoni colorati (emoji diversi)
- Quiz: una domanda alla volta, input numerico, feedback animato
- Web Audio API per suoni (successo/errore)
- Schermata risultati con punteggio
- Grafica vivace, stile cartone animato, font Google (Fredoka One)
- Responsive per tablet Android

Crea file COMPLETI e FUNZIONANTI. Non troncare il codice.
Rispondi SOLO con JSON {{"cmd1":"...", "cmd2":"..."}}
"""

def remove_thinking(text):
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)

def extract_commands(response):
    response = remove_thinking(response).strip()
    commands = []
    
    # Formato 1: {"cmd1": "...", "cmd2": "..."}
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
            print(f"Parser error format1: {e}")
    
    # Formato 2: {"comando": "contenuto"} - chiavi sono i comandi stessi
    try:
        start = response.find('{')
        end = response.rfind('}') + 1
        json_str = response[start:end]
        data = json.loads(json_str)
        if isinstance(data, dict):
            for key, value in data.items():
                if key.startswith(('mkdir', 'cat', 'cd', 'cp', 'rm', 'echo')):
                    if value:  # Se c'è contenuto, è un heredoc
                        commands.append(f"{key}\n{value}")
                    else:
                        commands.append(key)
            return commands
    except Exception as e:
        print(f"Parser error format2: {e}")
    
    return []

path = BASE_PATH / FOLDER
path.mkdir(parents=True, exist_ok=True)
prompt = USER_PROMPT.format(path=path)

print(f"🧪 Testing {MODEL} → {FOLDER}\n")
print(f"Invio prompt con system prompt completo...\n")

response = requests.post(f"{BASE_URL}/api/chat",
    json={
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": -1}
    },
    timeout=600)  # 10 minuti

llm_response = response.json()["message"]["content"]
log_file = path / f"response_{datetime.now().strftime('%H%M%S')}.txt"
log_file.write_text(llm_response)
print(f"📝 Response: {len(llm_response)} chars, salvata in {log_file}\n")

commands = extract_commands(llm_response)
print(f"📋 {len(commands)} comandi estratti\n")

for i, cmd in enumerate(commands, 1):
    preview = cmd[:60].replace('\n', '\\n')
    print(f"[{i}] {preview}...")
    cmd = cmd.replace('$HOME', str(Path.home())).replace('\\n', '\n')
    try:
        result = subprocess.run(cmd, shell=True, cwd=str(path), capture_output=True, text=True, timeout=60)
        status = "✓" if result.returncode == 0 else "✗"
        err = result.stderr[:80].replace('\n', ' ') if result.stderr else 'OK'
        print(f"    [{status}] {err}")
    except Exception as e:
        print(f"    [✗] {e}")

files = list(path.glob("*"))
print(f"\n📁 File creati: {len(files)}")
for f in sorted(files):
    if f.is_file() and f.suffix not in ['.txt']:
        lines = len(f.read_text().split('\n'))
        print(f"  - {f.name}: {lines} righe")
