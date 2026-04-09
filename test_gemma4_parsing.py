#!/usr/bin/env python3
"""
Test delle 3 funzionalità principali (/new, /fix, /reverse) con Gemma 4 via Ollama.
Focus: identificare e diagnosticare problemi di parsing nelle risposte LLM.
"""

import sys, json, time, os, shutil
from pathlib import Path
from datetime import datetime

# Assicura encoding UTF-8
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Aggiungi il path del progetto
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ollama_client import OllamaClient
from src.command_parser import CommandParser

# ── Configurazione ──────────────────────────────────────────────────────────
# Modelli Gemma4 disponibili (da ollama list)
MODELS = {
    "create": "gemma-latest-shellbot-create:latest",
    "default": "gemma-latest-shellbot:latest",
    "docs": "gemma-latest-shellbot-docs:latest",
}

OLLAMA_OPTIONS = {
    "temperature": 0.1,
    "top_p": 0.85,
    "top_k": 40,
    "repeat_penalty": 1.2,
    "repeat_last_n": 256,
    "num_ctx": 8192,
    "num_predict": 2048,
    "num_thread": 8,
}

# Directory di test
TEST_DIR = PROJECT_ROOT / "test_output_gemma4"
TEST_DIR.mkdir(exist_ok=True)

# Log dettagliato
LOG_FILE = TEST_DIR / f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

# ── Utilities ────────────────────────────────────────────────────────────────
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GRAY = "\033[38;5;245m"
    MAGENTA = "\033[35m"

def header(text):
    print(f"\n{'='*70}")
    print(f"  {Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{'='*70}\n")

def status(msg, level="info"):
    icons = {
        "info": f"{Colors.BLUE}ℹ{Colors.RESET}",
        "ok": f"{Colors.GREEN}✓{Colors.RESET}",
        "warn": f"{Colors.YELLOW}⚠{Colors.RESET}",
        "error": f"{Colors.RED}✗{Colors.RESET}",
        "test": f"{Colors.MAGENTA}🧪{Colors.RESET}",
    }
    icon = icons.get(level, icons["info"])
    print(f"  {icon} {msg}")

def call_llm(client: OllamaClient, messages: list[dict], label: str) -> tuple[str, float]:
    """Chiama l'LLM e ritorna (response, elapsed_seconds)."""
    status(f"Chiamata LLM ({label})...", "test")
    t0 = time.time()
    response = ""
    try:
        for chunk in client.chat(messages, stream=True):
            response += chunk
    except Exception as e:
        status(f"Errore LLM: {e}", "error")
        return f"ERROR: {e}", time.time() - t0
    elapsed = time.time() - t0
    status(f"Response ricevuta: {len(response)} chars in {elapsed:.1f}s", "ok")
    return response, elapsed

def analyze_parsing(parser: CommandParser, raw_response: str, test_name: str) -> dict:
    """Analizza il parsing di una response e ritorna diagnostica dettagliata."""
    result = {
        "test_name": test_name,
        "raw_response_len": len(raw_response),
        "raw_response_preview": raw_response[:500],
        "raw_response_full": raw_response,
        "parsing_success": False,
        "commands_count": 0,
        "commands": [],
        "error": None,
        "diagnostics": {},
    }

    # Diagnostica pre-parsing
    diag = result["diagnostics"]
    diag["starts_with_brace"] = raw_response.strip().startswith("{")
    diag["ends_with_brace"] = raw_response.strip().endswith("}")
    diag["has_code_block"] = "```" in raw_response
    diag["has_think_tags"] = "<think>" in raw_response.lower()
    diag["has_cmd_keys"] = bool(parser.CMD_START_PATTERN.search(raw_response))
    diag["has_loose_cmd_keys"] = bool(parser.LOOSE_CMD_START_PATTERN.search(raw_response))
    diag["has_smart_quotes"] = any(c in raw_response for c in '\u201c\u201d\u201e\u201f\u2018\u2019')
    diag["has_en_dash"] = '\u2013' in raw_response or '\u2014' in raw_response
    diag["has_double_colon"] = '::' in raw_response or ':  :' in raw_response
    diag["has_bash_heredoc"] = "cat <<" in raw_response or "cat << " in raw_response
    diag["has_markdown_fence"] = raw_response.strip().startswith("```")
    diag["brace_count_open"] = raw_response.count("{")
    diag["brace_count_close"] = raw_response.count("}")
    diag["brace_balanced"] = raw_response.count("{") == raw_response.count("}")

    # Cerca caratteri problematici
    problematic_chars = {}
    for i, c in enumerate(raw_response):
        if ord(c) > 127 and c not in '\n\r\t':
            char_name = f"U+{ord(c):04X}"
            if char_name not in problematic_chars:
                problematic_chars[char_name] = {"char": repr(c), "positions": [], "count": 0}
            problematic_chars[char_name]["count"] += 1
            if len(problematic_chars[char_name]["positions"]) < 3:
                problematic_chars[char_name]["positions"].append(i)
    diag["problematic_chars"] = problematic_chars

    # Parsing
    parsed = parser.parse(raw_response)
    result["parsing_success"] = parsed.is_valid
    result["commands_count"] = len(parsed.commands)
    result["commands"] = [cmd[:300] for cmd in parsed.commands]  # troncati per il log
    result["error"] = parsed.error

    # Mostra risultato
    if parsed.is_valid:
        status(f"Parsing OK: {len(parsed.commands)} comandi estratti", "ok")
        for i, cmd in enumerate(parsed.commands, 1):
            print(f"    {Colors.GREEN}cmd{i}:{Colors.RESET} {Colors.GRAY}{cmd[:120]}{'...' if len(cmd) > 120 else ''}{Colors.RESET}")
    else:
        status(f"Parsing FALLITO: {parsed.error}", "error")
        print(f"    {Colors.RED}Response (primi 400 chars):{Colors.RESET}")
        for line in raw_response[:400].split('\n'):
            print(f"    {Colors.GRAY}| {line[:100]}{Colors.RESET}")

    # Mostra diagnostica problemi
    issues = []
    if diag["has_smart_quotes"]:
        issues.append("Smart quotes rilevate (tipographic quotes)")
    if diag["has_en_dash"]:
        issues.append("En-dash/Em-dash rilevati")
    if diag["has_double_colon"]:
        issues.append("Doppio due-punti rilevato")
    if diag["has_bash_heredoc"]:
        issues.append("Bash heredoc rilevato (dovrebbe usare PowerShell)")
    if diag["has_code_block"]:
        issues.append("Markdown code block rilevato (dovrebbe essere JSON puro)")
    if diag["has_think_tags"]:
        issues.append("<think> tags rilevati")
    if not diag["brace_balanced"]:
        issues.append(f"Graffe sbilanciate: {diag['brace_count_open']}{{ vs {diag['brace_count_close']}}}")
    if not diag["has_cmd_keys"] and not diag["has_loose_cmd_keys"]:
        issues.append("Nessuna chiave 'cmd' trovata nella response")
    if diag["problematic_chars"]:
        for cn, info in diag["problematic_chars"].items():
            issues.append(f"Carattere non-ASCII: {cn} ({info['char']}) x{info['count']}")

    result["issues"] = issues
    if issues:
        print(f"\n    {Colors.YELLOW}Problemi rilevati:{Colors.RESET}")
        for issue in issues:
            print(f"    {Colors.YELLOW}  ⚠ {issue}{Colors.RESET}")

    return result

# ═══════════════════════════════════════════════════════════════════════════
# TEST 1: /new - Creazione progetto
# ═══════════════════════════════════════════════════════════════════════════
def test_new(client: OllamaClient, parser: CommandParser) -> dict:
    """Testa /new: crea un semplice file Python."""
    header("TEST 1: /new - Creazione Progetto")

    test_path = TEST_DIR / "test_new_proj"
    test_path_str = str(test_path).replace("\\", "\\\\")

    # Usa il modello CREATE
    client.model = MODELS["create"]
    status(f"Modello: {client.model}", "info")

    prompt = f"""Crea una semplice calcolatrice in Python.
Path: {str(test_path)}

REQUISITI:
- UN SOLO file main.py con 4 operazioni (+, -, *, /)
- Max 30 righe
- Input da console

Rispondi SOLO con JSON valido:
{{"cmd1": "New-Item -ItemType Directory ...", "cmd2": "Set-Content -Path ... -Value ..."}}"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    raw_resp, elapsed = call_llm(client, messages, "/new calcolatrice")
    result = analyze_parsing(parser, raw_resp, "test_new")
    result["elapsed_seconds"] = elapsed
    result["model"] = client.model
    return result

# ═══════════════════════════════════════════════════════════════════════════
# TEST 2: /fix - Fix di un file esistente
# ═══════════════════════════════════════════════════════════════════════════
def test_fix(client: OllamaClient, parser: CommandParser) -> dict:
    """Testa /fix: corregge un file Python con un bug noto."""
    header("TEST 2: /fix - Fix di un Bug")

    # Crea file con bug
    fix_dir = TEST_DIR / "test_fix_proj"
    fix_dir.mkdir(exist_ok=True)
    buggy_code = '''def divide(a, b):
    return a / b  # BUG: no divisione per zero check

def main():
    a = float(input("Primo numero: "))
    b = float(input("Secondo numero: "))
    print(f"Risultato: {divide(a, b)}")

if __name__ == "__main__":
    main()
'''
    buggy_file = fix_dir / "calc.py"
    buggy_file.write_text(buggy_code, encoding="utf-8")
    status(f"File con bug creato: {buggy_file}", "info")

    # Usa il modello CREATE (per fix)
    client.model = MODELS["create"]
    status(f"Modello: {client.model}", "info")

    prompt = f"""Il file calc.py ha un bug: la funzione divide() non gestisce la divisione per zero.

FILE ATTUALE ({str(buggy_file)}):
```python
{buggy_code}
```

Correggi il bug aggiungendo un controllo per divisione per zero.
Riscrivi il file intero con il fix.

Rispondi SOLO con JSON:
{{"cmd1": "Set-Content -Path '{str(buggy_file)}' -Value '...codice corretto...'"}}"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    raw_resp, elapsed = call_llm(client, messages, "/fix divisione per zero")
    result = analyze_parsing(parser, raw_resp, "test_fix")
    result["elapsed_seconds"] = elapsed
    result["model"] = client.model
    return result

# ═══════════════════════════════════════════════════════════════════════════
# TEST 3: /reverse - Generazione documentazione
# ═══════════════════════════════════════════════════════════════════════════
def test_reverse(client: OllamaClient, parser: CommandParser) -> dict:
    """Testa /reverse: genera documentazione da codice sorgente."""
    header("TEST 3: /reverse - Generazione Documentazione")

    # Crea un mini progetto da documentare
    rev_dir = TEST_DIR / "test_reverse_proj"
    rev_dir.mkdir(exist_ok=True)

    # File main.py
    main_code = '''"""Mini gestionale per biblioteca."""

class Book:
    def __init__(self, title: str, author: str, isbn: str):
        self.title = title
        self.author = author
        self.isbn = isbn
        self.available = True

    def __str__(self):
        status = "Disponibile" if self.available else "Prestato"
        return f"{self.title} di {self.author} [{status}]"

class Library:
    def __init__(self):
        self.books = []

    def add_book(self, book: Book):
        self.books.append(book)

    def search(self, query: str) -> list[Book]:
        return [b for b in self.books if query.lower() in b.title.lower()]

    def lend(self, isbn: str) -> bool:
        for b in self.books:
            if b.isbn == isbn and b.available:
                b.available = False
                return True
        return False

    def return_book(self, isbn: str) -> bool:
        for b in self.books:
            if b.isbn == isbn and not b.available:
                b.available = True
                return True
        return False

def main():
    lib = Library()
    lib.add_book(Book("Il Nome della Rosa", "Umberto Eco", "978-88"))
    lib.add_book(Book("La Divina Commedia", "Dante Alighieri", "978-99"))
    print("Biblioteca inizializzata con", len(lib.books), "libri")

if __name__ == "__main__":
    main()
'''
    (rev_dir / "main.py").write_text(main_code, encoding="utf-8")
    status(f"Progetto di test creato: {rev_dir}", "info")

    # Usa il modello DOCS
    client.model = MODELS["docs"]
    status(f"Modello: {client.model}", "info")

    doc_path = str(rev_dir / "DOCUMENTAZIONE.md")

    prompt = f"""Sei un technical writer. Genera documentazione per questo progetto Python.

STRUTTURA:
test_reverse_proj/
└── main.py

CONTENUTO main.py:
```python
{main_code}
```

Genera DOCUMENTAZIONE.md in ITALIANO (minimo 300 parole).
Sezioni: PANORAMICA, STRUTTURA, FILE PRINCIPALI, FLUSSO, API, CONFIGURAZIONE, NOTE.

Rispondi SOLO con JSON:
{{"cmd1": "Set-Content -Path '{doc_path}' -Value '# DOCUMENTAZIONE - Biblioteca\\n\\n## 1. PANORAMICA\\n...'"}}"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    raw_resp, elapsed = call_llm(client, messages, "/reverse documentazione")
    result = analyze_parsing(parser, raw_resp, "test_reverse")
    result["elapsed_seconds"] = elapsed
    result["model"] = client.model
    return result

# ═══════════════════════════════════════════════════════════════════════════
# TEST 4: Parsing edge cases - simulazione di risposte tipiche di Gemma4
# ═══════════════════════════════════════════════════════════════════════════
def test_parsing_edge_cases(parser: CommandParser) -> list[dict]:
    """Testa il parser con risposte tipiche problematiche di Gemma4."""
    header("TEST 4: Parsing Edge Cases (simulazione)")

    test_cases = [
        {
            "name": "smart_quotes",
            "input": '{\u201ccmd1\u201d: \u201cNew-Item -ItemType Directory -Force -Path \u2018C:\\\\proj\u2019\u201d}',
            "description": "Gemma4 usa smart quotes invece di ASCII quotes",
        },
        {
            "name": "double_colon",
            "input": '{"cmd1":  : "New-Item -ItemType Directory -Force -Path \'proj\'"}',
            "description": "Gemma4 mette doppio due-punti dopo la chiave",
        },
        {
            "name": "en_dash_in_flags",
            "input": '{"cmd1": "New-Item \u2013ItemType Directory \u2013Force \u2013Path \'proj\'"}',
            "description": "Gemma4 usa en-dash al posto del trattino nei flag",
        },
        {
            "name": "markdown_wrapped",
            "input": '```json\n{"cmd1": "Set-Content -Path \'file.py\' -Value \'print(hello)\'"}\n```',
            "description": "Gemma4 wrappa il JSON in markdown code block",
        },
        {
            "name": "text_before_json",
            "input": 'Ecco i comandi per creare il progetto:\n\n{"cmd1": "New-Item -ItemType Directory -Force -Path \'proj\'", "cmd2": "Set-Content -Path \'proj\\\\main.py\' -Value \'print(1)\'"}',
            "description": "Gemma4 mette testo esplicativo prima del JSON",
        },
        {
            "name": "wrong_keys",
            "input": '{"cmdhtml": "Set-Content -Path \'index.html\' -Value \'<html></html>\'", "cmdcss": "Set-Content -Path \'style.css\' -Value \'body{}\'"}',
            "description": "Gemma4 usa nomi descrittivi invece di cmd1/cmd2",
        },
        {
            "name": "think_tags",
            "input": '<think>Devo creare una calcolatrice...</think>\n{"cmd1": "New-Item -ItemType Directory -Force -Path \'calc\'", "cmd2": "Set-Content -Path \'calc\\\\main.py\' -Value \'print(1+2)\'"}',
            "description": "Gemma4 include thinking tags",
        },
        {
            "name": "unclosed_string",
            "input": '{"cmd1": "Set-Content -Path \'file.py\' -Value \'def hello():\nprint("hello")\n\', "cmd2": "Set-Content -Path \'test.py\' -Value \'import file\'"}',
            "description": "Gemma4 non chiude correttamente le stringhe con newline",
        },
        {
            "name": "bash_heredoc_on_windows",
            "input": '{"cmd1": "mkdir -p /home/user/proj", "cmd2": "cat << \'EOF\' > /home/user/proj/main.py\nprint(\\"hello\\")\nEOF"}',
            "description": "Gemma4 usa bash heredoc su Windows (dovrebbe usare PowerShell)",
        },
        {
            "name": "truncated_json",
            "input": '{"cmd1": "New-Item -ItemType Directory -Force -Path \'proj\'", "cmd2": "Set-Content -Path \'proj\\\\main.py\' -Value \'def main():\\n    pri',
            "description": "Response troncata a metà del JSON",
        },
        {
            "name": "mixed_issues",
            "input": '```json\n{\u201ccmd1\u201d:  : \u201cNew-Item \u2013ItemType Directory \u2013Force \u2013Path \u2018proj\u2019\u201d}\n```',
            "description": "Combinazione: markdown + smart quotes + double colon + en-dash",
        },
    ]

    results = []
    for tc in test_cases:
        print(f"\n  {Colors.MAGENTA}🧪 {tc['name']}{Colors.RESET}: {tc['description']}")
        result = analyze_parsing(parser, tc["input"], tc["name"])
        result["description"] = tc["description"]
        result["is_edge_case_test"] = True
        results.append(result)

    return results

# ═══════════════════════════════════════════════════════════════════════════
# MAIN - Esegui tutti i test
# ═══════════════════════════════════════════════════════════════════════════
def main():
    header("TEST GEMMA4 - Parsing e Funzionalità /new /fix /reverse")

    # Verifica connessione Ollama
    client = OllamaClient(
        base_url="http://localhost:11434",
        model=MODELS["create"],
        timeout=600,
        options=OLLAMA_OPTIONS,
    )

    status("Verifico connessione Ollama...", "test")
    if not client.is_available():
        status("Ollama non disponibile!", "error")
        status("Avvia Ollama con: ollama serve", "info")
        sys.exit(1)
    status("Ollama connesso", "ok")

    # Verifica modelli
    available_models = client.list_models()
    status(f"Modelli disponibili: {len(available_models)}", "info")
    for model_key, model_name in MODELS.items():
        found = model_name in available_models or model_name.replace(":latest", "") in [m.replace(":latest", "") for m in available_models]
        tag = "ok" if found else "error"
        status(f"  {model_key}: {model_name} {'✓' if found else '✗ NON TROVATO'}", tag)
        if not found:
            status(f"  Modello {model_name} non disponibile. Disponibili: {available_models}", "warn")

    parser = CommandParser()
    all_results = {"timestamp": datetime.now().isoformat(), "tests": {}}

    # ── Test 1-3: Chiamate LLM reali ────────────────────────────────────────
    try:
        r1 = test_new(client, parser)
        all_results["tests"]["test_new"] = r1
    except Exception as e:
        status(f"Test /new fallito con eccezione: {e}", "error")
        all_results["tests"]["test_new"] = {"error": str(e), "parsing_success": False}

    try:
        r2 = test_fix(client, parser)
        all_results["tests"]["test_fix"] = r2
    except Exception as e:
        status(f"Test /fix fallito con eccezione: {e}", "error")
        all_results["tests"]["test_fix"] = {"error": str(e), "parsing_success": False}

    try:
        r3 = test_reverse(client, parser)
        all_results["tests"]["test_reverse"] = r3
    except Exception as e:
        status(f"Test /reverse fallito con eccezione: {e}", "error")
        all_results["tests"]["test_reverse"] = {"error": str(e), "parsing_success": False}

    # ── Test 4: Edge cases di parsing (senza LLM) ──────────────────────────
    edge_results = test_parsing_edge_cases(parser)
    all_results["tests"]["edge_cases"] = edge_results

    # ── Report finale ───────────────────────────────────────────────────────
    header("REPORT FINALE")

    llm_tests = ["test_new", "test_fix", "test_reverse"]
    total_llm = len(llm_tests)
    passed_llm = sum(1 for t in llm_tests if all_results["tests"].get(t, {}).get("parsing_success", False))

    total_edge = len(edge_results)
    passed_edge = sum(1 for r in edge_results if r.get("parsing_success", False))

    print(f"\n  {Colors.BOLD}Test LLM (chiamate reali a Gemma4):{Colors.RESET}")
    for t in llm_tests:
        tr = all_results["tests"].get(t, {})
        ok = tr.get("parsing_success", False)
        cmds = tr.get("commands_count", 0)
        elapsed = tr.get("elapsed_seconds", 0)
        icon = f"{Colors.GREEN}✓{Colors.RESET}" if ok else f"{Colors.RED}✗{Colors.RESET}"
        print(f"    {icon} {t}: {'PASS' if ok else 'FAIL'} ({cmds} comandi, {elapsed:.1f}s)")
        if not ok and tr.get("error"):
            print(f"        {Colors.RED}Errore: {tr['error']}{Colors.RESET}")
        if tr.get("issues"):
            for issue in tr["issues"]:
                print(f"        {Colors.YELLOW}⚠ {issue}{Colors.RESET}")

    print(f"\n  {Colors.BOLD}Test Edge Cases (parsing locale):{Colors.RESET}")
    for r in edge_results:
        ok = r.get("parsing_success", False)
        icon = f"{Colors.GREEN}✓{Colors.RESET}" if ok else f"{Colors.RED}✗{Colors.RESET}"
        print(f"    {icon} {r['test_name']}: {'PASS' if ok else 'FAIL'}")
        if not ok and r.get("error"):
            print(f"        {Colors.RED}Errore: {r['error']}{Colors.RESET}")

    print(f"\n  {Colors.BOLD}Riepilogo:{Colors.RESET}")
    print(f"    Test LLM:        {passed_llm}/{total_llm}")
    print(f"    Test Edge Cases: {passed_edge}/{total_edge}")
    print(f"    TOTALE:          {passed_llm + passed_edge}/{total_llm + total_edge}")

    # Salva risultati
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    status(f"Risultati salvati: {LOG_FILE}", "ok")

    # Calcola sommario problemi ricorrenti
    all_issues = []
    for t in llm_tests:
        tr = all_results["tests"].get(t, {})
        all_issues.extend(tr.get("issues", []))

    if all_issues:
        print(f"\n  {Colors.BOLD}{Colors.YELLOW}Problemi ricorrenti nelle risposte Gemma4:{Colors.RESET}")
        from collections import Counter
        for issue, count in Counter(all_issues).most_common():
            print(f"    {Colors.YELLOW}[{count}x] {issue}{Colors.RESET}")

    return passed_llm + passed_edge, total_llm + total_edge

if __name__ == "__main__":
    passed, total = main()
    sys.exit(0 if passed == total else 1)
