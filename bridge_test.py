#!/usr/bin/env python3
"""Bridge semplificato per test diretto."""

import sys
sys.path.insert(0, '/home/vik/Documenti/progetti/my_claude_code')

from src.ollama_client import OllamaClient
from src.command_parser import CommandParser
from src.file_operations import FileOperations
import json

MODEL = "qwen3-reap"
PATH = "/home/vik/Documenti/progetti/quiz_tabelline_app"

SYSTEM = """You are a senior software architect. Answer ONLY with JSON: {"cmd1": "...", "cmd2": "..."}

PROJECT CREATION ORDER:
1. mkdir -p path
2. Create readme.md (title, description, technologies, files list, status)
3. Create source files (MAX 250 LINES EACH)
4. Update readme.md status

Use cat << 'EOF' > file for file creation. NEVER use echo for multi-line files.
"""

PROMPT = f"""Crea app web COMPLETA per tabelline (1-10) per bambina di 7 anni.
Path: {PATH}

REQUISITI DETTAGLIATI:
- UNICO file HTML con CSS e JS inline (self-contained, zero dipendenze esterne)
- Max 200 righe totali
- Titolo: "🌟 Le Tabelline di Ginevra! 🌟"
- Menu con 10 bottoni colorati, ognuno con emoji diverso (🍕🌈🎮🎨⚽🎵🦄🚀🌟🎂)
- Quiz: una domanda alla volta (es: "Quanto fa 4 × 7?")
- Input numerico grande (inputmode="numeric") per tablet
- Bottone "✅ RISPOSTA"
- Se corretta: animazione stelle, overlay verde, suono Web Audio API
- Se sbagliata: shake screen, overlay rosso, mostra risposta corretta
- Dopo 10 domande: schermata risultati con punteggio X/10
- Font: Fredoka One (Google Fonts)
- Colori vivaci, border-radius grandi, stile "bubbly"
- Responsive per tablet Android

Crea SOLO il file HTML completo. NON creare file separati CSS/JS.
Rispondi SOLO con JSON {{"cmd1": "mkdir...", "cmd2": "cat heredoc...", "cmd3": "cat heredoc readme.md..."}}
"""

print(f"🧪 Bridge semplificato - Modello: {MODEL}")
print(f"📁 Path: {PATH}\n")

client = OllamaClient(model=MODEL, options={"temperature": 0.2, "num_predict": -1})
parser = CommandParser()
ops = FileOperations()

print("📡 Chiamo LLM...")
llm_response = ""
for chunk in client.chat([{"role": "user", "content": PROMPT}], stream=True):
    llm_response += chunk
    print(".", end="", flush=True)

print(f"\n✅ Response: {len(llm_response)} chars\n")

# Salva response
from pathlib import Path
from datetime import datetime
log_dir = Path(PATH)
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / f"response_{datetime.now().strftime('%H%M%S')}.txt"
log_file.write_text(llm_response)
print(f"📝 Response salvata: {log_file}\n")

# Parsa comandi
parsed = parser.parse(llm_response)
print(f"📋 Comandi estratti: {len(parsed.commands)} (valid: {parsed.is_valid})\n")

if not parsed.is_valid:
    print(f"❌ Errore parsing: {parsed.error}")
    print(f"\nPrimi 500 chars response:\n{llm_response[:500]}")
    sys.exit(1)

# Esegue comandi
for i, cmd in enumerate(parsed.commands, 1):
    print(f"[{i}] {cmd[:70]}...")
    ok, out = ops.execute_command(cmd)
    status = "✓" if ok else "✗"
    print(f"    [{status}] {out[:100] if out else 'OK'}\n")

# Report finale
print("\n" + "="*50)
print("📊 FILE CREATI:")
print("="*50)
for f in sorted(Path(PATH).glob("*")):
    if f.is_file() and f.suffix != '.txt':
        lines = len(f.read_text().split('\n'))
        print(f"  {f.name}: {lines} righe")
