#!/usr/bin/env python3
"""Script per testare tutti e 4 i modelli con lo stesso prompt."""

import json
import requests
import subprocess
import re
from pathlib import Path
from datetime import datetime

BASE_PATH = Path("/home/vik/Documenti/progetti")
BASE_URL = "http://localhost:11434"

MODELS = [
    {"name": "qwen3-12b", "folder": "quiz_tabelline_qwen3-12b"},
    {"name": "qwen3-30b", "folder": "quiz_tabelline_qwen3-30b"},
    {"name": "qwen3-reap", "folder": "quiz_tabelline_reap"},
]

PROMPT = """Crea app web per tabelline (1-10) per bambina di 7 anni. Grafica vivace, emoji, animazioni CSS. 
Path: {path}. Max 200 righe/file. HTML self-contained, vanilla JS, Web Audio API per suoni.
Menu con 10 bottoni colorati, quiz una domanda alla volta, feedback animato, risultati finali.

Rispondi SOLO con JSON valido in questo formato:
{{"cmd1": "mkdir -p /path", "cmd2": "cat << 'EOF' > file...EOF", "cmd3": ...}}

NON scrivere spiegazioni, NON usare tag <think>, SOLO JSON con comandi shell."""


def remove_thinking(text):
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)


def extract_commands(response):
    response = remove_thinking(response).strip()
    
    # 1. Cerca JSON in code block
    match = re.search(r'```(?:json)?\s*\n?({.+?})\s*\n?```', response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return [data[k] for k in sorted(data.keys()) if k.startswith('cmd')]
        except: pass
    
    # 2. Cerca JSON inline - trova tutto da {"cmd a } finale
    # Usa un approccio diverso: conta le parentesi
    if '{"cmd' in response:
        start = response.find('{"cmd')
        depth = 0
        in_string = False
        escape_next = False
        end = start
        
        for i in range(start, len(response)):
            c = response[i]
            if escape_next:
                escape_next = False
            elif c == '\\':
                escape_next = True
            elif c == '"' and not escape_next:
                in_string = not in_string
            elif not in_string:
                if c == '{':
                    depth += 1
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
            print(f"  Parser error: {e}")
    
    return []


def execute_commands(commands, cwd):
    results = []
    for i, cmd in enumerate(commands, 1):
        cmd = cmd.replace('$HOME', str(Path.home())).replace('\\n', '\n')
        try:
            result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=60)
            results.append({"cmd": cmd[:50]+"...", "success": result.returncode==0, "error": result.stderr[:200] if result.stderr else None})
        except Exception as e:
            results.append({"cmd": cmd[:50]+"...", "success": False, "error": str(e)})
    return results


def test_model(model_config):
    model_name = model_config["name"]
    folder = model_config["folder"]
    path = BASE_PATH / folder
    print(f"\n{'='*60}\n🧪 Testing: {model_name} → {folder}\n{'='*60}\n")
    path.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(path=path)
    
    try:
        response = requests.post(f"{BASE_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False, "options": {"temperature": 0.2, "num_predict": -1}},
            timeout=300)  # 5 minuti per modello
        response.raise_for_status()
        llm_response = response.json()["response"]
    except Exception as e:
        print(f"❌ Errore API: {e}")
        return {"model": model_name, "error": str(e)}
    
    log_file = path / f"response_{datetime.now().strftime('%H%M%S')}.txt"
    log_file.write_text(llm_response)
    print(f"📝 Raw response salvata: {log_file}")
    
    commands = extract_commands(llm_response)
    print(f"📋 {len(commands)} comandi estratti")
    
    if not commands:
        print("⚠️ Nessun comando trovato!")
        return {"model": model_name, "commands_found": 0, "raw_response": llm_response[:500]}
    
    results = execute_commands(commands, str(path))
    success = sum(1 for r in results if r["success"])
    print(f"\n✅ {success}/{len(results)} comandi eseguiti")
    
    for r in results:
        icon = "✓" if r["success"] else "✗"
        print(f"  [{icon}] {r['cmd']}")
        if r["error"]: print(f"      Errore: {r['error'][:100]}")
    
    files = list(path.glob("*.html"))
    print(f"\n📁 File HTML creati: {len(files)}")
    for f in files:
        lines = len(f.read_text().split('\n'))
        print(f"  - {f.name} ({lines} righe)")
    
    return {"model": model_name, "commands_found": len(commands), "commands_success": success,
            "files_created": len(files), "html_files": [(f.name, len(f.read_text().split('\n'))) for f in files]}


def main():
    print("🚀 Test modelli per Quiz Tabelline\n")
    results = []
    for i, model in enumerate(MODELS):
        result = test_model(model)
        results.append(result)
        if i < len(MODELS) - 1:
            print(f"\n⏸️ Pausa 5 secondi prima del prossimo modello...")
            import time
            time.sleep(5)
    
    print("\n" + "="*60 + "\n📊 RIEPILOGO FINALE\n" + "="*60)
    for r in results:
        print(f"\n{r['model']}:")
        if "error" in r:
            print(f"  ❌ Errore: {r['error']}")
        else:
            print(f"  Comandi: {r.get('commands_found',0)} trovati, {r.get('commands_success',0)} eseguiti")
            print(f"  File HTML: {r.get('files_created',0)}")
            for name, lines in r.get('html_files',[]):
                print(f"    - {name}: {lines} righe")


if __name__ == "__main__":
    main()
