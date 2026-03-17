#!/usr/bin/env python3
"""Ollama File System Bridge - Con logging dettagliato e fix automatico"""

import argparse, json, sys, time, threading, logging, re, subprocess, hashlib, shutil
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime
from src.ollama_client import OllamaClient
from src.file_operations import FileOperations
from src.command_parser import CommandParser
from src.session_manager import SessionManager, Session
from src.project_scanner import (
    build_tree_from_paths,
    collect_candidate_files,
    collect_candidate_files_with_stats,
    apply_reverse_policy,
    find_primary_docs,
    determine_source_roots,
    format_candidate_index,
    pick_default_files,
    extract_requested_files,
    read_files_content,
    read_files_content_with_stats,
)

LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = Path("./.ollama_bridge_state.json")
COMMAND_HISTORY = []
HISTORY_FILE = Path.home() / ".ollama_bridge_history"
REVERSE_LOG = LOG_DIR / "reverse_cli.log"

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r') as f:
                COMMAND_HISTORY.extend(json.loads(f.read()))
        except: pass

def save_history():
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(COMMAND_HISTORY[-100:], f)
    except: pass

# Logging dettagliato per request/response
REQUEST_LOG_DIR = LOG_DIR / "requests"
REQUEST_LOG_DIR.mkdir(exist_ok=True)

def log_request_response(session_id: str, request: dict, response: dict = None, error: str = None):
    """Logga request/response con timestamp."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = REQUEST_LOG_DIR / f"{session_id}_{timestamp}.json"

    log_data = {
        "timestamp": timestamp,
        "request": request,
        "response": response,
        "error": error
    }

    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)

    ts = datetime.now().strftime('%H:%M:%S')
    if response:
        logger.info(f"[{ts}] REQUEST → {len(json.dumps(request))} chars")
        logger.info(f"[{ts}] RESPONSE ← {len(json.dumps(response))} chars")
    elif error:
        logger.error(f"[{ts}] ERROR: {error}")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_DIR / f"ollama_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

class Colors:
    RESET, BOLD, DIM, RED, GREEN, YELLOW, BLUE, CYAN, WHITE, ORANGE, GRAY, MAGENTA = "\033[0m", "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m", "\033[37m", "\033[38;5;208m", "\033[38;5;245m", "\033[35m"

def banner():
    print(f"{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.CYAN}║{Colors.RESET}   OLLAMA FILE SYSTEM BRIDGE                       {Colors.CYAN}║{Colors.RESET}")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.RESET}\n")

def status(msg, s="info"):
    icons = {"info": f"{Colors.BLUE}ℹ{Colors.RESET}", "success": f"{Colors.GREEN}✓{Colors.RESET}", "warning": f"{Colors.YELLOW}⚠{Colors.RESET}", "error": f"{Colors.RED}✗{Colors.RESET}", "running": f"{Colors.ORANGE}⟳{Colors.RESET}", "testing": f"{Colors.MAGENTA}🧪{Colors.RESET}"}
    icon = icons.get(s, icons["info"])
    print(f"  {icon} {msg}")

def cmd_box(c, idx=None):
    num = f" [{idx}]" if idx else ""
    print(f"\n  {Colors.DIM}┌─{Colors.RESET}")
    print(f"  {Colors.DIM}│{Colors.RESET} {Colors.ORANGE}⚡{num}{Colors.RESET} {Colors.BOLD}{c}{Colors.RESET}")
    print(f"  {Colors.DIM}└─{Colors.RESET}")

def print_output(o):
    for l in o.split('\n')[:15]:
        print(f"  {Colors.DIM}│{Colors.RESET} {Colors.GRAY}{l[:80]}{Colors.RESET}")

def print_error(o):
    print(f"\n  {Colors.DIM}╭─ 🚨 Errore ─{Colors.RESET}")
    for l in o.split('\n')[:20]:
        print(f"  {Colors.DIM}│{Colors.RESET} {Colors.RED}{l[:80]}{Colors.RESET}")

def print_claude(c):
    print(f"\n  {Colors.DIM}╭─ CLAUDE.md ─{Colors.RESET}")
    for l in c.split('\n')[:40]:
        if '[x]' in l or '[ ]' in l:
            print(f"  {Colors.DIM}│{Colors.RESET} {Colors.YELLOW}{l}{Colors.RESET}")
        elif l.startswith('#'):
            print(f"  {Colors.DIM}│{Colors.RESET} {Colors.CYAN}{Colors.BOLD}{l}{Colors.RESET}")
        else:
            print(f"  {Colors.DIM}│{Colors.RESET} {Colors.GRAY}{l}{Colors.RESET}")
    print(f"  {Colors.DIM}╰─{Colors.RESET}\n")

class Thinking:
    FRAMES, MESSAGES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"], ["LLM pensa", "Elabora", "Analizza", "Genera"]
    def __init__(self):
        self._stop, self._thread, self._i, self._m = threading.Event(), None, 0, 0
    def _run(self):
        while not self._stop.is_set():
            print(f"\r  {Colors.ORANGE}{self.FRAMES[self._i%len(self.FRAMES)]}{Colors.RESET} {Colors.CYAN}{self.MESSAGES[self._m%len(self.MESSAGES)]}{Colors.RESET}{'.'*((self._i//10)%4)}   ", end="", flush=True)
            if self._i % 30 == 0 and self._i > 0: self._m += 1
            self._i += 1; time.sleep(0.1)
        print(f"\r  {' '*45}\r", end="", flush=True)
    def start(self): self._stop.clear(); self._thread = threading.Thread(target=self._run, daemon=True); self._thread.start()
    def stop(self): self._stop.set(); self._thread and self._thread.join(0.5)

class ClaudeContext:
    def __init__(self, d: Path):
        self.d, self.f, self._c, self._st = d, d/"CLAUDE.md", "", "attesa"
    def load(self) -> bool:
        if not self.f.exists(): return False
        try:
            self._c = self.f.read_text()
            return True
        except Exception as e: logger.error(f"Errore load CLAUDE.md: {e}"); return False
    def get(self) -> str: return self._c
    def exists(self) -> bool: return self.f.exists()
    def ctx(self) -> str:
        if not self._c:
            return f"\n\n## PATH: {self.d}"
        return f"\n\n## CLAUDE.md\n{self._c}\n\n## PATH: {self.d}"

class Tester:
    RUNNERS = {
        '.py': lambda f: f"python3 {f}",
        '.js': lambda f: f"node {f}",
        '.sh': lambda f: f"bash {f}",
        '.java': lambda f: f"cd {f.parent} && javac {f.name} && java {f.stem}"
    }
    def __init__(self, d: Path): self.d = d
    def find(self) -> Optional[Path]:
        for n in ['main','index','app','tris','tetris','game','hello','Main','Test']:
            for e in ['.py','.js','.sh','.java']:
                f = self.d / f"{n}{e}"
                if f.exists(): return f
        for e in ['.py','.js','.sh','.java']:
            for f in self.d.glob(f"*{e}"):
                if f.is_file(): return f
        for f in self.d.glob("*.class"):
            if f.is_file(): return f
        return None
    def test(self, timeout=60) -> Tuple[bool, str, str]:
        f = self.find()
        if not f: return False, "", "Nessun file .py/.js/.sh/.java/.class"
        if f.suffix.lower() == '.class':
            cmd = f"cd {f.parent} && java {f.stem}"
        else:
            cmd = self.RUNNERS.get(f.suffix.lower(), lambda x: None)(f)
        if not cmd: return True, "Non eseguibile", ""
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(self.d), timeout=timeout)
            return (r.returncode==0, r.stdout, r.stderr)
        except subprocess.TimeoutExpired: return False, "", f"Timeout {timeout}s"
        except Exception as e: return False, "", str(e)

class State:
    def __init__(self, f: Path):
        self.f, self.model, self.auto_c, self.auto_t, self.safe = f, None, True, True, True
        self._load()
    def _load(self):
        if not self.f.exists(): return
        try:
            d = json.loads(self.f.read_text())
            self.model = d.get('model'); self.auto_c = d.get('auto_c', True); self.auto_t = d.get('auto_t', True); self.safe = d.get('safe', True)
        except: pass
    def save(self):
        try: self.f.write_text(json.dumps({'model': self.model, 'auto_c': self.auto_c, 'auto_t': self.auto_t, 'safe': self.safe}, indent=2))
        except: pass

def get_input() -> str:
    print(f"\n  {Colors.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.RESET}")
    print(f"  {Colors.BOLD}Scrivi richiesta (Invio+Invio per inviare):{Colors.RESET}")
    print(f"  {Colors.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.RESET}")
    lines = []
    while True:
        try:
            line_num = len(lines) + 1
            prefix = f"  {Colors.GREEN}»{Colors.RESET} " if line_num == 1 else "    "
            line = input(prefix)
            if not line and lines:
                break
            if line:
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break
    text = '\n'.join(lines).strip()
    print(f"  {Colors.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.RESET}\n")
    if text:
        COMMAND_HISTORY.append(text)
        save_history()
    return text

def fix_python_syntax(filepath: Path) -> bool:
    if not filepath.exists() or filepath.suffix != '.py': return False
    return _fix_file_content(filepath, _fix_python_content)

def fix_java_syntax(filepath: Path) -> bool:
    if not filepath.exists() or filepath.suffix != '.java': return False
    return _fix_file_content(filepath, _fix_java_content)

def _fix_file_content(filepath: Path, fix_func) -> bool:
    if not filepath.exists(): return False
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        original = content
        content = fix_func(content)
        if content != original:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Fixato file: {filepath}")
            return True
        return False
    except Exception as e:
        logger.error(f"Errore fix {filepath}: {e}")
        return False

def _fix_python_content(content: str) -> str:
    content = re.sub(r'print\(\s*"\s*"([^"]*)"', r'print("\1"', content)
    content = re.sub(r"print\(\s*'\s*'([^']*)'", r"print('\1'", content)
    content = re.sub(r'""\s+', '"', content)
    content = re.sub(r"''\s+", "'", content)
    content = re.sub(r'\\\s*\n', '\\\n', content)
    return content

def _fix_java_content(content: str) -> str:
    content = re.sub(r'System\.out\.println\s*\(\s*\)', r'System.out.println()', content)
    content = re.sub(r'System\.out\.println\s*\(\s*"([^"]*)"', r'System.out.println("\1"', content)
    content = re.sub(r'\\\s*\n', '\\\n', content)
    return content

def fix_project_files(proj_dir: Path) -> int:
    count = 0
    for ext in ['.py', '.js', '.sh', '.java']:
        for f in proj_dir.glob(f"*{ext}"):
            if ext == '.py' and fix_python_syntax(f): count += 1
            elif ext == '.java' and fix_java_syntax(f): count += 1
            elif ext in ['.js', '.sh']:
                if _fix_file_content(f, lambda c: c.replace('\\\\n', '\\n').replace('\\\\t', '\\t')): count += 1
    return count

class Bridge:
    def __init__(self, cfg: dict, st: State, forced_model: str = None):
        self.cfg, self.st = cfg, st
        model_to_use = (
            forced_model if forced_model
            else (st.model if st.model else cfg["ollama"]["model"])
        )

        ollama_options = {
            # ── Sampling ────────────────────────────────────────────────────
            "temperature": 0.2,
            "top_p": 0.90,
            "top_k": 40,
            "repeat_penalty": 1.15,
            "repeat_last_n": 64,

            # ── Memoria GPU (RX 5700 XT 8GB) ────────────────────────────────
            "num_ctx": 8192,
            "num_batch": 512,
            "num_predict": -1,  # SENZA LIMITE: lascia lavorare LLM finché ha finito
            "num_thread": 8,
        }

        self.ollama = OllamaClient(
            cfg["ollama"]["base_url"],
            model_to_use,
            cfg["ollama"].get("timeout", 1800),
            options=ollama_options
        )

        allowed_dirs = cfg.get("safety", {}).get("allowed_directories")
        self.ops = FileOperations(
            cfg.get("working_directory", "."),
            allowed_directories=allowed_dirs if allowed_dirs else None,
            shell_override=cfg.get("shell", {}).get("override"),
            timeout=cfg.get("shell", {}).get("timeout", 30)
        )
        self.parser, self.sm = CommandParser(), SessionManager()
        self.env_info = self.ops.environment_info()
        self.command_style = self._command_style_from_env(self.env_info)
        self._env_prompt_added = False
        self.sess, self.models, self.thinking, self.log_f, self.logs = None, [], Thinking(), LOG_DIR/f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", []
        self.auto_c, self.auto_t, self.max_s, self.max_t = st.auto_c, st.auto_t, 200, 10
        self.ctx, self.proj, self.tester = None, None, None
        self._plan_done = False
        self._retry_count = 0
        self._failed_commands = []
        self._actual_path = ""
        self._last_response_hash = ""
        self._commands_executed = False
        self.mode = 'default'

    def set_mode(self, m: str):
        self.mode = m
        if m == 'fix':
            status("🔧 Modalità FIX attivata", "success")
        elif m == 'new':
            status("🆕 Modalità NEW PROJECT attivata", "success")
        elif m == 'reverse':
            status("📖 Modalità REVERSE attivata", "success")

    def _log(self, t, d): self.logs.append({"ts": datetime.now().isoformat(), "t": t, "d": d})
    def _save_logs(self): self.log_f.write_text(json.dumps(self.logs, indent=2, ensure_ascii=False))
    def _find_model(self, n) -> Optional[str]:
        nl = n.lower()
        for m in self.models:
            if m.lower()==nl or nl in m.lower(): return m
        return None

    def _extract_path(self, u) -> Optional[Path]:
        matches = re.findall(r'(/[a-zA-Z0-9_./-]+)', u)
        if matches:
            for m in reversed(matches):
                p = Path(m)
                if p.is_absolute(): return p
        m = re.search(r'(?:in|nel|nella)\s+([./a-zA-Z0-9_-]+)', u, re.I)
        if m: return Path(m.group(1))
        return None

    def _init_ctx(self, d: Path):
        self.proj, self.ctx, self.tester = d, ClaudeContext(d), Tester(d)
        self._actual_path = str(d)
        status(f"✓ Path: {d}", "info")
        if self.ctx.load():
            print_claude(self.ctx.get())

    def _create_session(self):
        self.sess = self.sm.create_session()
        self._env_prompt_added = False
        self._inject_environment_prompt()
        return self.sess

    def _environment_prompt(self) -> str:
        env = self.env_info or {}
        runner = env.get("runner")
        system = env.get("system", "?")
        if runner == "wsl":
            return f"Ambiente host: Windows con WSL. Usa comandi bash/posix. Preferisci percorsi /mnt/... o relativi (working dir: {self._actual_path or self.ops.working_directory})."
        if runner == "bash":
            return f"Ambiente host: {system} con bash disponibile. Usa sintassi bash standard; evita percorsi Windows con backslash."
        if runner == "powershell":
            return ("Ambiente host: Windows solo PowerShell. NON usare 'cat << 'EOF''. "
                    "Per creare file multi-line usa: Set-Content -Path <file> -Value @'... '@; "
                    "per directory usa New-Item -ItemType Directory -Force.")
        if runner == "cmd":
            return ("Ambiente host: Windows cmd.exe (nessun bash). Usa comandi compatibili o richiamando "
                    "PowerShell con \"powershell -Command ...\" per file multi-line.")
        return f"Ambiente host: {system} (bash). Usa comandi POSIX standard."

    def _filter_shellbot(self, models: list[str]) -> list[str]:
        """Ritorna solo i modelli shellbot."""
        return [m for m in models if "shellbot" in m.lower()]

    def _inject_environment_prompt(self):
        if not self.sess or self._env_prompt_added:
            return
        prompt = self._environment_prompt()
        if prompt:
            self.sess.add_message("user", prompt)
            self._env_prompt_added = True

    def _show_environment(self):
        env = self.env_info or {}
        runner = env.get("runner", "?")
        desc = env.get("description", "shell sconosciuta")
        status(f"OS: {env.get('system', '?')} | Shell: {desc}", "info")
        if runner == "wsl":
            status("Esecuzione comandi tramite WSL bash", "info")
        elif runner == "bash":
            status("Bash disponibile: comandi POSIX OK", "success")
        elif runner == "powershell":
            status("PowerShell: usare cmdlet (Set-Content, New-Item) per file/dir", "warning")
        elif runner == "cmd":
            status("Fallback cmd.exe: comandi bash potrebbero fallire", "warning")

    def _reverse_log(self, msg: str):
        try:
            REVERSE_LOG.parent.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(REVERSE_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def _command_style_from_env(self, env: dict) -> str:
        runner = (env or {}).get("runner", "")
        if runner in {"powershell", "cmd"}:
            return "powershell"
        return "posix"

    def _sanitize_model_name(self, name: str) -> str:
        if not name:
            return ""
        safe = re.sub(r'[^a-zA-Z0-9._-]+', '-', name.strip())
        safe = re.sub(r'-{2,}', '-', safe).strip('-').lower()
        return safe

    def _shellbot_target_name(self, model: str) -> str:
        base = self._sanitize_model_name(model)
        return f"{base}-shellbot" if base else ""

    def _target_exists(self, models: set[str], target: str, target_with_tag: str) -> bool:
        lowered = {m.lower() for m in models}
        return target.lower() in lowered or target_with_tag.lower() in lowered

    def _run_ollama_create(self, target_with_tag: str, modelfile_path: Path) -> tuple[bool, str]:
        exe = shutil.which("ollama") or "ollama"
        try:
            result = subprocess.run(
                [exe, "create", target_with_tag, "-f", str(modelfile_path)],
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return (result.returncode == 0, output.strip())
        except Exception as e:
            return (False, f"Errore: {e}")

    def _load_template_modelfile(self) -> Optional[str]:
        candidates: List[Path] = []
        if self.command_style == "powershell":
            candidates += [
                Path("modelfiles/Modelfile_windows"),
                Path("Modelfile_windows"),
                Path("modelfiles/Modelfile_powershell"),
                Path("Modelfile_powershell"),
            ]
        candidates += [Path("Modelfile"), Path("modelfiles/Modelfile")]
        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    return path.read_text()
                except Exception as e:
                    logger.error(f"Errore lettura {path}: {e}")
        return None

    def _write_temp_modelfile(self, template: str, base_model: str, slug: str) -> Path:
        tmp_dir = LOG_DIR / "modelfile_auto"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        content = re.sub(r'^\s*FROM\s+.+$', f"FROM {base_model}", template, count=1, flags=re.MULTILINE)
        style = self.command_style or "posix"
        tmp_path = tmp_dir / f"Modelfile_{slug}_{style}"
        tmp_path.write_text(content, encoding='utf-8')
        return tmp_path

    def _get_installed_models(self) -> set[str]:
        models = set()
        try:
            models.update(self.ollama.list_models())
        except Exception as e:
            logger.error(f"list_models API error: {e}")
        ok, out = self.ops.execute_command("ollama list", timeout=60)
        if ok and out:
            status("📄 ollama list", "info")
            print_output(out)
            for line in out.splitlines():
                parts = line.split()
                if not parts or parts[0].lower() == "name":
                    continue
                models.add(parts[0])
        elif out:
            status(f"ollama list fallito: {out}", "warning")
        return models

    def _auto_convert_models(self):
        template = self._load_template_modelfile()
        if not template:
            status("Nessun Modelfile trovato per conversione automatica", "warning")
            return

        installed = self._get_installed_models()
        if not installed:
            status("Nessun modello locale trovato da ollama", "warning")
            return

        conversions = 0
        for model in sorted(installed):
            if "shellbot" in model.lower():
                continue
            target = self._shellbot_target_name(model)
            if not target:
                continue
            target_with_tag = f"{target}:latest"
            if self._target_exists(installed, target, target_with_tag):
                continue

            slug = self._sanitize_model_name(model)[:120]
            temp_path = self._write_temp_modelfile(template, model, slug)
            status(f"Converto {model} → {target_with_tag}", "running")
            ok, out = self._run_ollama_create(target_with_tag, temp_path)
            if ok:
                status(f"Creato {target_with_tag}", "success")
                installed.add(target_with_tag)
                conversions += 1
            else:
                status(f"Errore conversione {target_with_tag}", "error")
                logger.error(out)

        if conversions == 0:
            status("Nessuna conversione necessaria", "info")
        else:
            status(f"Conversioni completate: {conversions}", "success")
    def init(self) -> bool:
        banner()
        self._show_environment()
        status("Ollama...", "running")
        if not self.ollama.is_available():
            status("Ollama OFF!", "error"); print(f"  {Colors.DIM}$ ollama serve{Colors.RESET}\n"); return False
        self._auto_convert_models()
        self.models = self.ollama.list_models()
        shell_models = self._filter_shellbot(self.models)
        self.models = shell_models
        if shell_models:
            if self.ollama.model not in shell_models:
                self.ollama.model = shell_models[0]
                status(f"Modello impostato su {self.ollama.model} (solo shellBot)", "info")
        else:
            status("Nessun modello shellBot trovato (creane uno con autoconversione)", "warning")
        status("Ollama OK", "success")
        status(f"Modello: {Colors.BOLD}{self.ollama.model}{Colors.RESET}", "info")
        if self.models:
            status(f"Modelli: {len(self.models)}", "success")
            print(f"  {Colors.DIM}╭─{Colors.RESET}")
            for i, m in enumerate(self.models[:5], 1):
                cur = m == self.ollama.model
                print(f"  {Colors.DIM}│{Colors.RESET} {Colors.GREEN}►{Colors.RESET} {Colors.BOLD}{m}{Colors.RESET}" if cur else f"  {Colors.DIM}│{Colors.RESET} {i}. {Colors.GRAY}{m}{Colors.RESET}")
            print(f"  {Colors.DIM}╰─{Colors.RESET}\n")
        self._create_session()
        status(f"Sessione: {self.sess.id}", "success")
        print(f"  {Colors.DIM}═══════════════════════════════════════════════════════════{Colors.RESET}")
        print(f"  {Colors.GRAY}Comandi: /help /fix /new /reverse /model /safe /auto /test /context /exit{Colors.RESET}")
        print(f"  {Colors.DIM}═══════════════════════════════════════════════════════════{Colors.RESET}\n")
        return True

    def change_model(self, n) -> bool:
        m = self._find_model(n)
        if not m: status(f"'{n}' non trovato", "error"); return False
        self.ollama.model = m; self.st.model = m; self.st.save()
        status(f"Modello: {Colors.BOLD}{m}{Colors.RESET}", "success"); return True

    def _execute_commands(self, commands: List[str]) -> Tuple[int, List[Tuple[int, str, str]]]:
        success_count = 0
        failures = []
        filtered_commands = []
        for cmd in commands:
            # Blocca sempre creazione README.md - usa solo claude.md
            create_readme = re.search(r'>\s*[/\w-]*README\.md', cmd, re.IGNORECASE)
            if create_readme:
                status("⛔ Saltato: README.md non creato (usa solo claude.md)", "warning")
                continue
            
            filtered_commands.append(cmd)
        for i, cmd in enumerate(filtered_commands, 1):
            cmd_box(cmd, i)
            ok, out = self.ops.execute_command(cmd)
            if ok:
                if out: print_output(out)
                status(f"✓ Comando {i} eseguito", "success")
                success_count += 1
            else:
                status(f"✗ Comando {i} fallito: {out}", "error")
                failures.append((i, cmd, out))
        self._commands_executed = success_count > 0
        if success_count > 0 and self.proj:
            fixed = fix_project_files(self.proj)
            if fixed > 0:
                status(f"🔧 Fixati {fixed} file", "success")
        return success_count, failures

    def _test(self) -> bool:
        if not self.auto_t or not self.tester: return True
        status("🧪 Test...", "testing")
        max_fix_attempts = 3
        fix_attempts = 0
        for i in range(1, self.max_t+1):
            ok, o, e = self.tester.test()
            if ok:
                status(f"✓ Test OK ({i})", "success")
                return True
            status(f"✗ Errore ({i}/{self.max_t})", "error")
            print_error(e or o)
            if i >= self.max_t or fix_attempts >= max_fix_attempts:
                return False
            fix_attempts += 1
            self._create_session()
            current_content = ""
            test_file = self.tester.find()
            if test_file and test_file.exists():
                current_content = test_file.read_text()
            prompt = f"""Il file ha errori di sintassi Python:

ERRORE: {e or o}

PATH: {self._actual_path}

FILE ATTUALE:
{current_content}

Riscrivi il file intero corretto usando UN SOLO comando:
cat << 'EOF' > {test_file}
[contenuto completo del file corretto]
EOF

Non usare comandi sed o patch parziali. Riscrivi TUTTO il file."""
            self.sess.add_message("user", prompt)
            try:
                self.thinking.start()
                llm = ""
                for chunk in self.ollama.chat(self.sess.to_ollama_messages(), stream=True):
                    llm += chunk
                self.thinking.stop()
                p = self.parser.parse(llm)
                if p.is_valid and p.commands:
                    status(f"🔧 Tentativo fix ({fix_attempts}/{max_fix_attempts})", "running")
                    self._execute_commands(p.commands[:1])
            except Exception as e:
                logger.exception(f"Fix err: {e}")
                return False
        return False

    def _files(self) -> str:
        if not self.proj: return ""
        return "\n".join(str(f.relative_to(self.proj)) for f in self.proj.rglob("*") if f.is_file())[:400]

    def _read_file_context(self, max_files: int = 10) -> str:
        if not self.proj or not self.proj.exists():
            return ""
        code_files = []
        for ext in ['.py', '.js', '.html', '.css', '.java', '.sh', '.ts', '.jsx', '.tsx']:
            code_files.extend(self.proj.glob(f"*{ext}"))
        if not code_files:
            return ""
        claude_md = self.proj / "claude.md"
        claude_content = ""
        if claude_md.exists():
            try:
                claude_content = f"## claude.md (storico fix):\n```\n{claude_md.read_text()[:800]}\n```\n\n"
            except:
                pass
        context = "## File esistenti nel progetto (LEGGERE PRIMA DI FIXARE):\n\n"
        context += claude_content
        for f in code_files[:max_files]:
            try:
                content = f.read_text()
                if len(content) > 800:
                    content = content[:800] + "\n... (troncato - file lungo)"
                context += f"### {f.name}:\n```\n{content}\n```\n\n"
            except Exception as e:
                logger.error(f"Errore lettura {f}: {e}")
        return context

    def _update_claude_md_fix(self, user_request: str):
        if not self.proj: return
        claude_md = self.proj / "claude.md"
        today = datetime.now().strftime("%Y-%m-%d")
        fix_entry = f"- [v] Fix: {user_request[:100]} ({today})\n"
        try:
            if claude_md.exists():
                with open(claude_md, 'a', encoding='utf-8') as f:
                    f.write(fix_entry)
            else:
                with open(claude_md, 'w', encoding='utf-8') as f:
                    f.write(f"# Fix History\n\n{fix_entry}")
            status("📝 claude.md aggiornato", "success")
        except Exception as e:
            logger.error(f"Errore update claude.md: {e}")

    def _done(self, t) -> bool:
        return any(p in t.lower() for p in ["task completato","completato","fatto","completed","finished","done"])

    def chat(self, u) -> str:
        if not self.sess: return "Err"
        p = self._extract_path(u)
        if p and p != self.proj:
            self._init_ctx(p)
            self._plan_done = False
            self._failed_commands = []
            self._last_response_hash = ""
            self._commands_executed = False
        iteration = 0
        max_iterations = 8
        consecutive_duplicates = 0
        max_consecutive_duplicates = 3
        is_fix_request = any(word in u.lower() for word in ['fix', 'fixa', 'correggi', 'bug', 'errore', 'non funziona', 'modifica', 'aggiorna'])
        if self.mode == 'default':
            if is_fix_request:
                self.mode = 'fix'
            elif any(word in u.lower() for word in ['crea', 'nuovo', 'new', 'inizializza', 'setup']):
                self.mode = 'new'
        while iteration < max_iterations:
            iteration += 1
            if not self._plan_done:
                self._plan_done = True
                self._create_session()
                if (is_fix_request or self.mode == 'fix') and self.proj and self.proj.exists():
                    file_ctx = self._read_file_context()
                    if file_ctx:
                        self.sess.add_message("user", f"## Contesto: devo fixare un progetto esistente.\n\n{file_ctx}")
                        self.sess.add_message("user", f"## Task: {u}\n\nISTRUZIONI:\n1. Analizza i file sopra\n2. Identifica il problema\n3. Rispondi SOLO con comandi JSON per fixare\n4. NON creare README.md (usa solo claude.md)")
                        continue
                self.sess.add_message("user", u)
            elif self._failed_commands:
                file_ctx = self._read_file_context()
                func_match = re.search(r'(?:funzione|function|funzione\s+|fixa\s+|modifica\s+|bug\s+in\s+|errore\s+in\s+)(\w+)', u, re.IGNORECASE)
                specific_func_ctx = ""
                if func_match:
                    func_name = func_match.group(1)
                    specific_func_ctx = self._get_function_context(func_name)
                failed_list = "\n".join([f"cmd{idx}: {cmd[:150]}... -> ERRORE: {err}" for idx, cmd, err in self._failed_commands])
                fix_prompt = f"## Task originale: {u}\n\n"
                fix_prompt += "## Comandi falliti:\n"
                fix_prompt += f"{failed_list}\n\n"
                if specific_func_ctx:
                    fix_prompt += f"## Contesto FUNZIONE SPECIFICA ({func_name}):\n{specific_func_ctx}\n\n"
                    fix_prompt += "## Istruzioni:\n"
                    fix_prompt += f"1. Correggi SOLO la funzione `{func_name}`\n"
                    fix_prompt += "2. Usa cat heredoc per RISCRIVERE solo quella funzione nel file\n"
                    fix_prompt += "3. Mantieni le altre funzioni invariate\n"
                    fix_prompt += "4. Rispondi SOLO con JSON valido (max 2 comandi)\n\n"
                elif file_ctx:
                    fix_prompt += f"## Contesto file esistenti:\n{file_ctx}\n"
                    fix_prompt += "## Istruzioni:\n"
                    fix_prompt += "1. Correggi SOLO i comandi falliti\n"
                    fix_prompt += "2. NON riscrivere file già funzionanti\n"
                    fix_prompt += "3. NON creare file README.md, CLAUDE.md, claude.md (già esistono)\n"
                    fix_prompt += "4. Concentrati SOLO su file di codice (.py, .js, .html, .java)\n"
                    fix_prompt += "5. Usa comandi mirati (max 3-4 comandi)\n"
                    fix_prompt += "6. Rispondi SOLO con JSON valido\n\n"
                else:
                    fix_prompt += "## Istruzioni:\n"
                    fix_prompt += "1. Correggi i comandi falliti\n"
                    fix_prompt += "2. NON creare file README.md o CLAUDE.md\n"
                    fix_prompt += "3. Rispondi SOLO con JSON valido\n\n"
                fix_prompt += "JSON:"
                self._create_session()
                self.sess.add_message("user", fix_prompt)
                status(f"Fix per {len(self._failed_commands)} comandi" + (f" su `{func_name}`" if func_match else ""), "running")
            cx = self.ctx.ctx() if self.ctx else ""
            if self._plan_done and cx and not self._failed_commands:
                self.sess.add_message("user", f"{cx}\n\nPATH: {self._actual_path}")
            if self._plan_done and not self._failed_commands and iteration > 1:
                file_ctx = self._read_file_context()
                if file_ctx:
                    self.sess.add_message("user", f"## File già esistenti (NON riscriverli):\n{file_ctx}")
            try:
                # Aumenta token per /new (creazione progetti multi-file)
                use_extended = self.mode == 'new' or len(self.sess.to_ollama_messages()) > 10
                if use_extended:
                    original_ctx = self.ollama.options.get("num_ctx", 8192)
                    original_predict = self.ollama.options.get("num_predict", 8192)
                    self.ollama.options["num_ctx"] = 16384
                    self.ollama.options["num_predict"] = 16384
                
                status("LLM sta generando...", "running")
                self.thinking.start()
                request_data = {"messages": self.sess.to_ollama_messages(), "model": self.ollama.model}
                llm = ""
                for chunk in self.ollama.chat(self.sess.to_ollama_messages(), stream=True):
                    llm += chunk
                self.thinking.stop()
                
                # Ripristina opzioni se estese
                if use_extended:
                    self.ollama.options["num_ctx"] = original_ctx
                    self.ollama.options["num_predict"] = original_predict
                
                response_data = {"message": {"content": llm}}
                log_request_response(self.sess.id, request_data, response_data)
                
                # Controlla se response è troncata (per /new con molti file)
                if use_extended and len(llm) > 14000 and not llm.strip().endswith('}'):
                    status("⚠️ Response lunga, verifico completamento...", "warning")
                    if not llm.strip().endswith('EOF"}') and '"cmd' in llm:
                        llm = self._continue_truncated_response(llm, u)
                
                current_hash = hashlib.md5(llm.encode()).hexdigest()
                if current_hash == self._last_response_hash:
                    consecutive_duplicates += 1
                    status(f"⚠️ Response duplicata ({consecutive_duplicates}/{max_consecutive_duplicates})", "warning")
                    if consecutive_duplicates >= max_consecutive_duplicates:
                        status("⚠️ Troppi duplicati - LLM bloccato in loop", "error")
                        if self._commands_executed and self.proj:
                            fix_project_files(self.proj)
                        return "Loop rilevato - comandi già eseguiti"
                    self.sess.add_message("user", "Ignora risposte precedenti, genera SOLO se ci sono nuovi comandi da eseguire")
                    continue
                else:
                    consecutive_duplicates = 0
                self._last_response_hash = current_hash
                print(f"\n  {Colors.DIM}╭─ AI ─{Colors.RESET}")
                print(f"  {Colors.DIM}│{Colors.RESET} {Colors.CYAN}{llm[:600]}{Colors.RESET}")
                if len(llm) > 600:
                    print(f"  {Colors.DIM}│{Colors.RESET} {Colors.GRAY}... ({len(llm)} chars){Colors.RESET}")
                print(f"  {Colors.DIM}╰─{Colors.RESET}\n")
                p = self.parser.parse(llm)
                if not p.is_valid:
                    status(f"✗ Parsing fallito: {p.error}", "error")
                    logger.error(f"JSON parsing error: {p.error}")
                    logger.error(f"Raw response (first 800 chars): {llm[:800]}")
                    logger.error(f"Parser raw_response: {p.raw_response[:500] if p.raw_response else 'None'}")
                    if self.auto_c:
                        self.sess.add_message("user", f"Errore parsing JSON: {p.error}. Ripeti i comandi in formato JSON valido.")
                        continue
                    return f"Errore parsing: {p.error}"
                if self._done(llm):
                    status("✓ Completato!", "success")
                    if self.ctx: self.ctx._st = "completato"
                    if self._commands_executed and self.proj:
                        fix_project_files(self.proj)
                    self._test()
                    return "OK"
                if p.is_valid and p.commands:
                    status(f"LLM: {len(p.commands)} comandi", "info")
                    for i, cmd in enumerate(p.commands, 1):
                        logger.info(f"Command {i}: {cmd[:100]}...")
                    success_count, failures = self._execute_commands(p.commands)
                    if failures:
                        status(f"{len(failures)} falliti", "error")
                        self._failed_commands = failures
                        failed_prompt = f"## Task originale: {u}\n\n"
                        failed_prompt += "I seguenti comandi hanno fallito:\n\n"
                        for idx, cmd, err in failures:
                            cmd_short = cmd[:300] + "..." if len(cmd) > 300 else cmd
                            failed_prompt += f"### COMANDO {idx} FALLITO:\n{cmd_short}\n\n"
                            failed_prompt += f"ERRORE: {err}\n\n"
                        failed_prompt += f"## PATH: {self._actual_path}\n\n"
                        failed_prompt += "## Istruzioni:\n"
                        failed_prompt += "1. Analizza SOLO i comandi falliti sopra\n"
                        failed_prompt += "2. Correggi SOLO quelli specifici\n"
                        failed_prompt += "3. NON riscrivere file già creati con successo\n"
                        failed_prompt += "4. Usa comandi brevi e mirati (max 5 comandi)\n"
                        failed_prompt += "5. Rispondi SOLO con JSON, niente spiegazioni\n\n"
                        failed_prompt += "JSON dei comandi corretti:"
                        self._create_session()
                        self.sess.add_message("user", failed_prompt)
                        continue
                    else:
                        status(f"Tutti eseguiti", "success")
                        self._failed_commands = []
                        if self.proj and self.proj.exists():
                            self._update_claude_md_fix(u)
                        
                        # Per /new: chiedi se ci sono altri file da creare
                        if self.mode == 'new' and self._plan_done and not self._done(llm):
                            file_ctx = self._read_file_context()
                            continue_prompt = f"""File creati finora:
{file_ctx}

Task originale: {u}

Ci sono ancora file da creare per completare il progetto?
- Se SI: genera SOLO i file mancanti (max 4-5 comandi)
- Se NO: rispondi "Task completato"

JSON:"""
                            self.sess.add_message("user", continue_prompt)
                            status("🔄 Verifico se ci sono altri file...", "running")
                            continue
                        
                        if self._done(llm):
                            status("✓ Task completato!", "success")
                            if self.ctx: self.ctx._st = "completato"
                            self._test()
                            return "OK"
                        
                        if self.auto_c:
                            self.sess.add_message("user", "Continua con i prossimi passi se necessario, altrimenti rispondi 'Task completato'")
                            continue
                        else:
                            status("✅ Esecuzione completata", "success")
                            self._test()
                            return "OK"
                status("Nessun comando da eseguire", "warning")
                if self.auto_c:
                    self.sess.add_message("user", "Genera i comandi JSON per completare il task")
                    continue
                return "Nessun comando"
            except Exception as e:
                self.thinking.stop()
                status(f"❌ Errore: {e}", "error")
                logger.exception(f"Chat error: {e}")
                return f"Errore: {e}"
        return "Max iterazioni raggiunte"

    def show_ctx(self):
        if self.ctx and self.ctx.exists():
            print_claude(self.ctx.get())
        else:
            status("Nessun claude.md trovato", "info")

    def _reverse_engineer(self, target: Path) -> str:
        """Genera documentazione per un progetto."""
        self._reverse_log(f"reverse_start target={target}")
        status("📖 Scansione struttura progetto...", "running")
        candidates, stats = collect_candidate_files_with_stats(target, max_files=200)
        self._reverse_log(f"stats_seen_files={stats.get('seen_files')}")
        self._reverse_log(f"stats_ignored_dirs={stats.get('ignored_dirs')}")
        self._reverse_log(f"stats_ignored_ext={stats.get('ignored_ext')}")
        self._reverse_log(f"stats_ignored_size={stats.get('ignored_size')}")
        self._reverse_log(f"stats_ignored_other={stats.get('ignored_other')}")
        self._reverse_log(f"candidates={len(candidates)} truncated={stats.get('truncated')}")

        candidates, policy = apply_reverse_policy(target, candidates, max_candidates=40)
        self._reverse_log(f"policy_docs={policy.get('docs')}")
        self._reverse_log(f"policy_source_roots={policy.get('source_roots')}")
        self._reverse_log(f"policy_candidates_after={policy.get('candidates_after')}")
        self._reverse_log(f"policy_excluded_tests={policy.get('excluded_tests')}")
        self._reverse_log(f"policy_excluded_config={policy.get('excluded_config')}")
        self._reverse_log(f"policy_limited={policy.get('limited')} limit={policy.get('limit')}")
        if not candidates:
            self._reverse_log("no_candidates")
            return "❌ Nessun file rilevante trovato"
        tree = build_tree_from_paths(
            [rel for rel, _, _ in candidates],
            root_name=target.name,
            max_lines=400,
        )
        tree_lines = tree.count("\n") + 1 if tree else 0
        self._reverse_log(f"tree_lines={tree_lines}")
        index_text, allowed_set = format_candidate_index(candidates)

        # Fase 1: chiedi al LLM quali file leggere
        select_prompt = f"""Sei un technical writer. Ti fornisco SOLO una struttura filtrata e l'indice file.

STRUTTURA FILTRATA:
{tree}

INDICE FILE (dimensione e tag):
{index_text}

Seleziona SOLO i file necessari per capire il progetto.
Regole:
- Max 12 file
- Evita log/build/temp/lock
- Preferisci entrypoint, config, e sorgenti principali

Rispondi SOLO con JSON:
{{"cmd1": "READ <percorso_relativo>", "cmd2": "READ <percorso_relativo>", ...}}
Non usare comandi shell, solo READ + path relativo."""

        self._create_session()
        self.sess.add_message("user", select_prompt)

        try:
            self.thinking.start()
            select_resp = ""
            for chunk in self.ollama.chat(self.sess.to_ollama_messages(), stream=True):
                select_resp += chunk
            self.thinking.stop()
            self._reverse_log(f"select_resp_len={len(select_resp)}")
            self._reverse_log(f"select_resp_raw={select_resp.strip()[:2000]}")
        except Exception as e:
            self.thinking.stop()
            logger.exception(f"Reverse select error: {e}")
            self._reverse_log(f"select_error={e}")
            return f"❌ Errore selezione file: {e}"

        selected_by_llm = []
        selection_source = "llm"
        p_sel = self.parser.parse(select_resp)
        if p_sel.is_valid and p_sel.commands:
            selected_by_llm = extract_requested_files(p_sel.commands, target, allowed_set, max_files=12)
            self._reverse_log(f"select_commands={len(p_sel.commands)} selected={len(selected_by_llm)}")
        else:
            self._reverse_log("select_parse_failed")

        # Includi sempre README/CLAUDE se presenti
        if not selected_by_llm:
            selection_source = "fallback"
            selected_by_llm = pick_default_files(candidates, limit=10)
            self._reverse_log(f"fallback_selected={len(selected_by_llm)}")
        self._reverse_log(f"selection_source={selection_source}")

        selected = list(selected_by_llm)
        docs = find_primary_docs(target)
        for d in docs:
            if d not in selected:
                selected.insert(0, d)

        files_content, read_stats = read_files_content_with_stats(
            target, selected, max_chars_per_file=4000, max_total_chars=20000
        )
        self._reverse_log(f"files_content_len={len(files_content)}")
        self._reverse_log(f"files_read={read_stats.get('files_read')} total_chars={read_stats.get('total_chars')} truncated={read_stats.get('truncated')}")
        if not files_content:
            self._reverse_log("no_files_content")
            return "❌ Nessun contenuto letto"

        selected_list = "\n".join([f"- {p.as_posix()}" for p in selected])
        self._reverse_log("selected_files=" + ",".join([p.as_posix() for p in selected]))
        prompt = f"""Sei un technical writer. Genera documentazione completa per questo progetto.
Usa SOLO i file forniti; se manca qualche informazione, dichiaralo esplicitamente.

STRUTTURA FILTRATA:
{tree}

FILE SELEZIONATI:
{selected_list}

CONTENUTI FILE:
{files_content}

DOCUMENTAZIONE.md DEVE CONTENERE (IN QUESTO ORDINE):
1) PANORAMICA DEL PROGETTO (nome, scopo, tecnologie, architettura)
2) STRUTTURA DEL PROGETTO (ASCII tree)
3) FILE PRINCIPALI (scopo, funzioni/classi)
4) FLUSSO DI ESECUZIONE
5) API / FUNZIONI PUBBLICHE
6) CONFIGURAZIONE
7) NOTE AGGIUNTIVE

Genera DOCUMENTAZIONE.md in ITALIANO (minimo 800 parole).
Rispondi SOLO con comandi JSON per creare DOCUMENTAZIONE.md:"""

        # Salva opzioni originali e imposta opzioni moderate per /reverse
        original_ctx = self.ollama.options.get("num_ctx", 8192)
        original_predict = self.ollama.options.get("num_predict", 4096)
        self.ollama.options["num_ctx"] = 8192
        self.ollama.options["num_predict"] = 4096
        status("🔧 Contesto ottimizzato: 8192/4096 token per /reverse", "info")
        self._reverse_log(f"llm_options num_ctx=8192 num_predict=4096")

        try:
            self._create_session()
            self.sess.add_message("user", prompt)
            self.thinking.start()
            llm = ""
            for chunk in self.ollama.chat(self.sess.to_ollama_messages(), stream=True):
                llm += chunk
            self.thinking.stop()
            self._reverse_log(f"final_resp_len={len(llm)}")
            p = self.parser.parse(llm)

            # Se il JSON è troncato o incompleto, chiedi di continuare
            if not p.is_valid or (len(llm) > 10000 and llm.strip()[-10:] != 'EOF"}'):
                status("⚠️ Response troncata, chiedo continuazione...", "warning")
                self._reverse_log("response_truncated=True")
                llm = self._continue_truncated_response(llm, prompt)
                p = self.parser.parse(llm)
                self._reverse_log(f"final_resp_len_after_continue={len(llm)}")

            if p.is_valid and p.commands:
                self._reverse_log(f"final_commands={len(p.commands)}")
                self._execute_commands(p.commands)
                doc_file = target / "DOCUMENTAZIONE.md"
                if doc_file.exists():
                    return doc_file.read_text()[:3000]
            return llm
        except Exception as e:
            logger.exception(f"Reverse error: {e}")
            self._reverse_log(f"reverse_error={e}")
            return f"❌ Errore: {e}"
        finally:
            # Ripristina sempre le opzioni originali
            self.ollama.options["num_ctx"] = original_ctx
            self.ollama.options["num_predict"] = original_predict

    def _continue_truncated_response(self, truncated_llm: str, original_prompt: str) -> str:
        """Chiede al modello di continuare una response troncata."""
        status("🔄 Chiedo continuazione JSON...", "running")
        
        # Trova l'ultimo comando completo
        last_cmd_match = re.search(r'"cmd(\d+)":\s*"(.*?)"', truncated_llm, re.DOTALL)
        last_cmd_num = int(last_cmd_match.group(1)) if last_cmd_match else 0
        
        continue_prompt = f"""Il tuo JSON precedente era troncato. Continua da cmd{last_cmd_num + 1}.

JSON TRONCATO (ultimi 500 chars):
...{truncated_llm[-500:]}

CONTINUA il JSON da dove si è interrotto. Formato:
{{"cmd{last_cmd_num + 1}": "...", "cmd{last_cmd_num + 2}": "...", ...}}

Importante: chiudi il JSON con }} alla fine."""
        
        self._create_session()
        self.sess.add_message("user", continue_prompt)
        
        try:
            self.thinking.start()
            continuation = ""
            for chunk in self.ollama.chat(self.sess.to_ollama_messages(), stream=True):
                continuation += chunk
            self.thinking.stop()
            
            # Combina originale + continuazione
            return truncated_llm + "\n" + continuation
        except Exception as e:
            logger.error(f"Continue error: {e}")
            return truncated_llm

    def _cmd_ui(self, c) -> bool:
        p = c.lower().split(); cmd = p[0]
        if cmd in ['/quit','/exit','/q']:
            save_history()
            self._save_logs()
            self.st.save()
            print(f"\n  {Colors.GREEN}✓{Colors.RESET}\n"); return True
        if cmd == '/model' and len(p) > 1: self.change_model(c.split(None,1)[1])
        elif cmd == '/safe':
            self.st.safe = not self.st.safe; self.st.save()
            status(f"Safety: {'ON' if self.st.safe else 'OFF'}", "info")
        elif cmd == '/auto': self.auto_c = not self.auto_c; self.st.auto_c = self.auto_c; self.st.save(); status(f"Auto: {'ON' if self.auto_c else 'OFF'}", "info")
        elif cmd == '/test': self.auto_t = not self.auto_t; self.st.auto_t = self.auto_t; self.st.save(); status(f"Test: {'ON' if self.auto_t else 'OFF'}", "info")
        elif cmd == '/context': self.show_ctx()
        elif cmd == '/fix':
            self.set_mode('fix')
            self.auto_c = True
            self.auto_t = True
            status("  • Leggerà file esistenti prima di agire", "info")
            status("  • Non creerà README.md (usa claude.md)", "info")
            status("  • Aggiornerà claude.md con i fix effettuati", "info")
            print(f"  {Colors.DIM}Ora scrivi la richiesta di fix (es: 'fixa il gioco che non parte'){Colors.RESET}")
        elif cmd == '/new':
            self.set_mode('new')
            self.auto_c = True
            self.auto_t = True
            status("  • Può creare claude.md per tracciamento", "info")
            status("  • Struttura completa del progetto", "info")
            print(f"  {Colors.DIM}Ora scrivi cosa creare (es: 'crea un gioco del tris in /path'){Colors.RESET}")
        elif cmd == '/reverse':
            status("📖 Reverse Engineering - Specifica il path del progetto", "running")
            parts = c.split(None, 1)
            if len(parts) > 1:
                target_path = Path(_strip_surrounding_quotes(parts[1].strip()))
            else:
                target_path = self.proj if self.proj else Path(".")
            status(f"Analizzo: {target_path.absolute()}", "info")
            doc = self._reverse_engineer(target_path)
            if doc and not doc.startswith("❌"):
                doc_file = target_path / "DOCUMENTAZIONE.md"
                try:
                    doc_file.write_text(doc)
                    status(f"📝 Documentazione salvata: {doc_file}", "success")
                    print(f"\n  {Colors.CYAN}{doc[:1000]}{'...' if len(doc) > 1000 else ''}{Colors.RESET}\n")
                except Exception as e:
                    status(f"Errore salvataggio: {e}", "error")
                    print(f"\n  {Colors.CYAN}{doc}{Colors.RESET}\n")
            else:
                status(doc, "error")
        elif cmd == '/help':
            print(f"""
  {Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.RESET}
  {Colors.CYAN}║{Colors.RESET}   COMANDI DISPONIBILI                           {Colors.CYAN}║{Colors.RESET}
  {Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.RESET}

  {Colors.BOLD}Modalità di lavoro:{Colors.RESET}
    {Colors.GREEN}/fix{Colors.RESET}         Attiva modalità FIX (legge file esistenti, usa claude.md)
    {Colors.GREEN}/new{Colors.RESET}         Attiva modalità NEW PROJECT (crea da zero con claude.md)
    {Colors.GREEN}/reverse{Colors.RESET}     Reverse engineering (genera DOCUMENTAZIONE.md)

  {Colors.BOLD}Gestione:{Colors.RESET}
    {Colors.GREEN}/model <nome>{Colors.RESET}  Cambia modello LLM
    {Colors.GREEN}/safe{Colors.RESET}        Toggle safety (ON/OFF)
    {Colors.GREEN}/auto{Colors.RESET}        Auto-continue (ON/OFF)
    {Colors.GREEN}/test{Colors.RESET}        Auto-test dopo fix (ON/OFF)
    {Colors.GREEN}/context{Colors.RESET}     Mostra claude.md corrente
    {Colors.GREEN}/help{Colors.RESET}        Mostra questo aiuto
    {Colors.GREEN}/exit{Colors.RESET}        Esci dall'applicazione

  {Colors.DIM}Esempi:{Colors.RESET}
    /fix
    fixa il gioco del tris che non parte
    /new
    crea un gestionale per biblioteca in /path/proj
    /reverse /path/progetto

  {Colors.YELLOW}NOTA: claude.md è l'UNICO file di tracciamento (no README.md){Colors.RESET}
""")
        return False

def _strip_surrounding_quotes(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
        return t[1:-1]
    return t

    def run(self):
        print(f"  {Colors.DIM}Es: 'crea tris in /path/proj'{Colors.RESET}\n")
        load_history()
        while True:
            try:
                u = get_input()
                if not u:
                    status("Scrivi comando o /help", "info")
                    continue
                if u.startswith('/'):
                    if self._cmd_ui(u): break
                    continue
                self.chat(u)
            except KeyboardInterrupt:
                save_history()
                self._save_logs()
                self.st.save()
                if self._commands_executed and self.proj:
                    fix_project_files(self.proj)
                print(f"\n  {Colors.GREEN}✓{Colors.RESET}\n"); break
            except EOFError: break

def main():
    ap = argparse.ArgumentParser(
        description="Ollama File System Bridge - CLI e GUI per interagire con Ollama LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python3 main.py          # Avvia CLI terminale (default)
  python3 main.py --gui    # Avvia interfaccia grafica (Tkinter)
  python3 main.py --chat   # Avvia chat UI testuale (Textual)
  python3 main.py -p "crea tris"  # Esegue prompt singolo
        """
    )
    ap.add_argument("-c", "--config", default="config.json")
    ap.add_argument("-p", "--prompt")
    ap.add_argument("-m", "--model")
    ap.add_argument("--gui", action="store_true", help="Avvia interfaccia grafica (Tkinter)")
    ap.add_argument("--chat", action="store_true", help="Avvia chat UI testuale (Textual)")
    ap.add_argument("--cli", action="store_true", help="Forza modalità CLI terminale (default)")
    args = ap.parse_args()

    if args.gui:
        from src.gui import main as gui_main
        gui_main()
        return

    if args.chat:
        from src.chat_ui import main as chat_main
        chat_main()
        return

    st = State(STATE_FILE)
    cfg = json.loads(Path(args.config).read_text()) if Path(args.config).exists() else {"ollama":{"base_url":"http://localhost:11434","model":"shellbot:latest","timeout":1800}}
    forced_model = args.model if args.model else None
    b = Bridge(cfg, st, forced_model)
    if not b.init(): sys.exit(1)
    print(b.chat(args.prompt)) if args.prompt else b.run()

if __name__ == "__main__": main()
