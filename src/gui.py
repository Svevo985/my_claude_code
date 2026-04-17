#!/usr/bin/env python3
"""GUI Tkinter per Ollama File System Bridge - Grafica curata con animazioni e controlli completi."""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import json
import re
import logging
from pathlib import Path
from datetime import datetime
import time
import re
import subprocess
import shutil

# Configura logging su file per la GUI
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_gui_logging():
    """Configura il logging su file per la GUI."""
    log_file = LOG_DIR / f"gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # Crea handler file
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    # Configura logger GUI
    gui_logger = logging.getLogger('gui')
    gui_logger.setLevel(logging.INFO)
    gui_logger.addHandler(file_handler)
    
    return gui_logger

logger = setup_gui_logging()

from src.ollama_client import OllamaClient
from src.session_manager import SessionManager
from src.file_operations import FileOperations
from src.command_parser import CommandParser
from src.project_memory import ProjectMemory
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
    find_java_service_classes,
    find_java_controller_classes,
    _is_spring_boot_project,
)

CONFIG_FILE = Path("./config.json")
STATE_FILE = Path("./.ollama_bridge_state.json")


class ThinkingAnimation:
    """Animazione per lo stato 'pensando'."""

    def __init__(self, parent, bg, fg):
        self.parent = parent
        self.bg = bg
        self.fg = fg
        self.label = None
        self.dots = 0
        self.running = False
        self.frames = ["-", "\\", "|", "/"]
        self.messages = ["LLM pensa", "Elabora", "Analizza", "Genera"]
        self.frame_idx = 0
        self.msg_idx = 0

    def start(self, container):
        """Avvia l'animazione."""
        self.running = True
        self.frame_idx = 0
        self.msg_idx = 0
        self.dots = 0

        self.label = tk.Label(
            container,
            text="============================================================",
            bg=self.bg, fg=self.fg,
            font=("Consolas", 10, "bold")
        )
        self.label.pack(pady=5)

        self._animate()

    def stop(self):
        """Ferma l'animazione."""
        self.running = False
        if self.label:
            self.label.destroy()
            self.label = None

    def _animate(self):
        """Aggiorna l'animazione."""
        if not self.running:
            return

        frame = self.frames[self.frame_idx % len(self.frames)]
        msg = self.messages[self.msg_idx % len(self.messages)]
        dots = "." * self.dots

        self.label.config(text=f"  {frame} {msg}{dots}   ")

        self.frame_idx += 1
        if self.frame_idx % 30 == 0:
            self.msg_idx += 1
        if self.frame_idx % 10 == 0:
            self.dots = (self.dots % 4) + 1

        self.parent.after(100, self._animate)


class OllamaBridgeGUI:
    """Interfaccia grafica Tkinter per Ollama Bridge."""

    def __init__(self, root):
        logger.info("=== AVVIO GUI OLLAMA BRIDGE ===")
        self.root = root
        self.root.title("Ollama File System Bridge")
        self.root.geometry("1400x800")
        self.root.minsize(1000, 650)

        # Config
        self.config = self._load_config()
        self.state = self._load_state()
        
        logger.info(f"Configurazione caricata: {self.config.get('ollama', {}).get('base_url', 'default')}")

        # Client
        self.ollama = None
        self.session_manager = SessionManager()
        self.session = None
        self.file_ops = FileOperations(
            self.config.get("working_directory", "."),
            shell_override=self.config.get("shell", {}).get("override")
        )
        self.env_info = self.file_ops.environment_info()
        self.command_style = self._command_style_from_env(self.env_info)
        self.parser = CommandParser()

        # Stato
        self.is_thinking = False
        self.connected = False
        self.models = []
        self.stop_flag = False  # Flag per stoppare inferenza
        self.thinking_anim = None
        
        # Modelli specializzati (scoperti dinamicamente dopo connessione)
        self.model_create = None
        self.model_docs = None
        self.current_mode = "default"

        # Colori tema (VS Code dark)
        self.colors = {
            "bg": "#1e1e1e",
            "bg_dark": "#181818",
            "bg_light": "#252526",
            "fg": "#d4d4d4",
            "accent": "#007acc",
            "accent_light": "#0098ff",
            "success": "#4ec9b0",
            "error": "#f44747",
            "warning": "#dcdcaa",
            "info": "#569cd6",
            "cyan": "#4ec9b0",
            "orange": "#ce9178",
            "gray": "#808080",
            "border": "#3e3e42",
            "thinking": "#dcdcaa",
        }

        # Setup UI
        self._setup_styles()
        self._setup_ui()

        # Inizializza connessione
        self._init_ollama()

    #  Utils modelli shellbot 
    def _sanitize_model_name(self, name: str) -> str:
        if not name:
            return ""
        safe = re.sub(r'[^a-zA-Z0-9._-]+', '-', name.strip())
        safe = re.sub(r'-{2,}', '-', safe).strip('-').lower()
        return safe

    def _shellbot_target_name(self, model: str) -> str:
        base = self._sanitize_model_name(model)
        return f"{base}-shellbot" if base else ""

    def _filter_shellbot(self, models: list[str]) -> list[str]:
        """Ritorna i modelli shellbot o quelli esplicitamente taggati per compiti specifici."""
        keywords = ["shellbot", "create", "docs", "fix", "reverse"]
        return [m for m in models if any(k in m.lower() for k in keywords)]

    def _command_style_from_env(self, env: dict) -> str:
        runner = (env or {}).get("runner", "")
        if runner in {"powershell", "cmd"}:
            return "powershell"
        return "posix"

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
        except Exception as exc:
            return (False, f"Errore: {e}")

    def _load_template_modelfile(self) -> str | None:
        candidates: list[Path] = []
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
                    return path.read_text(encoding='utf-8', errors='replace')
                except Exception:
                    pass
        return None

    def _write_temp_modelfile(self, template: str, base_model: str, slug: str) -> Path:
        tmp_dir = Path("logs") / "modelfile_auto_gui"
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
        except Exception:
            pass
        ok, out = self.file_ops.execute_command("ollama list", timeout=60)
        if ok and out:
            for line in out.splitlines():
                parts = line.split()
                if not parts or parts[0].lower() == "name":
                    continue
                models.add(parts[0])
        return models

    def _auto_convert_models(self, force: bool = False):
        template = self._load_template_modelfile()
        if not template:
            return
        try:
            installed = self._get_installed_models()
        except Exception:
            installed = set()
        if not installed:
            return
        for model in sorted(installed):
            if "shellbot" in model.lower():
                continue
            target = self._shellbot_target_name(model)
            if not target:
                continue
            target_tag = f"{target}:latest"
            if self._target_exists(installed, target, target_tag) and not force:
                continue
            # crea modelfile temporaneo
            slug = self._sanitize_model_name(model)[:120]
            tmp_path = self._write_temp_modelfile(template, model, slug)
            ok, out = self._run_ollama_create(target_tag, tmp_path)
            if ok:
                installed.add(target_tag)
            else:
                # log in chat solo se visibile
                self._add_message(f" Conversione {target_tag} fallita: {out[:120]}", "warning")

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        else:
            cfg = {
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen2.5-coder-shellbot-create:latest",
                "timeout": 1800
            }
        }
        wf = cfg.setdefault("workflow", {})
        wf.setdefault("plan_num_predict", 900)
        wf.setdefault("plan_max_response_chars", 20000)
        wf.setdefault("plan_max_retries", 2)
        wf.setdefault("step_num_predict", 1200)
        wf.setdefault("step_max_response_chars", 20000)
        wf.setdefault("max_step_retries", 2)
        return cfg

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return {}

    def _setup_styles(self):
        """Configura stili e colori."""
        self.root.configure(bg=self.colors["bg"])

        # Font
        self.font_title = ("Consolas", 11, "bold")
        self.font_normal = ("Consolas", 10)
        self.font_small = ("Consolas", 9)
        self.font_code = ("Consolas", 10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["fg"], font=self.font_normal)
        style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["cyan"], font=self.font_title)
        style.configure("Accent.TLabel", background=self.colors["bg"], foreground=self.colors["accent"], font=self.font_title)
        style.configure("TButton", background=self.colors["accent"], foreground="white", font=self.font_normal, padding=5)
        style.map("TButton", background=[("active", self.colors["accent_light"])])
        style.configure("Success.TButton", background=self.colors["success"], foreground="black")
        style.configure("Danger.TButton", background=self.colors["error"], foreground="white")
        style.configure("TNotebook", background=self.colors["bg"], bordercolor=self.colors["border"])
        style.configure("TNotebook.Tab", background=self.colors["bg_light"], foreground=self.colors["fg"], padding=[10, 5], font=self.font_normal)
        style.map("TNotebook.Tab", background=[("selected", self.colors["bg"])])
        style.configure("TProgressbar", background=self.colors["accent"], troughcolor=self.colors["bg_dark"])

    def _create_banner(self, parent):
        """Crea il banner stile terminale."""
        banner = tk.Frame(parent, bg=self.colors["bg_dark"], height=100)
        banner.pack(fill=tk.X, padx=2, pady=2)

        # Titolo grande
        title_frame = tk.Frame(banner, bg=self.colors["accent"])
        title_frame.pack(fill=tk.X)

        tk.Label(
            title_frame,
            text="============================================================",
            bg=self.colors["accent"], fg="white", font=("Consolas", 9)
        ).pack()

        title_text = tk.Frame(banner, bg=self.colors["bg_dark"])
        title_text.pack(fill=tk.X, padx=10)

        tk.Label(
            title_text,
            text="    OLLAMA FILE SYSTEM BRIDGE",
            bg=self.colors["bg_dark"], fg="white", font=("Consolas", 14, "bold")
        ).pack(anchor=tk.W)

        tk.Label(
            title_text,
            text="   Interfaccia Grafica per LLM + File System",
            bg=self.colors["bg_dark"], fg=self.colors["gray"], font=("Consolas", 9)
        ).pack(anchor=tk.W)

        tk.Label(
            title_frame,
            text="",
            bg=self.colors["accent"], fg="white", font=("Consolas", 9)
        ).pack()

        return banner

    def _create_status_bar(self, parent):
        """Crea la barra di stato."""
        status = tk.Frame(parent, bg=self.colors["bg_light"], height=30)
        status.pack(fill=tk.X, side=tk.BOTTOM, padx=2, pady=2)

        # Stato connessione
        self.status_label = tk.Label(
            status, text=" Disconnesso",
            bg="#f44747", fg="white",
            padx=15, pady=5, font=("Consolas", 9, "bold"),
            relief=tk.FLAT
        )
        self.status_label.pack(side=tk.LEFT, padx=5, pady=5)

        # Modello
        self.model_label = tk.Label(
            status, text="Modello: --",
            bg=self.colors["bg_light"], fg=self.colors["accent"],
            padx=10, pady=5, font=("Consolas", 9, "bold")
        )
        self.model_label.pack(side=tk.LEFT, padx=10)

        # Sessione
        self.session_label = tk.Label(
            status, text="Sessione: --",
            bg=self.colors["bg_light"], fg=self.colors["info"],
            padx=10, pady=5, font=("Consolas", 9)
        )
        self.session_label.pack(side=tk.LEFT, padx=10)

        # Container animazione thinking
        self.thinking_container = tk.Frame(status, bg=self.colors["bg_light"])
        self.thinking_container.pack(side=tk.LEFT, padx=10)

        # Path
        self.path_label = tk.Label(
            status, text=f"Path: {Path('.').absolute()}",
            bg=self.colors["bg_light"], fg=self.colors["gray"],
            padx=10, pady=5, font=("Consolas", 8)
        )
        self.path_label.pack(side=tk.RIGHT, padx=10)

        return status

    def _create_commands_panel(self, parent):
        """Crea il pannello laterale comandi."""
        panel = tk.Frame(parent, bg=self.colors["bg_light"], width=320)
        panel.pack(fill=tk.Y, side=tk.RIGHT, padx=2, pady=2)
        panel.pack_propagate(False)

        # Scrollbar per il pannello
        scrollbar = tk.Scrollbar(panel)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas = tk.Canvas(panel, bg=self.colors["bg_light"], highlightthickness=0, yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=canvas.yview)

        # Frame interno scrollabile
        inner_frame = tk.Frame(canvas, bg=self.colors["bg_light"])
        canvas.create_window((0, 0), window=inner_frame, anchor=tk.NW)
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Titolo
        tk.Label(
            inner_frame, text=" COMANDI DISPONIBILI",
            bg=self.colors["bg_light"], fg=self.colors["cyan"],
            font=("Consolas", 11, "bold"), pady=10
        ).pack(fill=tk.X)

        # Separator
        ttk.Separator(inner_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)

        # Modalit di lavoro
        tk.Label(
            inner_frame, text=" MODALIT DI LAVORO",
            bg=self.colors["bg_light"], fg=self.colors["warning"],
            font=("Consolas", 10, "bold"), pady=5
        ).pack(anchor=tk.W, padx=10)

        commands = [
            (" /fix", "Fixa codice esistente", self._cmd_fix, "Legge file, non crea doc"),
            (" /new", "Nuovo progetto", self._cmd_new, "Crea da zero con claude.md"),
            (" /reverse", "Documentazione", self._cmd_reverse, "Genera DOCUMENTAZIONE.md"),
        ]

        for label, desc, cmd, note in commands:
            btn_frame = tk.Frame(inner_frame, bg=self.colors["bg_light"])
            btn_frame.pack(fill=tk.X, padx=10, pady=2)

            tk.Button(
                btn_frame, text=label, command=cmd,
                bg=self.colors["bg_light"], fg=self.colors["fg"],
                activebackground=self.colors["accent"], activeforeground="white",
                font=("Consolas", 9), relief=tk.FLAT,
                cursor="hand2", width=18, anchor=tk.W
            ).pack(side=tk.LEFT)

            info_frame = tk.Frame(btn_frame, bg=self.colors["bg_light"])
            info_frame.pack(side=tk.LEFT, padx=5)

            tk.Label(
                info_frame, text=desc,
                bg=self.colors["bg_light"], fg=self.colors["fg"],
                font=("Consolas", 8), anchor=tk.W
            ).pack(anchor=tk.W)

            tk.Label(
                info_frame, text=note,
                bg=self.colors["bg_light"], fg=self.colors["gray"],
                font=("Consolas", 7, "italic"), anchor=tk.W
            ).pack(anchor=tk.W)

        ttk.Separator(inner_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # Gestione sessione
        tk.Label(
            inner_frame, text=" GESTIONE",
            bg=self.colors["bg_light"], fg=self.colors["info"],
            font=("Consolas", 10, "bold"), pady=5
        ).pack(anchor=tk.W, padx=10)

        management = [
            ("/help", "Mostra aiuto completo", self._cmd_help),
            ("/model <n>", "Cambia modello LLM", self._cmd_model),
            ("/context", "Vedi claude.md", self._cmd_context),
            ("/safe", "Toggle safety on/off", self._cmd_safe),
            ("/auto", "Auto-continue on/off", self._cmd_auto),
            ("/test", "Auto-test on/off", self._cmd_test),
            ("/clear", "Pulisci schermo", self._cmd_clear),
            ("/exit", "Esci dall'app", self._cmd_exit),
        ]

        for label, desc, cmd in management:
            btn_frame = tk.Frame(inner_frame, bg=self.colors["bg_light"])
            btn_frame.pack(fill=tk.X, padx=10, pady=1)

            tk.Label(
                btn_frame, text=label,
                bg=self.colors["bg_light"], fg=self.colors["accent"],
                font=("Consolas", 9), width=18, anchor=tk.W
            ).pack(side=tk.LEFT)

            tk.Label(
                btn_frame, text=desc,
                bg=self.colors["bg_light"], fg=self.colors["gray"],
                font=("Consolas", 7), anchor=tk.W
            ).pack(side=tk.LEFT, padx=5)

        ttk.Separator(inner_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=10)

        # Modelli disponibili
        tk.Label(
            inner_frame, text=" MODELLI DISPONIBILI",
            bg=self.colors["bg_light"], fg=self.colors["success"],
            font=("Consolas", 10, "bold"), pady=5
        ).pack(anchor=tk.W, padx=10)

        self.models_listbox = tk.Listbox(
            inner_frame, bg=self.colors["bg_dark"], fg=self.colors["fg"],
            font=("Consolas", 8), height=10,
            selectbackground=self.colors["accent"],
            selectforeground="white",
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=self.colors["border"]
        )
        self.models_listbox.pack(fill=tk.X, padx=10, pady=5)

        # Pulsante refresh
        tk.Button(
            inner_frame, text=" Aggiorna lista modelli", command=self._refresh_models,
            bg=self.colors["accent"], fg="white",
            activebackground=self.colors["accent_light"],
            font=("Consolas", 9), relief=tk.FLAT,
            cursor="hand2", pady=5
        ).pack(fill=tk.X, padx=10, pady=5)

        # Info box
        info_box = tk.Label(
            inner_frame,
            text=" Suggerimento:\nUsa /fix per modificare\ncodice esistente.\nUsa /new per creare\nnuovi progetti.",
            bg=self.colors["bg_dark"], fg=self.colors["gray"],
            font=("Consolas", 8), padx=10, pady=10,
            relief=tk.FLAT, justify=tk.LEFT
        )
        info_box.pack(fill=tk.X, padx=10, pady=10)

        return panel

    def _setup_ui(self):
        """Crea l'interfaccia utente principale."""
        # Frame principale
        main_frame = tk.Frame(self.root, bg=self.colors["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Banner
        self._create_banner(main_frame)

        # Status bar
        self._create_status_bar(main_frame)

        # Pannello centrale
        center_frame = tk.Frame(main_frame, bg=self.colors["bg"])
        center_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Chat area
        chat_frame = tk.LabelFrame(
            center_frame, text="  Chat ",
            bg=self.colors["bg_light"], fg=self.colors["cyan"],
            font=("Consolas", 10, "bold"), padx=5, pady=5
        )
        chat_frame.pack(fill=tk.BOTH, expand=True)

        self.chat_display = scrolledtext.ScrolledText(
            chat_frame, wrap=tk.WORD,
            bg=self.colors["bg_dark"], fg=self.colors["fg"],
            font=self.font_code,
            padx=10, pady=10,
            borderwidth=0, insertbackground="white",
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=self.colors["border"]
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        # Tag per colori
        self._setup_tags()

        # Input area
        input_frame = tk.Frame(center_frame, bg=self.colors["bg_light"], pady=10, padx=10)
        input_frame.pack(fill=tk.X, pady=(5, 0))

        tk.Label(
            input_frame, text=">>",
            fg=self.colors["accent"], bg=self.colors["bg_light"],
            font=("Consolas", 14, "bold")
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.input_field = scrolledtext.ScrolledText(
            input_frame, height=4,
            bg=self.colors["bg_dark"], fg=self.colors["fg"],
            font=self.font_code,
            padx=10, pady=8,
            borderwidth=0, insertbackground="white",
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=self.colors["border"]
        )
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_field.bind("<Shift-Return>", lambda e: None)
        self.input_field.bind("<Return>", self._on_enter_key)

        # Pulsanti
        btn_frame = tk.Frame(input_frame, bg=self.colors["bg_light"])
        btn_frame.pack(side=tk.RIGHT, padx=(10, 0))

        # Pulsante STOP (rosso)
        self.stop_btn = tk.Button(
            btn_frame, text=" STOP", command=self._stop_inference,
            bg=self.colors["error"], fg="white",
            activebackground="#ff6b6b",
            font=("Consolas", 10, "bold"), relief=tk.FLAT,
            cursor="hand2", padx=15, pady=8,
            state=tk.DISABLED
        )
        self.stop_btn.pack(fill=tk.X, pady=(0, 5))

        self.send_btn = tk.Button(
            btn_frame, text=" Invia", command=self._send_message,
            bg=self.colors["success"], fg="black",
            activebackground="#5fd9c0",
            font=("Consolas", 10, "bold"), relief=tk.FLAT,
            cursor="hand2", padx=15, pady=8
        )
        self.send_btn.pack(fill=tk.X, pady=(0, 5))

        self.clear_btn = tk.Button(
            btn_frame, text=" Pulisci", command=self._clear_chat,
            bg=self.colors["bg_light"], fg=self.colors["fg"],
            activebackground=self.colors["accent"], activeforeground="white",
            font=("Consolas", 9), relief=tk.FLAT,
            cursor="hand2", padx=10, pady=5
        )
        self.clear_btn.pack(fill=tk.X)

        # Pannello comandi laterale
        self._create_commands_panel(center_frame)

        # Inizializza animazione thinking
        self.thinking_anim = ThinkingAnimation(
            self.thinking_container,
            self.colors["bg_light"],
            self.colors["thinking"]
        )

    def _setup_tags(self):
        """Configura tag per colori nella chat."""
        self.chat_display.tag_configure("user", foreground=self.colors["success"], font=("Consolas", 10, "bold"))
        self.chat_display.tag_configure("ai", foreground=self.colors["info"], font=("Consolas", 10, "bold"))
        self.chat_display.tag_configure("system", foreground=self.colors["warning"], font=("Consolas", 9, "italic"))
        self.chat_display.tag_configure("error", foreground=self.colors["error"], font=("Consolas", 10))
        self.chat_display.tag_configure("success", foreground=self.colors["success"], font=("Consolas", 10))
        self.chat_display.tag_configure("warning", foreground=self.colors["warning"], font=("Consolas", 10))
        self.chat_display.tag_configure("info", foreground=self.colors["info"], font=("Consolas", 9))
        self.chat_display.tag_configure("code", foreground=self.colors["orange"], font=("Consolas", 9))
        self.chat_display.tag_configure("banner", foreground=self.colors["cyan"], font=("Consolas", 9, "bold"))
        self.chat_display.tag_configure("model_list", foreground=self.colors["fg"], font=("Consolas", 9))

    def _reverse_log(self, msg: str):
        try:
            log_file = Path("logs") / "reverse_gui.log"
            log_file.parent.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def _find_specialized_model(self, suffix: str):
        """Cerca un modello shellbot con suffisso specifico tra quelli disponibili."""
        if not self.models:
            return None
        # Priorit 1: modello con suffisso esatto legato a shellbot
        for m in self.models:
            ml = m.lower()
            if f"shellbot-{suffix}" in ml or f"-shellbot-{suffix}" in ml:
                return m
        # Priorit 2: modello che contiene sia 'shellbot' che il suffisso
        for m in self.models:
            ml = m.lower()
            if f"{suffix}" in ml and "shellbot" in ml:
                return m
        # Priorit 3: fallback su qualsiasi modello che contiene il suffisso (es. gemma4NewCreate)
        for m in self.models:
            ml = m.lower()
            if suffix.lower() in ml:
                return m
        return None

    def _discover_specialized_models(self):
        """Scopri modelli specializzati create/docs tra quelli disponibili."""
        self.model_create = self._find_specialized_model("create")
        self.model_docs = self._find_specialized_model("docs")
        if self.model_create:
            self._add_message(f" Modello CREATE/FIX: {self.model_create}", "info")
        if self.model_docs:
            self._add_message(f" Modello DOCS/REVERSE: {self.model_docs}", "info")

    def _init_ollama(self):
        """Inizializza la connessione a Ollama."""
        def connect():
            try:
                base_url = self.config.get("ollama", {}).get("base_url", "http://localhost:11434")
                use_state_model = self.config.get("ollama", {}).get("use_state_model", True)
                model = self.state.get('model') if use_state_model and self.state.get('model') else self.config.get('ollama', {}).get('model', 'llama3.2')
                timeout = self.config.get('ollama', {}).get('timeout', 1800)

                ollama_options = {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_ctx": 16384,
                    "num_predict": 4096,
                    "num_thread": 6,
                    "think": False,
                }

                self.ollama = OllamaClient(base_url, model, timeout, options=ollama_options)

                if not self.ollama.is_available():
                    self.root.after(0, self._add_message, " Ollama non disponibile, tentativo di avvio automatico...", "warning")
                    success, msg = self.ollama.ensure_available()
                    if not success:
                        self.root.after(0, self._on_connection_failed, f"Ollama non avviabile: {msg}")
                        return
                    self.root.after(0, self._add_message, f" Ollama avviato: {msg}", "success")

                if self.ollama.is_available():
                    # Autoconversione in varianti shellBot prima di filtrare
                    force_rebuild = self.config.get("ollama", {}).get("force_rebuild_shellbot", False)
                    # self._auto_convert_models(force=force_rebuild) #  Disabilitato automatismo su richiesta utente

                    all_models = self.ollama.list_models()
                    # Salva TUTTI i modelli, non solo shellbot
                    self.models = all_models
                    shell_models = self._filter_shellbot(all_models)
                    
                    # Se ci sono shellbot, usa il primo come default
                    if shell_models:
                        if self.ollama.model not in shell_models:
                            self.ollama.model = shell_models[0]
                    elif all_models:
                        # Nessun shellbot: usa il primo disponibile
                        if self.ollama.model not in all_models:
                            self.ollama.model = all_models[0]
                    
                    self.connected = True
                    self.session = self.session_manager.create_session()
                    self.root.after(0, self._on_connected)
                else:
                    self.root.after(0, self._on_connection_failed, "Ollama non risponde")
            except Exception as exc:
                self.root.after(0, self._on_connection_failed, str(exc))

        self._set_status("Connessione...", "warning")
        threading.Thread(target=connect, daemon=True).start()

    def _on_connected(self):
        """Callback per connessione riuscita."""
        self._set_status(" Connesso", "success")
        self.model_label.config(text=f"Modello: {self.ollama.model}")
        self.session_label.config(text=f"Sessione: {self.session.id[:8] if self.session else '--'}")

        # Mostra banner di benvenuto CON LISTA MODELLI
        self._show_welcome_banner()
        self._discover_specialized_models()

        # Popola lista modelli (TUTTI, non solo shellbot)
        self.models_listbox.delete(0, tk.END)
        if self.models:
            shell_models = [m for m in self.models if "shellbot" in m.lower()]
            if shell_models:
                self._add_message(f" {len(shell_models)} modelli shellBot su {len(self.models)} totali:", "success")
            else:
                self._add_message(f" {len(self.models)} modelli disponibili (nessuno shellBot):", "warning")
            
            for i, m in enumerate(self.models, 1):
                is_shell = "shellbot" in m.lower()
                is_active = m == self.ollama.model
                if is_active:
                    prefix = " "
                elif is_shell:
                    prefix = f" {i}. "
                else:
                    prefix = f"   {i}. "
                self.models_listbox.insert(tk.END, f"{prefix}{m}")
                self._add_message(f"  {prefix}{m}", "model_list")
        else:
            self._add_message(" Nessun modello disponibile", "warning")

        self.input_field.focus()

    def _show_welcome_banner(self):
        """Mostra banner di benvenuto con info complete."""
        self._add_message("============================================================", "banner")
        self._add_message("   Benvenuto in Ollama File System Bridge!                 ", "banner")
        self._add_message("============================================================", "banner")
        self._add_message("", "info")
        os_name = self.env_info.get("system", "?")
        shell_desc = self.env_info.get("description", "?")
        self._add_message(f"OS: {os_name} | Shell: {shell_desc}", "info")
        self._add_message("", "info")
        self._add_message(f" Modello attivo: {self.ollama.model}", "success")
        self._add_message("", "info")
        self._add_message(" MODALIT DISPONIBILI:", "system")
        self._add_message("    /fix   - Fixa codice esistente (legge file, non crea doc)", "info")
        self._add_message("    /new   - Crea nuovo progetto da zero (con claude.md)", "info")
        self._add_message("    /reverse - Genera documentazione (DOCUMENTAZIONE.md)", "info")
        self._add_message("", "info")
        self._add_message(" COMANDI UTILI:", "system")
        self._add_message("   /help  - Mostra tutti i comandi", "info")
        self._add_message("   /model <nome> - Cambia modello", "info")
        self._add_message("   /context - Mostra claude.md corrente", "info")
        self._add_message("   /safe, /auto, /test - Toggle impostazioni", "info")
        self._add_message("", "info")
        self._add_message(" Premi STOP per interrompere l'inferenza in corso", "warning")
        self._add_message("", "info")

    def _on_connection_failed(self, error):
        """Callback per connessione fallita."""
        self._set_status(" Disconnesso", "error")
        self.model_label.config(text="Modello: --")
        self._add_message(f" Errore connessione: {error}", "error")
        self._add_message(" Assicurati che 'ollama serve' sia in esecuzione.", "warning")
        self._add_message("   Poi clicca ' Aggiorna lista modelli'", "info")

    def _set_status(self, text, status_type):
        """Imposta lo stato nella barra."""
        colors = {
            "success": "#4ec9b0",
            "error": "#f44747",
            "warning": "#dcdcaa",
            "info": "#569cd6"
        }
        self.status_label.config(text=text, bg=colors.get(status_type, "#f44747"))

    def _add_message(self, text, msg_type="system"):
        """Aggiunge un messaggio alla chat."""
        self.chat_display.config(state=tk.NORMAL)

        timestamp = datetime.now().strftime("%H:%M:%S")

        if msg_type == "user":
            prefix = " TU"
            tag = "user"
        elif msg_type == "ai":
            prefix = " AI"
            tag = "ai"
        else:
            prefix = ""
            tag = msg_type

        if prefix:
            self.chat_display.insert(tk.END, f"[{timestamp}] {prefix}: ", tag)
        self.chat_display.insert(tk.END, f"{text}\n", tag)
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def _on_enter_key(self, event):
        """Gestisce Enter per inviare."""
        self._send_message()
        return "break"

    def _stop_inference(self):
        """Ferma l'inferenza in corso."""
        if self.is_thinking:
            self.stop_flag = True
            self.is_thinking = False
            self.thinking_anim.stop()
            self._set_status(" Interrotto", "warning")
            self._add_message(" Inferenza interrotta dall'utente", "warning")

            # Abilita pulsanti
            self.send_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _send_message(self):
        """Invia il messaggio corrente."""
        if self.is_thinking:
            messagebox.showwarning("Attendi", "L'LLM sta ancora elaborando...\nPremi STOP per interrompere.")
            return

        message = self.input_field.get("1.0", tk.END).strip()
        if not message:
            return

        if not self.connected or not self.ollama:
            messagebox.showwarning("Attenzione", "Ollama non  connesso!\nControlla che 'ollama serve' sia attivo.")
            return

        #  CONTROLLA SE  UN COMANDO LOCALE (inizia con /)
        if message.startswith('/'):
            self._execute_local_command(message)
            return

        #  Auto-detect reverse engineering da richiesta naturale con path
        auto_path = self._extract_path_from_text(message)
        if auto_path and (self._looks_like_reverse_intent(message) or self._is_just_path(message, auto_path)):
            self._add_message(message, "user")
            self.input_field.delete("1.0", tk.END)
            self.stop_flag = False
            self._add_message(f" Reverse Engineering di: {auto_path}", "info")
            self._reverse_engineer_gui(auto_path)
            return

        # Reset stop flag
        self.stop_flag = False

        # Aggiungi messaggio utente
        self._add_message(message, "user")
        self.input_field.delete("1.0", tk.END)

        # Avvia elaborazione
        self._process_message(message)

    def _execute_local_command(self, cmd):
        """
        Esegue i comandi locali (quelli che iniziano con /).
        Questi comandi NON vengono inviati all'LLM.
        """
        cmd = cmd.strip()
        parts = cmd.split(None, 1)  # Separa comando e argomenti
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        self.input_field.delete("1.0", tk.END)

        # Gestisci i comandi
        if command == '/exit' or command == '/quit' or command == '/q':
            if messagebox.askyesno("Esci", "Uscire dall'applicazione?"):
                self.root.quit()

        elif command == '/help':
            self._show_help()

        elif command == '/model':
            if args:
                self._change_model(args)
            else:
                self._add_message(f" Modello corrente: {self.ollama.model}", "info")
                self._add_message(" Usa: /model <nome_modello>", "info")
                if self.models:
                    self._add_message(" Modelli disponibili:", "info")
                    for i, m in enumerate(self.models, 1):
                        cur = " " if m == self.ollama.model else f"{i}. "
                        self._add_message(f"  {cur}{m}", "model_list")

        elif command == '/context':
            self._show_context()

        elif command == '/safe':
            self._toggle_safe()

        elif command == '/auto':
            self._toggle_auto()

        elif command == '/test':
            self._toggle_test()

        elif command == '/clear':
            self._clear_chat()

        elif command == '/fix':
            self.mode = 'fix'
            # NON cambiare modello se l'utente ha scelto un modello "full coder" (es. qwen2.5-coder)
            current_model_lower = (self.ollama.model or "").lower()
            is_full_coder = any(x in current_model_lower for x in ['qwen', 'coder', 'sushi'])
            
            if not is_full_coder:
                tag = self.model_create or (self.models[0] if self.models else None)
                if tag and self.ollama and self.ollama.model != tag:
                    self.ollama.model = tag
                    self._add_message(f" Modello: {tag} (CREATE/FIX)", "info")
                elif not tag:
                    self._add_message(" Nessun modello shellbot CREATE trovato", "warning")
            else:
                self._add_message(f" Uso {self.ollama.model} (modelllo completo - pianifico + eseguo)", "info")
            
            self._add_message(" Modalit FIX attivata", "success")
            self._add_message("   Legger file esistenti prima di agire", "info")
            self._add_message("   Non creer README.md (usa claude.md)", "info")
            self._add_message("   Aggiorner claude.md con i fix effettuati", "info")
            self._add_message(" Ora scrivi la richiesta di fix con path (es: 'fixa il gioco in C:\\path\\progetto')", "system")

        elif command == '/new':
            self.mode = 'new'
            # NON cambiare modello se l'utente ha scelto un modello "full coder" (es. qwen2.5-coder)
            current_model_lower = (self.ollama.model or "").lower()
            is_full_coder = any(x in current_model_lower for x in ['qwen', 'coder', 'sushi'])
            
            if not is_full_coder:
                tag = self.model_create or (self.models[0] if self.models else None)
                if tag and self.ollama and self.ollama.model != tag:
                    self.ollama.model = tag
                    self._add_message(f" Modello: {tag} (CREATE/FIX)", "info")
                elif not tag:
                    self._add_message(" Nessun modello shellbot CREATE trovato", "warning")
            else:
                self._add_message(f" Uso {self.ollama.model} (modelllo completo - pianifico + eseguo)", "info")
            
            self._add_message(" Modalit NEW PROJECT attivata", "success")
            self._add_message("   Pu creare claude.md per tracciamento", "info")
            self._add_message("   Struttura completa del progetto", "info")
            self._add_message(" Ora scrivi cosa creare (es: 'crea un gioco del tris in /path')", "system")

        elif command == '/reverse':
            if args:
                target_path = Path(self._strip_surrounding_quotes(args.strip()))
                if not target_path.exists():
                    self._add_message(f" Path non trovato: {target_path}", "error")
                    return
                self._add_message(f" Reverse Engineering di: {target_path}", "info")
                self._reverse_engineer_gui(target_path)
            else:
                self._add_message(" Reverse Engineering", "info")
                self._add_message(" Usa: /reverse /path/del/progetto", "system")

        elif command == '/session' or command == '/sessions':
            self._add_message(f" Sessione corrente: {self.session.id if self.session else 'Nessuna'}", "info")

        else:
            self._add_message(f" Comando sconosciuto: {command}", "error")
            self._add_message(" Usa /help per vedere tutti i comandi", "info")

    def _strip_surrounding_quotes(self, text: str) -> str:
        t = text.strip()
        if len(t) >= 2 and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
            return t[1:-1]
        return t

    def _is_just_path(self, text: str, path: Path) -> bool:
        t = text.strip()
        p = str(path)
        return t == p or t == f'"{p}"' or t == f"'{p}'"

    def _looks_like_reverse_intent(self, text: str) -> bool:
        t = text.lower()
        keywords = [
            "reverse", "documentazione", "documenta", "cosa fa", "descrivi",
            "spiega", "capire", "analizza", "analisi", "panoramica"
        ]
        return any(k in t for k in keywords)

    def _extract_path_from_text(self, text: str) -> Path | None:
        # 1) Cerca path tra virgolette
        for match in re.findall(r"[\"']([^\"']+)[\"']", text):
            candidate = match.strip().rstrip(".,);")
            p = Path(candidate)
            if p.exists():
                return p

        # 2) Windows assoluto non quotato
        m = re.search(r"([A-Za-z]:\\[^\\n\"']+)", text)
        if m:
            candidate = m.group(1).strip().rstrip(".,);")
            p = Path(candidate)
            if p.exists():
                return p

        # 3) POSIX assoluto non quotato
        m = re.search(r"(/[^\\s\"']+)", text)
        if m:
            candidate = m.group(1).strip().rstrip(".,);")
            p = Path(candidate)
            if p.exists():
                return p

        return None

    def _show_help(self):
        """Mostra aiuto completo."""
        self._add_message("", "banner")
        self._add_message("   COMANDI DISPONIBILI                                     ", "banner")
        self._add_message("", "banner")
        self._add_message("", "info")
        self._add_message(" MODALIT DI LAVORO:", "system")
        self._add_message("   /fix         - Fixa codice esistente", "info")
        self._add_message("   /new         - Crea nuovo progetto da zero", "info")
        self._add_message("   /reverse     - Genera documentazione", "info")
        self._add_message("", "info")
        self._add_message(" GESTIONE:", "system")
        self._add_message("  /help          - Mostra questo aiuto", "info")
        self._add_message("  /model <nome>  - Cambia modello LLM", "info")
        self._add_message("  /context       - Mostra claude.md corrente", "info")
        self._add_message("  /safe          - Toggle safety (ON/OFF)", "info")
        self._add_message("  /auto          - Auto-continue (ON/OFF)", "info")
        self._add_message("  /test          - Auto-test (ON/OFF)", "info")
        self._add_message("  /clear         - Pulisci la chat", "info")
        self._add_message("  /exit          - Esci dall'applicazione", "info")
        self._add_message("", "info")
        self._add_message(" Esempi:", "system")
        self._add_message("  /fix", "code")
        self._add_message("  fixa il gioco del tris che non parte", "code")
        self._add_message("", "info")
        self._add_message("  /model qwen2.5-coder:14b", "code")
        self._add_message("", "info")
        self._add_message("  /new", "code")
        self._add_message("  crea un gestionale per biblioteca in /path/proj", "code")

    def _change_model(self, model_name):
        """Cambia il modello LLM."""
        self._add_message(f" Cambio modello: {model_name}...", "info")

        # Cerca il modello nella lista
        model_found = None
        model_name_lower = model_name.lower()

        for m in self.models:
            if m.lower() == model_name_lower or model_name_lower in m.lower():
                model_found = m
                break

        if model_found:
            # Aggiorna config
            self.ollama.model = model_found
            self.state['model'] = model_found

            # Salva stato
            try:
                with open(STATE_FILE, 'w') as f:
                    json.dump(self.state, f, indent=2)
            except:
                pass

            self.model_label.config(text=f"Modello: {model_found}")
            self._add_message(f" Modello cambiato: {model_found}", "success")

            # Nuova sessione con nuovo modello
            self.session = self.session_manager.create_session()
            self.session_label.config(text=f"Sessione: {self.session.id[:8]}")
        else:
            self._add_message(f" Modello non trovato: {model_name}", "error")
            self._add_message(" Usa /model senza argomenti per vedere la lista", "info")

    def _show_context(self):
        """Mostra il contenuto di claude.md se esiste."""
        if self.file_ops and self.file_ops.working_dir:
            claude_path = Path(self.file_ops.working_dir) / "claude.md"
            if not claude_path.exists():
                claude_path = Path(self.file_ops.working_dir) / "CLAUDE.md"

            if claude_path.exists():
                try:
                    content = claude_path.read_text(encoding='utf-8', errors='replace')
                    self._add_message(" Contenuto di claude.md:", "info")
                    self._add_message("" * 60, "system")
                    for line in content.split('\n')[:50]:  # Max 50 righe
                        self._add_message(line, "code")
                    if len(content.split('\n')) > 50:
                        self._add_message("... (troncato)", "info")
                except Exception as exc:
                    self._add_message(f" Errore lettura: {e}", "error")
            else:
                self._add_message(" Nessun claude.md trovato nella directory corrente", "warning")
        else:
            self._add_message(" Directory di lavoro non impostata", "warning")

    def _reverse_engineer_gui(self, target: Path):
        """Genera documentazione per un progetto in modalit GUI."""
        import pathlib
        
        def reverse_thread():
            self.is_thinking = True
            self.root.after(0, lambda: self._set_status(" Reverse engineering...", "warning"))
            self.root.after(0, lambda: self.thinking_anim.start(self.thinking_container))
            
            try:
                self._reverse_log(f"reverse_start target={target}")
                # Scansione struttura e indice file
                self.root.after(0, lambda: self._add_message(f" Scansione struttura: {target}", "info"))
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
                self.root.after(0, lambda d=policy.get("docs", []), r=policy.get("source_roots", []), c=policy.get("candidates_after", 0):
                    self._add_message(
                        f" Policy: docs={d if d else 'none'} | roots={r if r else 'all'} | candidati={c}",
                        "info",
                    )
                )

                seen_files = stats.get("seen_files", 0)
                ignored = stats.get("ignored_ext", 0) + stats.get("ignored_size", 0) + stats.get("ignored_other", 0)
                self.root.after(0, lambda s=seen_files, i=ignored, c=len(candidates), d=stats.get("ignored_dirs", 0):
                    self._add_message(
                        f" File visti: {s} | scartati scan: {i} | candidati(post-policy): {c} | dir ignorate: {d}",
                        "info",
                    )
                )
                self.root.after(0, lambda e=policy.get("excluded_tests", 0), cfg=policy.get("excluded_config", 0), lim=policy.get("limited", False), l=policy.get("limit", 0):
                    self._add_message(
                        f" Policy: test esclusi={e} | config esclusi={cfg} | limite candidati={l} | limitato={lim}",
                        "info",
                    )
                )
                if not candidates:
                    self._reverse_log("no_candidates")
                    self.root.after(0, lambda: self._add_message(" Nessun file rilevante trovato", "error"))
                    return
                tree = build_tree_from_paths(
                    [rel for rel, _, _ in candidates],
                    root_name=target.name,
                    max_lines=400,
                )
                self._reverse_log(f"tree_lines={tree.count(chr(10)) + 1 if tree else 0}")
                index_text, allowed_set = format_candidate_index(candidates)

                # Rileva se  un progetto Java PRIMA della selezione
                # Controlla se esistono file .java e pom.xml/build.gradle nella root
                has_java_files = any(
                    item[0].suffix.lower() == ".java"
                    for item in candidates
                )
                has_build_file = (target / "pom.xml").exists() or (target / "build.gradle").exists() or (target / "settings.gradle").exists()
                is_java_project = has_java_files and has_build_file
                is_spring = _is_spring_boot_project(target) if is_java_project else False
                
                if is_spring:
                    self.root.after(0, lambda: self._add_message(" Rilevato progetto SPRING BOOT - Priorit alle classi @Service", "success"))
                    self._reverse_log("spring_boot_project=True")
                
                java_instruction = ""
                if is_java_project:
                    java_instruction = """
 PROGETTO JAVA MICROSERVIZIO - REGOLE SPECIALI:
- PRIORIT 1: Leggi TUTTE le classi *Service.java (contengono la logica di business)
- PRIORIT 2: Leggi le classi *Controller.java (API endpoint) e la classe Application principale
- PRIORIT 3: Leggi *Repository.java e DTO solo se necessario per contesto
- Concentrati sulla logica di business nei Service layer
"""

                # Fase 1: selezione file da leggere
                select_prompt = f"""Sei un technical writer. Ti fornisco SOLO una struttura filtrata e l'indice file.

STRUTTURA FILTRATA:
{tree}

INDICE FILE (dimensione e tag):
{index_text}
{java_instruction}
Seleziona SOLO i file necessari per capire il progetto.
Regole:
- Max 12 file
- Evita log/build/temp/lock
- Preferisci entrypoint, config, e sorgenti principali

Rispondi SOLO con JSON:
{{"cmd1": "READ <percorso_relativo>", "cmd2": "READ <percorso_relativo>", ...}}
Non usare comandi shell, solo READ + path relativo."""

                self.session = self.session_manager.create_session()
                self.session.add_message("user", select_prompt)
                select_resp = ""
                for chunk in self.ollama.chat(self.session.to_ollama_messages(), stream=True):
                    if self.stop_flag:
                        self.root.after(0, lambda: self._add_message(" [Interrotto]", "warning"))
                        break
                    select_resp += chunk
                self._reverse_log(f"select_resp_len={len(select_resp)}")
                self._reverse_log(f"select_resp_raw={select_resp.strip()[:2000]}")

                selected_by_llm = []
                selection_source = "llm"
                p_sel = self.parser.parse(select_resp)
                if p_sel.is_valid and p_sel.commands:
                    selected_by_llm = extract_requested_files(p_sel.commands, target, allowed_set, max_files=12)
                    self._reverse_log(f"select_commands={len(p_sel.commands)} selected={len(selected_by_llm)}")
                else:
                    self._reverse_log("select_parse_failed")
                    
                # Per progetti Java: includi SEMPRE le classi Service (priorit massima)
                java_services = []
                java_controllers = []
                if is_java_project:
                    java_services = find_java_service_classes(candidates)
                    java_controllers = find_java_controller_classes(candidates)
                    if java_services:
                        self._reverse_log(f"java_services_found={len(java_services)}")
                        if is_spring:
                            self.root.after(0, lambda n=len(java_services):
                                self._add_message(f" {n} classi Service Spring trovate - INCLUSE AUTOMATICAMENTE", "success")
                            )
                        else:
                            self.root.after(0, lambda n=len(java_services):
                                self._add_message(f" Trovate {n} classi Service Java", "info")
                            )

                if not selected_by_llm:
                    selection_source = "fallback"
                    selected_by_llm = pick_default_files(candidates, limit=10)
                    self._reverse_log(f"fallback_selected={len(selected_by_llm)}")

                # Costruisci lista finale: PRIMA le Service (se Spring), poi le altre selezionate
                selected = []
                
                # Se  Spring Boot: metti Service ALL'INIZIO assolutamente
                if is_spring and java_services:
                    selected.extend(java_services)
                    self._reverse_log(f"spring_services_added_first={len(java_services)}")
                
                # Poi aggiungi le selezionate da LLM/fallback
                for item in selected_by_llm:
                    if item not in selected:
                        selected.append(item)
                
                # Aggiungi Controller se non sono gi inclusi (max 15 file totali)
                if java_controllers:
                    for ctrl in java_controllers:
                        if ctrl not in selected and len(selected) < 15:
                            selected.append(ctrl)

                # Includi sempre README/CLAUDE se presenti (aggiunti dal bridge)
                docs = find_primary_docs(target)
                added_docs = []
                for d in docs:
                    if d not in selected:
                        selected.insert(0, d)
                        added_docs.append(d)

                selected_list = "\n".join([f"- {p.as_posix()}" for p in selected])
                self._reverse_log("selected_files=" + ",".join([p.as_posix() for p in selected]))

                llm_list = "\n".join([f"- {p.as_posix()}" for p in selected_by_llm])
                label = "File selezionati dall'LLM" if selection_source == "llm" else "File selezionati di default"
                self.root.after(0, lambda s=llm_list, n=len(selected_by_llm), l=label:
                    self._add_message(f" {l} ({n}):\n{s}", "code")
                )
                if added_docs:
                    added_list = "\n".join([f"- {p.as_posix()}" for p in added_docs])
                    self.root.after(0, lambda s=added_list:
                        self._add_message(f" File aggiunti dal bridge (docs):\n{s}", "code")
                    )

                files_content, read_stats = read_files_content_with_stats(
                    target, selected, max_chars_per_file=4000, max_total_chars=20000
                )
                self._reverse_log(f"files_content_len={len(files_content)}")
                self._reverse_log(f"files_read={read_stats.get('files_read')} total_chars={read_stats.get('total_chars')} truncated={read_stats.get('truncated')}")
                if not files_content:
                    self._reverse_log("no_files_content")
                    self.root.after(0, lambda: self._add_message(" Nessun contenuto letto", "error"))
                    return
                self.root.after(0, lambda r=read_stats.get("files_read", 0), ch=read_stats.get("total_chars", 0):
                    self._add_message(f" File letti: {r} | caratteri totali: {ch}", "info")
                )

                # Fase 2: genera documentazione
                # Imposta opzioni per documentazione lunga
                original_num_predict = self.ollama.options.get('num_predict', 2048)
                original_num_ctx = self.ollama.options.get('num_ctx', 8192)
                original_timeout = self.ollama.timeout
                self.ollama.options['num_ctx'] = 16384
                self.ollama.options['num_predict'] = 8192  # Pi spazio per documentazione completa
                self.ollama.timeout = 600  # 10 minuti timeout
                self._reverse_log("llm_options num_ctx=16384 num_predict=8192 timeout=600")

                java_doc_instruction = ""
                if is_java_project:
                    java_doc_instruction = """
 PROGETTO JAVA MICROSERVIZIO - ISTRUZIONI SPECIALI:
- Concentrati sulle classi Service: descrivi la logica di business di ogni metodo pubblico
- Per ogni Service: elenca le dipendenze iniettate (@Autowired, constructor injection)
- Documenta le chiamate esterne: database (Repository), API esterne (RestTemplate, WebClient)
- Spiega il flusso: Controller riceve richiesta -> Service elabora -> Repository persiste
- Identifica i use case/business capability implementati
"""

                prompt = f"""Sei un technical writer esperto. Genera documentazione COMPLETA per questo progetto.
Usa SOLO i file forniti; se manca qualche informazione, dichiaralo.
{java_doc_instruction}
STRUTTURA FILTRATA:
{tree}

FILE SELEZIONATI:
{selected_list}

CONTENUTI FILE:
{files_content}

DOCUMENTAZIONE.md DEVE CONTENERE (IN QUESTO ORDINE):
1) PANORAMICA DEL PROGETTO
2) STRUTTURA DEL PROGETTO (ASCII TREE)
3) FILE PRINCIPALI
4) FLUSSO DI ESECUZIONE
5) API / FUNZIONI PUBBLICHE
6) CONFIGURAZIONE
7) NOTE AGGIUNTIVE

Genera DOCUMENTAZIONE.md in ITALIANO (minimo 800 parole).
Rispondi SOLO con comandi JSON per creare DOCUMENTAZIONE.md:"""

                self.session = self.session_manager.create_session()
                self.session.add_message("user", prompt)
                response = ""
                for chunk in self.ollama.chat(self.session.to_ollama_messages(), stream=True):
                    if self.stop_flag:
                        self.root.after(0, lambda: self._add_message(" [Interrotto]", "warning"))
                        break
                    response += chunk
                self._reverse_log(f"final_resp_len={len(response)}")

                # Ripristina opzioni
                self.ollama.options['num_predict'] = original_num_predict
                self.ollama.options['num_ctx'] = original_num_ctx
                self.ollama.timeout = original_timeout
                self.root.after(0, lambda: self.thinking_anim.stop())

                if response:
                    self.root.after(0, lambda: self._add_message(f" Response ({len(response)} chars):", "info"))
                    self.root.after(0, lambda: self._add_message(response[:2000] + ("..." if len(response) > 2000 else ""), "code"))

                    parsed = self.parser.parse(response)
                    if parsed.is_valid and parsed.commands:
                        self._reverse_log(f"final_commands={len(parsed.commands)}")
                        self.root.after(0, lambda: self._add_message(f" {len(parsed.commands)} comandi", "success"))
                        for i, cmd in enumerate(parsed.commands, 1):
                            ok, out = self.file_ops.execute_command(cmd)
                            if ok:
                                self.root.after(0, lambda idx=i: self._add_message(f" Comando {idx} eseguito", "success"))
                            else:
                                self.root.after(0, lambda e=out, idx=i: self._add_message(f" Comando {idx}: {e}", "error"))

                        doc_file = target / "DOCUMENTAZIONE.md"
                        if doc_file.exists():
                            self.root.after(0, lambda: self._add_message(f" Documentazione salvata: {doc_file}", "success"))
                            content = doc_file.read_text(encoding='utf-8', errors='replace')[:1500]
                            self.root.after(0, lambda c=content: self._add_message(f"\n{c}...", "code"))
                    else:
                        # fallback: salva response come doc se contiene markdown
                        self.root.after(0, lambda: self._add_message(" Salvataggio manuale della documentazione...", "info"))
                        doc_file = target / "DOCUMENTAZIONE.md"
                        md_start = response.find('# ')
                        if md_start >= 0:
                            doc_content = response[md_start:]
                            doc_content = doc_content.replace('\\n', '\n')
                            doc_content = re.sub(r' +\n', '\n', doc_content)
                            doc_content = re.sub(r'\n{3,}', '\n\n', doc_content)
                            try:
                                doc_file.write_text(doc_content)
                                self.root.after(0, lambda: self._add_message(f" Documentazione salvata: {doc_file}", "success"))
                                self.root.after(0, lambda: self._add_message(" Contenuto convertito: \\n  newline reali", "info"))
                            except Exception as exc:
                                self.root.after(0, lambda e=e: self._add_message(f" Salvataggio fallito: {e}", "warning"))
                else:
                    self.root.after(0, lambda: self._add_message(" Nessuna risposta", "warning"))
                    
            except Exception as exc:
                error_msg = str(exc)
                self.root.after(0, lambda err=error_msg: self._add_message(f" Errore: {err}", "error"))
            finally:
                self.is_thinking = False
                self.root.after(0, lambda: self._set_status(" Connesso", "success"))
                self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))
        
        threading.Thread(target=reverse_thread, daemon=True).start()
        self.send_btn.config(state=tk.DISABLED)

    def _toggle_safe(self):
        """Toggle safety mode."""
        self.state['safe'] = not self.state.get('safe', True)
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
        status = "ON" if self.state['safe'] else "OFF"
        self._add_message(f" Safety: {status}", "success")
        if self.state['safe']:
            self._add_message("   Comandi distruttivi richiederanno conferma", "info")
        else:
            self._add_message("   Attenzione: comandi distruttivi eseguiti senza conferma", "warning")

    def _toggle_auto(self):
        """Toggle auto-continue."""
        self.state['auto_c'] = not self.state.get('auto_c', True)
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
        status = "ON" if self.state['auto_c'] else "OFF"
        self._add_message(f" Auto-continue: {status}", "success")

    def _toggle_test(self):
        """Toggle auto-test."""
        self.state['auto_t'] = not self.state.get('auto_t', True)
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
        status = "ON" if self.state['auto_t'] else "OFF"
        self._add_message(f" Auto-test: {status}", "success")

    def _process_message(self, user_message):
        """Elabora il messaggio con LLM in thread separato."""

        # Controlli preliminari
        if not self.session:
            self._add_message(" Sessione non inizializzata, ne creo una nuova...", "warning")
            self._new_session()

        if not self.ollama or not self.connected:
            self._add_message(" Ollama non  connesso", "error")
            self._add_message(" Verifica che 'ollama serve' sia in esecuzione", "info")
            return

        def process(Path=Path):
            self.is_thinking = True
            self.root.after(0, lambda: self._set_status(" Pensando...", "warning"))
            self.root.after(0, lambda: self.thinking_anim.start(self.thinking_container))

            # Disabilita pulsanti
            self.root.after(0, lambda: self.send_btn.config(state=tk.DISABLED))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))

            try:
                #  ESTRAI PATH dal messaggio utente (per /fix o fix di progetto esistente)
                # path_match = re.search(r'(/[a-zA-Z0-9_./-]+)', user_message)
                auto_path = self._extract_path_from_text(user_message)
                project_path = None
                if auto_path:
                    project_path = Path(auto_path)
                    if not project_path.exists():
                        project_path = None

                # WORKFLOW AGENTICO DETERMINISTICO PER /new e /fix
                current_mode = getattr(self, 'mode', 'default')
                if current_mode in {'new', 'fix'}:
                    if current_mode == 'fix' and not project_path:
                        # In /fix, se il path non e' nel messaggio, usa la directory corrente selezionata in GUI.
                        try:
                            project_path = Path(self.file_ops.working_directory)
                        except Exception:
                            project_path = Path(".")
                        if not project_path.exists():
                            self.root.after(0, lambda: self._add_message(" [ERR] Path progetto non valido per /fix", "error"))
                            return
                    self._execute_agentic_workflow(user_message, project_path)
                    return

                #  RILEVA MODALIT /reverse
                is_reverse = "/reverse" in user_message.lower() or "reverse" in user_message.lower() or "documentazione" in user_message.lower()

                #  LEGGI FILE ESISTENTI se  un fix o reverse di progetto esistente
                file_context = ""
                if project_path and project_path.exists():
                    self.root.after(0, lambda: self._add_message(f" Lettura file da: {project_path}", "info"))

                    # Leggi file di codice + config + doc
                    code_files = []
                    
                    if is_reverse:
                        # Per /reverse leggi TUTTO ricorsivamente
                        self.root.after(0, lambda: self._add_message(" Modalit REVERSE: lettura completa del progetto...", "info"))
                        
                        # Prima leggi documentazione (*.md, *.txt, *.rst)
                        for ext in ['*.md', '*.txt', '*.rst', 'README*', 'LICENSE*']:
                            code_files.extend(project_path.rglob(ext))
                        
                        # Poi tutti i file di codice
                        for ext in ['*.py', '*.js', '*.ts', '*.jsx', '*.tsx', '*.java', '*.go', '*.rs', '*.cpp', '*.c', '*.h', '*.hpp', '*.cs', '*.php', '*.rb', '*.swift', '*.kt', '*.scala', '*.html', '*.css', '*.scss', '*.sass', '*.less', '*.sql', '*.yaml', '*.yml', '*.json', '*.xml', '*.toml', '*.ini', '*.cfg', '*.sh', '*.bash', '*.zsh', '*.ps1', '*.dockerfile', 'Dockerfile*', 'Makefile*', '*.gradle', '*.pom', '*.cargo']:
                            code_files.extend(project_path.rglob(ext))
                        
                        # Rimuovi duplicati e limita a 50 file per non saturare
                        code_files = list(set(code_files))[:50]
                    else:
                        # Per /fix leggi solo i file nella root
                        for ext in ['.html', '.js', '.py', '.java', '.css', '.ts', '.jsx', '.tsx', '.go', '.rs', '.cpp', '.c', '.h', '.sql', '.yaml', '.json', '.sh']:
                            code_files.extend(project_path.glob(f"*{ext}"))

                    # Leggi anche claude.md se esiste
                    claude_md = project_path / "claude.md"
                    if claude_md.exists():
                        file_context += f"## claude.md:\n```\n{claude_md.read_text(encoding='utf-8', errors='replace')[:1000]}\n```\n\n"

                    # Leggi file di codice
                    for f in code_files[:50 if is_reverse else 15]:  # Max 50 per reverse, 15 per fix
                        try:
                            content = f.read_text(encoding='utf-8', errors='replace')
                            rel_path = f.relative_to(project_path) if is_reverse else f.name
                            # Per reverse: pi contenuto per file (3000 chars)
                            max_chars = 3000 if is_reverse else 1500
                            file_context += f"## {rel_path}:\n```\n{content[:max_chars]}\n```\n\n"
                        except Exception as exc:
                            pass

                    if file_context:
                        self.root.after(0, lambda: self._add_message(f" Trovati {len(code_files)} file", "success"))
                        # Aggiungi contesto come primo messaggio
                        self.session.add_message("user", f"## Contesto file esistenti:\n\n{file_context}\n\n## PATH progetto: {project_path}")

                # Aggiungi messaggio utente
                self.session.add_message("user", user_message)

                # Debug: controlla che ci siano messaggi
                messages = self.session.to_ollama_messages()
                if not messages:
                    self.root.after(0, lambda: self._add_message(" Nessun messaggio nella sessione", "warning"))
                    return

                # Chiama Ollama
                response = ""
                for chunk in self.ollama.chat(messages, stream=True):
                    if self.stop_flag:
                        self.root.after(0, lambda: self._add_message(" [Interrotto dall'utente]", "warning"))
                        break
                    response += chunk

                # Controlla se la risposta  vuota
                if not response or not response.strip():
                    self.root.after(0, lambda: self._add_message(" Nessuna risposta dall'LLM", "warning"))
                    self.root.after(0, lambda: self._add_message(" Prova a riformulare la richiesta o cambia modello", "info"))
                else:
                    #  LOG COMPLETO DELLA RESPONSE
                    self.root.after(0, lambda: self._add_message(f" RAW Response ({len(response)} chars):", "info"))
                    self.root.after(0, lambda: self._add_message(response[:2000] + ("..." if len(response) > 2000 else ""), "code"))

                    #  PARSING ED ESECUZIONE COMANDI
                    parsed = self.parser.parse(response)

                    if not parsed.is_valid:
                        self.root.after(0, lambda: self._add_message(f" Parsing fallito: {parsed.error}", "error"))
                        self.root.after(0, lambda: self._add_message(f" Raw JSON: {parsed.raw_response[:500]}", "warning"))
                        self.session.add_message("assistant", response)
                    elif parsed.commands:
                        self.root.after(0, lambda: self._add_message(f" {len(parsed.commands)} comandi parsati", "success"))

                        # Esegui comandi - sincrono per evitare bug con lambda
                        for i, cmd in enumerate(parsed.commands, 1):
                            self.root.after(0, lambda c=cmd, idx=i: self._add_message(f"[{idx}] {c[:100]}...", "info"))
                            ok, out = self.file_ops.execute_command(cmd)
                            if ok:
                                output_msg = f" Comando {i} eseguito"
                                if out and len(out) < 500:
                                    output_msg += f"\n  Output: {out}"
                                self.root.after(0, lambda m=output_msg: self._add_message(m, "success"))
                            else:
                                self.root.after(0, lambda e=out, idx=i: self._add_message(f" Comando {idx} fallito: {e}", "error"))

                        self.session.add_message("assistant", response)
                    else:
                        self.session.add_message("assistant", response)
                        self.root.after(0, lambda: self._add_message(response, "ai"))

            except Exception as exc:
                # Gestione errori dettagliata
                error_msg = str(exc) if exc else "Errore sconosciuto"
                error_type = type(exc).__name__

                self.root.after(0, lambda: self._add_message(f" Errore ({error_type}): {error_msg}", "error"))

                # Suggerimenti basati sul tipo di errore
                if "Connection" in error_type or "connection" in error_msg.lower():
                    self.root.after(0, lambda: self._add_message(" Verifica che 'ollama serve' sia in esecuzione", "info"))
                elif "Timeout" in error_type or "timeout" in error_msg.lower():
                    self.root.after(0, lambda: self._add_message(" Il modello sta impiegando troppo tempo, prova con un modello pi veloce", "info"))
                elif "500" in error_msg:
                    self.root.after(0, lambda: self._add_message(" Errore interno di Ollama, prova a riavviare il servizio", "info"))
                elif "404" in error_msg:
                    self.root.after(0, lambda: self._add_message(" Modello non trovato, usa /model per cambiare", "info"))
                else:
                    self.root.after(0, lambda: self._add_message(" Riprova o controlla i log per dettagli", "info"))

                # Log su file per debug
                try:
                    from pathlib import Path
                    log_file = Path("./logs/gui_error.log")
                    log_file.parent.mkdir(exist_ok=True)
                    with open(log_file, 'a') as f:
                        f.write(f"[{datetime.now().isoformat()}] {error_type}: {error_msg}\n")
                        f.write(f"User message: {user_message[:200]}\n")
                        f.write(f"Session: {self.session.id if self.session else 'None'}\n")
                        f.write(f"Messages count: {len(self.session.messages) if self.session else 0}\n\n")
                except Exception as log_err:
                    self.root.after(0, lambda: self._add_message(f" Errore log: {log_err}", "warning"))

            finally:
                self.is_thinking = False
                self.stop_flag = False
                self.root.after(0, lambda: self.thinking_anim.stop())
                self.root.after(0, lambda: self._set_status(" Connesso", "success"))
                self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

        threading.Thread(target=process, daemon=True).start()

    def _workflow_settings(self) -> dict:
        wf = self.config.get("workflow", {}) if isinstance(self.config, dict) else {}
        plan_num_predict = wf.get("plan_num_predict", 900)
        plan_max_response_chars = wf.get("plan_max_response_chars", 20000)
        plan_max_retries = wf.get("plan_max_retries", 2)
        step_num_predict = wf.get("step_num_predict", 1200)
        step_max_response_chars = wf.get("step_max_response_chars", 20000)
        max_step_retries = wf.get("max_step_retries", 2)

        try:
            plan_num_predict = int(plan_num_predict)
        except Exception:
            plan_num_predict = 900
        try:
            plan_max_response_chars = int(plan_max_response_chars)
        except Exception:
            plan_max_response_chars = 20000
        try:
            plan_max_retries = int(plan_max_retries)
        except Exception:
            plan_max_retries = 2
        try:
            step_num_predict = int(step_num_predict)
        except Exception:
            step_num_predict = 1200
        try:
            step_max_response_chars = int(step_max_response_chars)
        except Exception:
            step_max_response_chars = 20000
        try:
            max_step_retries = int(max_step_retries)
        except Exception:
            max_step_retries = 2

        return {
            "plan_num_predict": max(256, plan_num_predict),
            "plan_max_response_chars": max(1000, plan_max_response_chars),
            "plan_max_retries": max(0, plan_max_retries),
            "step_num_predict": max(256, step_num_predict),
            "step_max_response_chars": max(1000, step_max_response_chars),
            "max_step_retries": max(0, max_step_retries),
        }

    def _infer_project_name(self, user_message: str) -> str:
        m = re.search(r"(?:crea|create|build)\s+([a-zA-Z0-9 _.-]{3,60})", user_message, re.IGNORECASE)
        if m:
            name = m.group(1).strip(" .:-")
            if name:
                return name
        return "Nuovo Progetto"

    def _list_project_code_files(self, project_path: Path, max_files: int = 80) -> list[str]:
        allowed_ext = {
            ".html", ".css", ".js", ".ts", ".py", ".java", ".cs", ".go", ".rs",
            ".cpp", ".c", ".h", ".hpp", ".json", ".yaml", ".yml", ".md", ".txt",
            ".xml", ".sql", ".sh", ".ps1",
        }
        excluded_names = {
            ".project_memory.json",
            "PLAN_SCHEMA.json",
            "STEP_CONTEXT.json",
            "claude.md",
            "claude_plan.md",
        }
        names: list[str] = []
        try:
            for item in project_path.iterdir():
                if not item.is_file():
                    continue
                if item.name in excluded_names:
                    continue
                if item.suffix.lower() in allowed_ext:
                    names.append(item.name)
        except Exception:
            return []
        return sorted(names)[:max_files]

    def _run_local_project_diagnostics(self, project_path: Path, files: list[str]) -> list[tuple[str, str]]:
        """
        Diagnostica locale light senza LLM, riusa le validazioni cross-file.
        Utile in /fix per capire subito cosa non torna e passarlo al planner.
        """
        issues: list[tuple[str, str]] = []
        if not files:
            return issues

        step_context = {
            "steps": [
                {"num": idx + 1, "filename": name, "status": "pending"}
                for idx, name in enumerate(files)
            ]
        }

        for name in files:
            ext = Path(name).suffix.lower()
            if ext not in {".html", ".css", ".js", ".ts", ".py", ".java"}:
                continue
            try:
                ok, reason = self._validate_written_step_file(project_path, step_context, name)
                if not ok:
                    issues.append((name, reason))
            except Exception as exc:
                issues.append((name, f"Errore diagnostica locale: {exc}"))
        return issues[:12]

    def _build_planning_prompt(
        self,
        user_message: str,
        mode: str = "new",
        existing_files: list[str] | None = None,
        diagnostics: list[tuple[str, str]] | None = None,
    ) -> str:
        existing_files = existing_files or []
        diagnostics = diagnostics or []
        is_fix = (mode or "").lower() == "fix"

        extra_context = ""
        if is_fix:
            files_block = "\n".join(f"- {name}" for name in existing_files[:60]) or "- Nessun file rilevato"
            diag_block = "\n".join(f"- {name}: {reason}" for name, reason in diagnostics) or "- Nessuna anomalia locale rilevata"
            extra_context = (
                "\nCONTESTO FIX (PROGETTO ESISTENTE):\n"
                f"File modificabili rilevati:\n{files_block}\n\n"
                f"Diagnostica locale pre-fix:\n{diag_block}\n"
            )

        step_rule = "Ogni step crea un solo file." if not is_fix else "Ogni step modifica un solo file."
        fix_rules = (
            ""
            if not is_fix
            else (
                "\nREGOLE FIX AGGIUNTIVE:\n"
                "- Priorita': risolvi prima i problemi diagnostici elencati.\n"
                "- Modifica SOLO file esistenti, salvo richiesta esplicita di nuovi file.\n"
                "- In progetti HTML/CSS/JS: mantieni coerenza tra id/class HTML, selettori CSS e listener JS.\n"
            )
        )

        return f"""Sei un software architect senior.

Genera SOLO un JSON valido (nessun testo extra).

SCHEMA OBBLIGATORIO:
{{
  "app_summary": ["...", "..."],
  "steps": [
    {{
      "num": 1,
      "filename": "nome_file.estensione",
      "goal": "descrizione funzionale del file",
      "key_refs": ["riferimento 1", "riferimento 2"],
      "acceptance_checks": ["check 1", "check 2"]
    }}
  ]
}}

REGOLE:
- Nessun codice sorgente.
- Nessun comando shell/powershell.
- Massimo 8 step.
- {step_rule}
- filename deve avere estensione.
- acceptance_checks deve contenere da 2 a 4 check concreti.
- acceptance_checks deve descrivere verifiche osservabili (coerenza file o comportamento utente), non frasi vaghe.
- num deve essere progressivo (1..N).{fix_rules}
{extra_context}
Richiesta utente: {user_message}"""

    def _user_explicitly_requests_docs(self, user_message: str) -> bool:
        text = (user_message or "").lower()
        keywords = [
            "readme",
            "documentazione",
            "documentation",
            "docs",
            "manuale",
            "guida",
        ]
        return any(k in text for k in keywords)

    def _strip_doc_steps_for_new_mode(self, steps: list[dict], user_message: str) -> tuple[list[dict], list[str]]:
        """
        In /new evita file documentali non richiesti esplicitamente (es. README.md).
        Mantiene intatta la pipeline ma previene artefatti non desiderati.
        """
        if self._user_explicitly_requests_docs(user_message):
            return steps, []

        doc_like = {
            "readme.md",
            "documentation.md",
            "documentazione.md",
            "docs.md",
            "manuale.md",
            "guida.md",
        }
        removed: list[str] = []
        filtered: list[dict] = []
        for step in steps:
            filename = Path(str(step.get("filename", ""))).name.lower()
            if filename in doc_like:
                removed.append(Path(str(step.get("filename", ""))).name)
                continue
            filtered.append(step)

        for idx, step in enumerate(filtered, 1):
            step["num"] = idx

        return filtered, removed

    def _sanitize_llm_response(self, text: str) -> str:
        clean = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"^```(?:json)?\s*", "", clean.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean.strip(), flags=re.DOTALL)
        return clean.strip()

    def _extract_first_json_object(self, text: str) -> dict | None:
        clean = self._sanitize_llm_response(text)
        if not clean:
            return None

        start = clean.find("{")
        if start < 0:
            return None

        candidate = clean[start:]
        depth = 0
        in_string = False
        escape_next = False

        for idx, char in enumerate(candidate):
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                if in_string:
                    escape_next = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    raw_json = candidate[:idx + 1]
                    try:
                        obj = json.loads(raw_json)
                        return obj if isinstance(obj, dict) else None
                    except Exception:
                        return None
        return None

    def _validate_plan_schema(self, plan_obj: dict | None) -> tuple[bool, str | None, dict | None]:
        if not isinstance(plan_obj, dict):
            return False, "Plan non e' un oggetto JSON", None

        app_summary = plan_obj.get("app_summary")
        steps = plan_obj.get("steps")

        if not isinstance(app_summary, list) or not app_summary:
            return False, "Campo app_summary mancante o non valido", None
        summary_clean = [str(s).strip() for s in app_summary if str(s).strip()]
        if len(summary_clean) < 1:
            return False, "app_summary vuoto", None

        if not isinstance(steps, list) or not steps:
            return False, "Campo steps mancante o non valido", None

        normalized_steps: list[dict] = []
        seen_filenames: set[str] = set()

        for idx, raw_step in enumerate(steps, 1):
            if not isinstance(raw_step, dict):
                return False, f"Step {idx} non e' oggetto", None

            raw_num = raw_step.get("num")
            filename = Path(str(raw_step.get("filename", "")).strip()).name
            goal = str(raw_step.get("goal", "")).strip()
            key_refs = raw_step.get("key_refs")
            acceptance_checks = raw_step.get("acceptance_checks")

            if not isinstance(raw_num, int):
                return False, f"Step {idx}: num non valido", None
            if not filename or "." not in filename:
                return False, f"Step {idx}: filename non valido", None
            if filename.lower() in seen_filenames:
                return False, f"Step {idx}: filename duplicato ({filename})", None
            if not goal:
                return False, f"Step {idx}: goal mancante", None
            if not isinstance(key_refs, list) or not key_refs:
                return False, f"Step {idx}: key_refs mancanti", None
            if not isinstance(acceptance_checks, list):
                return False, f"Step {idx}: acceptance_checks mancanti", None

            key_refs_clean = [str(x).strip() for x in key_refs if str(x).strip()]
            checks_clean = [str(x).strip() for x in acceptance_checks if str(x).strip()]
            if not key_refs_clean:
                return False, f"Step {idx}: key_refs vuoti", None
            if len(checks_clean) < 2 or len(checks_clean) > 4:
                return False, f"Step {idx}: acceptance_checks deve avere 2-4 elementi", None

            seen_filenames.add(filename.lower())
            normalized_steps.append({
                "num": raw_num,
                "filename": filename,
                "goal": goal,
                "plan_references": key_refs_clean[:10],
                "acceptance_checks": checks_clean[:4],
                "status": "pending",
            })

        normalized_steps = sorted(normalized_steps, key=lambda s: s["num"])
        for i, step in enumerate(normalized_steps, 1):
            if step["num"] != i:
                return False, "Numerazione step non progressiva", None

        return True, None, {
            "app_summary": summary_clean[:3],
            "steps": normalized_steps[:8],
        }

    def _render_claude_md(self, app_summary: list[str], steps: list[dict]) -> str:
        lines: list[str] = []
        lines.append("## App Summary")
        for point in app_summary[:3]:
            lines.append(f"- {point}")
        lines.append("")
        lines.append("## Steps")
        for step in steps:
            lines.append(f"### Step {step['num']} - `{step['filename']}`")
            lines.append(f"Goal: {step.get('goal', '')}")
            lines.append("Key references:")
            refs = step.get("plan_references") or []
            for ref in refs:
                lines.append(f"- {ref}")
            lines.append("Acceptance checks:")
            checks = step.get("acceptance_checks") or []
            for check in checks:
                lines.append(f"- {check}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _sanitize_plan_response(self, plan_resp: str) -> str:
        clean = re.sub(r"<think>.*?</think>", "", plan_resp or "", flags=re.DOTALL | re.IGNORECASE).strip()
        cleaned_lines = []
        for line in clean.splitlines():
            low = line.lower()
            if "vietato" in low and "step" not in low:
                continue
            if "non scrivere codice" in low:
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    def _extract_summary_points(self, plan_text: str) -> list[str]:
        summary_points: list[str] = []
        summary_match = re.search(
            r"##\s*(?:App\s*Summary|Descrizione\s*Progetto|Sommario)\s*(.*?)(?=\n##\s*Steps|\Z)",
            plan_text,
            re.IGNORECASE | re.DOTALL,
        )
        if summary_match:
            for line in summary_match.group(1).splitlines():
                stripped = line.strip()
                if re.match(r"^[-*]\s+", stripped):
                    summary_points.append(re.sub(r"^[-*]\s+", "", stripped).strip())
                elif stripped and len(summary_points) < 3:
                    summary_points.append(stripped)
        if not summary_points:
            fallback_lines = [l.strip() for l in plan_text.splitlines() if l.strip()]
            summary_points = fallback_lines[:3]
        return summary_points[:3]

    def _parse_plan_steps(self, plan_text: str) -> dict:
        steps: list[dict] = []
        summary_points = self._extract_summary_points(plan_text)

        step_pattern = re.compile(
            r"###\s*Step\s*(\d+)\s*[-:]\s*`([^`]+)`\s*(.*?)(?=\n###\s*Step\s*\d+|\Z)",
            re.IGNORECASE | re.DOTALL,
        )

        for match in step_pattern.finditer(plan_text):
            step_num = int(match.group(1))
            filename = Path(match.group(2).strip()).name
            body = match.group(3).strip()

            goal = ""
            goal_match = re.search(r"(?:Goal|Scopo)\s*:\s*(.+)", body, re.IGNORECASE)
            if goal_match:
                goal = goal_match.group(1).strip()
            if not goal:
                for line in body.splitlines():
                    candidate = line.strip(" -*\t")
                    if not candidate:
                        continue
                    if candidate.lower().startswith("key references"):
                        continue
                    goal = candidate
                    break
            if not goal:
                goal = f"Implementa il file {filename}"

            plan_references: list[str] = []
            in_refs = False
            for raw_line in body.splitlines():
                line = raw_line.strip()
                if re.match(r"^Key\s*references?\s*:", line, re.IGNORECASE):
                    in_refs = True
                    tail = line.split(":", 1)[1].strip()
                    if tail:
                        plan_references.append(tail)
                    continue
                if in_refs:
                    if line.startswith("-") or line.startswith("*"):
                        plan_references.append(line[1:].strip())
                        continue
                    if not line:
                        continue
                    if re.match(r"^[A-Za-z ]+\s*:", line):
                        break
                    plan_references.append(line)

            steps.append({
                "num": step_num,
                "filename": filename,
                "goal": goal,
                "plan_references": plan_references[:8],
                "status": "pending",
            })

        if not steps:
            fallback_files: list[tuple[int, str, str]] = []
            seen_files: set[str] = set()
            for line in plan_text.splitlines():
                m = re.search(r"`([^`]+\.[A-Za-z0-9_-]+)`", line)
                if not m:
                    continue
                filename = Path(m.group(1).strip()).name
                if filename.lower() in seen_files:
                    continue
                seen_files.add(filename.lower())
                fallback_files.append((len(fallback_files) + 1, filename, line.strip()))

            for num, filename, raw_goal in fallback_files:
                steps.append({
                    "num": num,
                    "filename": filename,
                    "goal": raw_goal or f"Implementa il file {filename}",
                    "plan_references": [],
                    "status": "pending",
                })

        steps = sorted(steps, key=lambda s: s["num"])
        for idx, step in enumerate(steps, 1):
            step["num"] = idx

        return {
            "app_summary": summary_points,
            "steps": steps,
        }

    def _step_context_file(self, project_path: Path) -> Path:
        return project_path / "STEP_CONTEXT.json"

    def _write_step_context(self, project_path: Path, context: dict) -> None:
        context["last_updated"] = datetime.now().isoformat()
        self._step_context_file(project_path).write_text(
            json.dumps(context, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _init_step_context(self, project_path: Path, app_summary: list[str], steps: list[dict]) -> dict:
        ordered_steps = []
        for step in sorted(steps, key=lambda s: s["num"]):
            ordered_steps.append({
                "num": step["num"],
                "filename": step["filename"],
                "goal": step.get("goal", f"Implementa il file {step['filename']}"),
                "status": "pending",
                "plan_references": step.get("plan_references", []),
                "acceptance_checks": step.get("acceptance_checks", []),
            })

        context = {
            "app_summary": app_summary[:3],
            "steps": ordered_steps,
            "current_step": ordered_steps[0]["num"] if ordered_steps else None,
            "key_references_by_file": {},
            "last_updated": datetime.now().isoformat(),
        }
        self._write_step_context(project_path, context)
        return context

    def _set_step_status(self, project_path: Path, context: dict, step_num: int, status: str) -> None:
        for step in context.get("steps", []):
            if step.get("num") == step_num:
                step["status"] = status
                break

        if status == "done":
            next_pending = next((s["num"] for s in context.get("steps", []) if s.get("status") == "pending"), None)
            context["current_step"] = next_pending
        else:
            context["current_step"] = step_num

        self._write_step_context(project_path, context)

    def _collect_key_references(self, memory: ProjectMemory) -> dict:
        key_refs: dict = {}
        contracts = memory.get_all_contracts() if memory else {}
        for filename, info in contracts.items():
            elements = (info or {}).get("elements", {})
            extracted: dict = {}
            for key in ["ids", "classes", "button_ids", "functions", "variables", "selectors", "used_ids", "used_classes"]:
                values = elements.get(key) or []
                cleaned = sorted(set(str(v).strip() for v in values if str(v).strip()))
                if cleaned:
                    extracted[key] = cleaned
            for key in ["has_css_link", "has_js_link", "has_inline_style", "has_inline_script"]:
                if key in elements and elements.get(key):
                    extracted[key] = elements[key][0]
            if extracted:
                key_refs[filename] = extracted
        return key_refs

    def _format_key_reference_lines(self, refs: dict) -> list[str]:
        lines: list[str] = []
        labels = {
            "ids": "ids",
            "classes": "classes",
            "button_ids": "button_ids",
            "functions": "functions",
            "variables": "variables",
            "selectors": "selectors",
            "used_ids": "used_ids",
            "used_classes": "used_classes",
            "has_css_link": "has_css_link",
            "has_js_link": "has_js_link",
            "has_inline_style": "has_inline_style",
            "has_inline_script": "has_inline_script",
        }
        for key, label in labels.items():
            if key not in refs:
                continue
            value = refs[key]
            if isinstance(value, list):
                lines.append(f"- {label}: {', '.join(value[:12])}")
            else:
                lines.append(f"- {label}: {value}")
        return lines

    def _build_step_brief(self, user_message: str, step_context: dict, step: dict, key_references_by_file: dict) -> str:
        summary = step_context.get("app_summary") or [user_message]
        step_lines = []
        for s in step_context.get("steps", []):
            status = s.get("status", "pending")
            step_lines.append(f"- Step {s.get('num')}: {s.get('filename')} [{status}]")

        prev_files = [
            s.get("filename")
            for s in step_context.get("steps", [])
            if s.get("num", 0) < step.get("num", 0) and s.get("status") == "done"
        ]

        ref_lines: list[str] = []
        for filename in prev_files:
            refs = key_references_by_file.get(filename)
            if not refs:
                continue
            ref_lines.append(f"{filename}:")
            ref_lines.extend(self._format_key_reference_lines(refs))

        if not ref_lines:
            ref_lines = ["- Nessun riferimento disponibile dai file precedenti."]

        plan_refs = step.get("plan_references", [])
        plan_ref_lines = [f"- {r}" for r in plan_refs] if plan_refs else ["- Nessun riferimento aggiuntivo nel piano."]
        acceptance = step.get("acceptance_checks", [])
        acceptance_lines = [f"- {a}" for a in acceptance] if acceptance else ["- Nessun check definito."]

        summary_lines = [f"{idx}. {item}" for idx, item in enumerate(summary, 1)]

        return "\n".join([
            "STIAMO FACENDO QUESTA APPLICAZIONE:",
            *summary_lines,
            "",
            "STATO STEP:",
            *step_lines,
            "",
            f"ADESSO SIAMO NELLO STEP {step['num']}: implementa `{step['filename']}`.",
            f"Obiettivo dello step: {step.get('goal', '')}",
            "",
            "RIFERIMENTI CHIAVE DAI FILE PRECEDENTI:",
            *ref_lines,
            "",
            "RIFERIMENTI CHIAVE NEL PIANO PER QUESTO STEP:",
            *plan_ref_lines,
            "",
            "ACCEPTANCE CHECKS STEP CORRENTE:",
            *acceptance_lines,
        ])

    def _build_step_file_rules(self, filename: str) -> str:
        ext = Path(filename).suffix.lower().lstrip(".")
        model_name = (getattr(self, "ollama", None).model or "").lower() if getattr(self, "ollama", None) else ""
        prefer_plain_value = "qwen2.5-coder" in model_name
        if ext == "html":
            base = """REGOLE FILE HTML:
- Scrivi HTML completo e valido.
- Non usare placeholder o testo descrittivo al posto del codice.
- Se il piano richiede file esterni, includi i riferimenti necessari.
- Per elementi interattivi ripetuti usa hook stabili per JS (classi coerenti e, quando utile, attributi `data-*`)."""
            if prefer_plain_value:
                base += "\n- Per questo modello evita here-string PowerShell: usa `-Value '...'` con `\\n`."
            return base
        if ext == "css":
            base = """REGOLE FILE CSS:
- Solo CSS, nessun HTML o JS.
- Nessun placeholder.
- Mantieni coerenza con ID/classi dichiarate nei riferimenti chiave.
- Se in HTML ci sono controlli interattivi (button/input/link d'azione), includi selettori che li stilizzano davvero (#id, .classe o tag coerente)."""
            if prefer_plain_value:
                base += "\n- Per questo modello evita here-string PowerShell: usa `-Value '...'` con `\\n`."
            return base
        if ext in {"js", "ts"}:
            base = """REGOLE FILE JS/TS:
- Solo codice JS/TS, nessun markdown.
- Funzioni complete, nessun placeholder.
- Mantieni coerenza con i riferimenti chiave.
- Non usare commenti HTML (`<!-- -->`) in file JS/TS.
- Se esistono controlli UI in HTML, collega gli handler agli elementi realmente presenti.
- Se usi `getElementById/querySelector`, i selettori devono esistere in HTML.
- Per contenuti multilinea preferisci here-string PowerShell (`-Value @' ... '@`)."""
            if prefer_plain_value:
                base += "\n- Per questo modello evita here-string PowerShell: usa `-Value '...'` con `\\n`."
            return base
        if ext == "py":
            base = """REGOLE FILE PY:
- Solo codice Python valido.
- Nessun placeholder.
- Mantieni il file autosufficiente per il suo scopo."""
            if prefer_plain_value:
                base += "\n- Per questo modello evita here-string PowerShell: usa `-Value '...'` con `\\n`."
            return base
        return """REGOLE FILE:
- Scrivi solo il contenuto completo del file richiesto.
- Nessun placeholder, nessuna spiegazione."""

    def _build_step_user_prompt(self, step: dict, total_steps: int, brief: str, file_rules: str) -> str:
        filename = step["filename"]
        model_name = (getattr(self, "ollama", None).model or "").lower() if getattr(self, "ollama", None) else ""
        multiline_rule = f"- Se il file e' multilinea, preferisci `Set-Content -Path '{filename}' -Value @' ... '@`."
        if "qwen2.5-coder" in model_name:
            multiline_rule = (
                f"- Se il file e' multilinea, usa `Set-Content -Path '{filename}' -Value 'riga1\\nriga2...'` "
                "(NO here-string `@' ... '@`)."
            )
        return f"""{brief}

{file_rules}

VINCOLI DI OUTPUT:
- Devi creare SOLO il file `{filename}`.
- Rispondi SOLO con JSON valido.
- Nessun testo extra fuori dal JSON.
- Usa comandi compatibili con PowerShell.
- Obbligatorio usare chiavi cmd1/cmd2/cmd3...
{multiline_rule}
- Vietato usare placeholder (es. CONTENUTO_COMPLETO).

Siamo allo step {step['num']}/{total_steps}."""

    def _build_step_retry_hint(self, filename: str, parse_error: str) -> str:
        reason = (parse_error or "errore non specificato").strip()
        return (
            "\n\nCORREZIONE OBBLIGATORIA:\n"
            f"- Errore precedente: {reason}\n"
            f"- File target obbligatorio: `{filename}`\n"
            "- Output solo oggetto JSON con cmd1/cmd2...\n"
            "- Comando completo: non troncare `-Value`, chiudi sempre stringhe o here-string.\n"
            "- Nessun testo extra, nessun markdown, nessun placeholder.\n"
        )

    def _step_num_predict_for_filename(self, wf: dict, filename: str) -> int:
        """Aumenta num_predict per file tendenzialmente piu' lunghi."""
        try:
            base = int((wf or {}).get("step_num_predict", 1200))
        except Exception:
            base = 1200

        ext = Path(filename or "").suffix.lower()
        if ext in {".js", ".ts"}:
            return max(base, 3200)
        if ext in {".py", ".java", ".cs"}:
            return max(base, 2600)
        if ext in {".html", ".css"}:
            return max(base, 2600)
        return max(base, 1200)

    def _extract_command_target_filename(self, cmd: str) -> str | None:
        cmd_str = (cmd or "").strip()

        if cmd_str.startswith("Set-Content") or cmd_str.startswith("Add-Content"):
            p_match = re.search(r"-Path\s+'([^']*)'", cmd_str)
            if not p_match:
                p_match = re.search(r"-Path\s+\"([^\"]*)\"", cmd_str)
            if p_match:
                return Path(p_match.group(1)).name
            return None

        heredoc_match = re.search(r"cat\s+<<\s*'?EOF'?\s*>\s*(.+?)(?:\s*\n|\s*\\n)", cmd_str)
        if heredoc_match:
            return Path(heredoc_match.group(1).strip().strip("'\"")).name

        return None

    def _commands_target_expected_file(self, commands: list[str], expected_filename: str) -> bool:
        expected = Path(expected_filename).name.lower()
        found_write_command = False
        for cmd in commands:
            target = self._extract_command_target_filename(cmd)
            if not target:
                continue
            found_write_command = True
            if Path(target).name.lower() != expected:
                return False
        return found_write_command

    def _is_write_command_string(self, text: str) -> bool:
        cmd = (text or "").strip()
        if not cmd:
            return False
        if cmd.startswith("Set-Content") or cmd.startswith("Add-Content"):
            return True
        return bool(re.search(r"cat\s+<<\s*'?EOF'?\s*>", cmd))

    def _extract_direct_file_content_from_response(self, response: str, filename: str) -> str | None:
        """
        Fallback: estrae contenuto file quando il modello restituisce JSON con cmd1 non-comando
        o direttamente un blocco codice.
        """
        clean = (response or "").strip()
        if not clean:
            return None

        # 1) JSON object con cmdN che contiene contenuto diretto (non comando)
        obj = self._extract_first_json_object(clean)
        if isinstance(obj, dict):
            cmd_keys = sorted(
                [k for k in obj.keys() if re.fullmatch(r"cmd\d+", str(k), re.IGNORECASE)],
                key=lambda k: int(re.search(r"\d+", str(k)).group(0)) if re.search(r"\d+", str(k)) else 10_000,
            )
            for key in cmd_keys:
                val = obj.get(key)
                if not isinstance(val, str):
                    continue
                candidate = val.strip()
                if not candidate or self._is_write_command_string(candidate):
                    continue
                if len(candidate) >= 20:
                    return candidate

        # 2) Code block markdown
        blocks = re.findall(r"```(?:[a-zA-Z0-9_+.-]+)?\s*\n(.*?)```", clean, re.DOTALL)
        if blocks:
            candidate = max((b.strip() for b in blocks if b and b.strip()), key=len, default="")
            if candidate:
                return candidate

        # 3) Euristica minimale per file testuali
        ext = Path(filename).suffix.lower()
        if ext == ".html":
            m = re.search(r"(<!DOCTYPE\s+html.*?</html>)", clean, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()
        if ext in {".js", ".ts", ".css", ".py"} and len(clean) >= 20:
            if not self._is_write_command_string(clean):
                return clean

        return None

    def _write_direct_step_content(self, p_path: Path, filename: str, content: str) -> bool:
        content = self._repair_probable_overescaped_content(filename, content)
        validation = self._validate_file_content(filename, content)
        if not validation['valid']:
            logger.warning(f"Contenuto diretto scartato per {filename}: {validation['reason']}")
            return False

        t_file = p_path / Path(filename).name
        t_file.parent.mkdir(parents=True, exist_ok=True)
        t_file.write_text(content, encoding='utf-8')
        logger.info(f"File creato da fallback contenuto diretto: {t_file.name} ({len(content)} bytes)")
        return True

    def _read_reference_html_content(self, p_path: Path, step_context: dict) -> str:
        planned_steps = step_context.get("steps", []) if isinstance(step_context, dict) else []
        html_names = [
            Path(s.get("filename", "")).name
            for s in planned_steps
            if str(s.get("filename", "")).lower().endswith(".html")
        ]
        for name in html_names:
            f = p_path / name
            if f.exists():
                return f.read_text(encoding="utf-8", errors="replace")
        for f in sorted(p_path.glob("*.html")):
            if f.is_file():
                return f.read_text(encoding="utf-8", errors="replace")
        return ""

    def _extract_html_contract(self, html_content: str) -> dict:
        ids = set(re.findall(r'id=["\']([^"\']+)["\']', html_content, re.IGNORECASE))
        class_attrs = re.findall(r'class=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        classes: set[str] = set()
        for attr in class_attrs:
            for token in re.split(r"\s+", attr.strip()):
                if token:
                    classes.add(token)

        button_ids = set(re.findall(r'<button[^>]*\bid=["\']([^"\']+)["\']', html_content, re.IGNORECASE))
        button_classes: set[str] = set()
        for match in re.finditer(r'<button[^>]*\bclass=["\']([^"\']+)["\']', html_content, re.IGNORECASE):
            for token in re.split(r"\s+", match.group(1).strip()):
                if token:
                    button_classes.add(token)

        button_text_by_id: dict[str, str] = {}
        button_types_by_id: dict[str, str] = {}
        button_classes_by_id: dict[str, set[str]] = {}
        for match in re.finditer(r"<button\b([^>]*)>(.*?)</button>", html_content, re.IGNORECASE | re.DOTALL):
            attrs = match.group(1) or ""
            body = match.group(2) or ""

            id_match = re.search(r'\bid=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            if not id_match:
                continue
            button_id = id_match.group(1)
            button_ids.add(button_id)

            class_match = re.search(r'\bclass=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            cls_tokens: set[str] = set()
            if class_match:
                for token in re.split(r"\s+", class_match.group(1).strip()):
                    if token:
                        cls_tokens.add(token)
                        button_classes.add(token)
                if cls_tokens:
                    button_classes_by_id[button_id] = cls_tokens

            type_match = re.search(r'\btype=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
            if type_match:
                button_types_by_id[button_id] = type_match.group(1).strip().lower()

            plain_text = re.sub(r"<[^>]+>", " ", body)
            plain_text = re.sub(r"\s+", " ", plain_text).strip().lower()
            if plain_text:
                button_text_by_id[button_id] = plain_text

        return {
            "ids": ids,
            "classes": classes,
            "button_ids": button_ids,
            "button_classes": button_classes,
            "button_text_by_id": button_text_by_id,
            "button_types_by_id": button_types_by_id,
            "button_classes_by_id": button_classes_by_id,
        }

    def _looks_like_action_control(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        action_patterns = (
            r"\breset\b", r"\brestart\b", r"\breload\b", r"\brefresh\b",
            r"\bsave\b", r"\bsubmit\b", r"\bsend\b", r"\bsearch\b",
            r"\bstart\b", r"\bstop\b", r"\bplay\b", r"\bretry\b",
            r"\bnew[\s_-]?game\b", r"\bcontinue\b", r"\bconfirm\b", r"\bcancel\b",
            r"\bopen\b", r"\bclose\b", r"\bdownload\b", r"\bupload\b",
            r"\bdelete\b", r"\bremove\b", r"\bcreate\b", r"\bupdate\b", r"\bapply\b",
            r"\bavvia\b", r"\bferma\b", r"\bricomincia\b", r"\bsalva\b", r"\binvia\b",
            r"\bcerca\b", r"\bannulla\b", r"\bconferma\b", r"\bapri\b", r"\bchiudi\b",
            r"\belimina\b", r"\brimuovi\b", r"\bcrea\b", r"\baggiorna\b", r"\besegui\b",
            r"\bscarica\b", r"\bcarica\b",
        )
        return any(re.search(pattern, normalized) for pattern in action_patterns)

    def _collect_action_button_ids(self, html_contract: dict) -> set[str]:
        button_ids: set[str] = set(html_contract.get("button_ids", set()))
        text_by_id: dict[str, str] = html_contract.get("button_text_by_id", {}) or {}
        types_by_id: dict[str, str] = html_contract.get("button_types_by_id", {}) or {}
        classes_by_id: dict[str, set[str]] = html_contract.get("button_classes_by_id", {}) or {}

        action_ids: set[str] = set()
        for button_id in button_ids:
            if self._looks_like_action_control(button_id):
                action_ids.add(button_id)
                continue

            button_type = (types_by_id.get(button_id, "") or "").lower()
            if button_type in {"submit", "reset"}:
                action_ids.add(button_id)
                continue

            class_tokens = classes_by_id.get(button_id, set()) or set()
            if any(self._looks_like_action_control(token) for token in class_tokens):
                action_ids.add(button_id)
                continue

            label = text_by_id.get(button_id, "")
            if self._looks_like_action_control(label):
                action_ids.add(button_id)

        return action_ids

    def _html_button_has_inline_handler(self, html_content: str, button_id: str) -> bool:
        return bool(
            re.search(
                rf"<button[^>]*\bid=[\"']{re.escape(button_id)}[\"'][^>]*\bon\w+\s*=",
                html_content,
                re.IGNORECASE,
            )
        )

    def _validate_css_against_html(self, css_content: str, html_content: str) -> tuple[bool, str]:
        html = self._extract_html_contract(html_content)
        html_ids = html["ids"]
        html_classes = html["classes"]
        button_ids = html["button_ids"]
        button_classes = html["button_classes"]

        if not html_ids and not html_classes:
            return True, "OK"

        dom_selector_hits = 0
        for el_id in html_ids:
            if f"#{el_id}" in css_content:
                dom_selector_hits += 1
        for cls in html_classes:
            if f".{cls}" in css_content:
                dom_selector_hits += 1

        if dom_selector_hits == 0:
            return False, "CSS non usa selector coerenti con id/class presenti in HTML"

        # Se in HTML esistono controlli d'azione, il CSS deve includere stile specifico
        # per almeno uno di essi o uno stile generico su `button`.
        has_generic_button_style = bool(re.search(r"(?<![A-Za-z0-9_-])button(?![A-Za-z0-9_-])", css_content))
        action_button_ids = self._collect_action_button_ids(html)
        action_button_classes: set[str] = set()
        classes_by_id = html.get("button_classes_by_id", {}) or {}
        for btn_id in action_button_ids:
            action_button_classes.update(classes_by_id.get(btn_id, set()) or set())

        button_specific_hits = 0
        for el_id in action_button_ids:
            if f"#{el_id}" in css_content:
                button_specific_hits += 1
        for cls in action_button_classes:
            if f".{cls}" in css_content:
                button_specific_hits += 1

        if action_button_ids and button_specific_hits == 0 and not has_generic_button_style:
            return False, "CSS non contiene stili applicabili ai controlli d'azione presenti in HTML"

        return True, "OK"

    def _extract_js_id_bindings(self, js_content: str) -> tuple[set[str], dict[str, set[str]]]:
        used_ids: set[str] = set()
        id_to_vars: dict[str, set[str]] = {}

        direct_ids = re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)", js_content)
        direct_ids += re.findall(r"querySelector\(\s*['\"]#([^'\"]+)['\"]\s*\)", js_content)
        used_ids.update(direct_ids)

        for var_name, element_id in re.findall(
            r"(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*document\.getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)",
            js_content,
        ):
            used_ids.add(element_id)
            id_to_vars.setdefault(element_id, set()).add(var_name)

        for var_name, element_id in re.findall(
            r"(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*document\.querySelector\(\s*['\"]#([^'\"]+)['\"]\s*\)",
            js_content,
        ):
            used_ids.add(element_id)
            id_to_vars.setdefault(element_id, set()).add(var_name)

        return used_ids, id_to_vars

    def _js_has_listener_for_id(self, js_content: str, element_id: str, id_to_vars: dict[str, set[str]]) -> bool:
        if re.search(
            rf"document\.getElementById\(\s*['\"]{re.escape(element_id)}['\"]\s*\)\s*\.addEventListener\(",
            js_content,
        ):
            return True
        if re.search(
            rf"document\.getElementById\(\s*['\"]{re.escape(element_id)}['\"]\s*\)\s*\.onclick\s*=",
            js_content,
        ):
            return True
        if re.search(
            rf"document\.querySelector\(\s*['\"]#{re.escape(element_id)}['\"]\s*\)\s*\.addEventListener\(",
            js_content,
        ):
            return True
        if re.search(
            rf"document\.querySelector\(\s*['\"]#{re.escape(element_id)}['\"]\s*\)\s*\.onclick\s*=",
            js_content,
        ):
            return True

        for var_name in id_to_vars.get(element_id, set()):
            if re.search(rf"\b{re.escape(var_name)}\b\s*(?:\?\.)?\.addEventListener\(", js_content):
                return True
            if re.search(rf"\b{re.escape(var_name)}\b\s*(?:\?\.)?\.onclick\s*=", js_content):
                return True
        return False

    def _validate_js_against_html(self, js_content: str, html_content: str) -> tuple[bool, str]:
        html = self._extract_html_contract(html_content)
        html_ids = html["ids"]
        html_classes = html["classes"]
        button_ids = html["button_ids"]

        used_ids, id_to_vars = self._extract_js_id_bindings(js_content)
        missing_ids = sorted(el_id for el_id in used_ids if el_id not in html_ids)
        if missing_ids:
            return False, f"JS usa id non presenti in HTML: {', '.join(missing_ids[:5])}"

        selectors = re.findall(r"(?:querySelectorAll|querySelector)\(\s*['\"]([^'\"]+)['\"]\s*\)", js_content)
        for sel in selectors:
            if re.fullmatch(r"\.[A-Za-z0-9_-]+", sel):
                class_name = sel[1:]
                if class_name not in html_classes:
                    return False, f"JS usa classe non presente in HTML: .{class_name}"
            if re.fullmatch(r"#[A-Za-z0-9_-]+", sel):
                element_id = sel[1:]
                if element_id not in html_ids:
                    return False, f"JS usa id non presente in HTML: #{element_id}"

        # Richiede listener solo per controlli d'azione riconoscibili (id/class/text/type).
        if button_ids:
            action_button_ids = self._collect_action_button_ids(html)
            for btn_id in sorted(action_button_ids):
                has_listener = self._js_has_listener_for_id(js_content, btn_id, id_to_vars)
                has_inline = self._html_button_has_inline_handler(html_content, btn_id)
                if not has_listener and not has_inline:
                    return False, f"JS non gestisce il controllo d'azione `{btn_id}` (listener mancante)"

        return True, "OK"

    def _validate_python_source(self, filename: str, content: str) -> tuple[bool, str]:
        try:
            compile(content, filename, "exec")
            return True, "OK"
        except SyntaxError as exc:
            return False, f"Python syntax error: {exc.msg} (line {exc.lineno})"
        except Exception as exc:
            return False, f"Python validation error: {exc}"

    def _validate_java_source_light(self, content: str) -> tuple[bool, str]:
        if not re.search(r"\bclass\s+[A-Za-z_][A-Za-z0-9_]*", content):
            return False, "Java: manca dichiarazione di classe"
        if content.count("{") != content.count("}"):
            return False, "Java: parentesi graffe sbilanciate"
        return True, "OK"

    def _validate_written_step_file(self, p_path: Path, step_context: dict, filename: str) -> tuple[bool, str]:
        """
        Validazione cross-file post-scrittura per evitare output formalmente valido ma non collegato.
        """
        target = p_path / Path(filename).name
        if not target.exists():
            return False, f"File non trovato dopo la scrittura: {filename}"

        content = target.read_text(encoding="utf-8", errors="replace")
        ext = Path(filename).suffix.lower()
        planned_steps = step_context.get("steps", []) if isinstance(step_context, dict) else []
        expected_css = [
            Path(s.get("filename", "")).name
            for s in planned_steps
            if str(s.get("filename", "")).lower().endswith(".css")
        ]
        expected_js = [
            Path(s.get("filename", "")).name
            for s in planned_steps
            if str(s.get("filename", "")).lower().endswith((".js", ".ts"))
        ]

        if ext == ".html":
            for css_name in expected_css:
                if not re.search(rf"<link[^>]*href=[\"']{re.escape(css_name)}[\"']", content, re.IGNORECASE):
                    return False, f"HTML non collega il file CSS previsto: {css_name}"
            for js_name in expected_js:
                if not re.search(rf"<script[^>]*src=[\"']{re.escape(js_name)}[\"']", content, re.IGNORECASE):
                    return False, f"HTML non collega il file JS previsto: {js_name}"
            return True, "OK"

        html_content = self._read_reference_html_content(p_path, step_context)

        if ext == ".css" and html_content:
            return self._validate_css_against_html(content, html_content)

        if ext in {".js", ".ts"} and html_content:
            return self._validate_js_against_html(content, html_content)

        if ext == ".py":
            return self._validate_python_source(filename, content)

        if ext == ".java":
            return self._validate_java_source_light(content)

        return True, "OK"

    def _execute_direct_workflow(self, user_message, project_path):
        """Workflow deterministico a step: plan -> parse steps -> execute step -> update STEP_CONTEXT."""
        try:
            logger.info("=== INIZIO STEP WORKFLOW DETERMINISTICO ===")
            logger.info(f"Modello workflow: {self.ollama.model}")
            logger.info(f"User message: {user_message[:200]}")
            logger.info(f"Project path: {project_path}")

            self.root.after(0, lambda: self._add_message("\n[STEP] FASE 1: PIANIFICAZIONE FUNZIONALE...", "info"))

            wf = self._workflow_settings()
            p_path = project_path or Path(".")
            p_path.mkdir(parents=True, exist_ok=True)

            mode = getattr(self, "mode", "new")
            existing_files = self._list_project_code_files(p_path) if mode == "fix" else []
            diagnostics = self._run_local_project_diagnostics(p_path, existing_files) if mode == "fix" else []

            if mode == "fix":
                self.root.after(0, lambda: self._add_message(f"[FIX] Path target: {p_path}", "info"))
                self.root.after(0, lambda: self._add_message(f"[FIX] File rilevati: {len(existing_files)}", "info"))
                if diagnostics:
                    for name, reason in diagnostics[:8]:
                        self.root.after(0, lambda n=name, r=reason: self._add_message(f"[DIAG] {n}: {r}", "warning"))
                else:
                    self.root.after(0, lambda: self._add_message("[DIAG] Nessuna anomalia locale evidente", "success"))

            memory = ProjectMemory(p_path)
            memory.clear()
            project_name = self._infer_project_name(user_message)
            memory.set_project_info(project_name, user_message[:400])

            plan_prompt = self._build_planning_prompt(
                user_message,
                mode=mode,
                existing_files=existing_files,
                diagnostics=diagnostics,
            )
            plan_system = (
                "You are a software architect. "
                "Reply with only one valid JSON object that follows the required schema. "
                "No markdown, no prose, no extra keys. "
                "Do not output <think> tags."
            )
            self.root.after(0, lambda: self._add_message("[STEP] Generazione piano JSON...", "info"))
            logger.info(f"=== PIANO PROMPT ===\n{plan_prompt[:2000]}")

            plan_data = None
            plan_error = None
            max_plan_retries = wf["plan_max_retries"]

            for attempt in range(max_plan_retries + 1):
                if self.stop_flag:
                    break

                plan_messages = [
                    {"role": "system", "content": plan_system},
                    {"role": "user", "content": plan_prompt},
                ]
                logger.info(
                    f"=== PLAN attempt {attempt + 1} === messages_count={len(plan_messages)} "
                    f"num_predict_override={wf['plan_num_predict']}"
                )

                response = ""
                original_predict = self.ollama.options.get("num_predict")
                self.ollama.options["num_predict"] = wf["plan_num_predict"]
                try:
                    for chunk in self.ollama.chat(plan_messages, stream=True):
                        if self.stop_flag:
                            break
                        response += chunk
                finally:
                    if original_predict is None:
                        self.ollama.options.pop("num_predict", None)
                    else:
                        self.ollama.options["num_predict"] = original_predict

                if self.stop_flag:
                    break

                clean_response = self._sanitize_llm_response(response)
                logger.info(f"=== PIANO RISPOSTA ({len(clean_response)} chars) ===\n{clean_response[:3000]}")

                if not clean_response:
                    plan_error = "Piano vuoto dal modello"
                elif len(clean_response) > wf["plan_max_response_chars"]:
                    plan_error = (
                        f"Risposta piano troppo lunga ({len(clean_response)} > {wf['plan_max_response_chars']})"
                    )
                else:
                    plan_obj = self._extract_first_json_object(clean_response)
                    ok_schema, schema_error, normalized = self._validate_plan_schema(plan_obj)
                    if ok_schema and normalized:
                        plan_data = normalized
                        plan_error = None
                        break
                    plan_error = schema_error or "Schema piano non valido"

                if attempt < max_plan_retries:
                    logger.warning(f"PLAN retry {attempt + 1}: {plan_error}")
                    self.root.after(0, lambda a=attempt + 1: self._add_message(f"[RETRY PLAN] {a}", "warning"))
                    plan_prompt += (
                        "\n\nATTENZIONE: OUTPUT NON VALIDO.\n"
                        f"Errore: {plan_error}\n"
                        "Riprova: SOLO JSON schema richiesto, senza testo extra."
                    )
                else:
                    logger.error(f"Piano fallito: {plan_error}")

            if self.stop_flag:
                return

            if not plan_data:
                self.root.after(0, lambda e=plan_error or "Piano non disponibile": self._add_message(f"[ERR] {e}", "error"))
                return

            app_summary = plan_data.get("app_summary", [])
            steps = plan_data.get("steps", [])

            if mode == "new":
                steps, removed_doc_steps = self._strip_doc_steps_for_new_mode(steps, user_message)
                if removed_doc_steps:
                    plan_data["steps"] = steps
                    removed_str = ", ".join(removed_doc_steps)
                    logger.info(f"Step documentazione rimossi in /new (non richiesti): {removed_str}")
                    self.root.after(0, lambda r=removed_str: self._add_message(f"[INFO] Step documentazione rimossi: {r}", "info"))

            if not steps:
                logger.error("Nessuno step valido nel piano JSON")
                self.root.after(0, lambda: self._add_message("[ERR] Nessuno step valido nel piano JSON", "error"))
                return

            claude_md = p_path / "claude.md"
            claude_md.write_text(self._render_claude_md(app_summary, steps), encoding="utf-8")
            plan_json_file = p_path / "PLAN_SCHEMA.json"
            plan_json_file.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.root.after(0, lambda: self._add_message(f"[OK] Piano salvato: {claude_md}", "success"))
            self.root.after(0, lambda: self._add_message(f"[INFO] Schema piano: {plan_json_file.name}", "info"))

            step_context = self._init_step_context(p_path, app_summary, steps)
            self.root.after(0, lambda: self._add_message(f"[INFO] STEP_CONTEXT.json creato in {p_path}", "info"))
            logger.info(f"Step parsati: {[s['filename'] for s in step_context['steps']]}")

            created_files: list[str] = []
            total_steps = len(step_context["steps"])
            self.root.after(0, lambda: self._add_message(f"\n[STEP] FASE 2: ESECUZIONE {total_steps} STEP", "info"))

            for step in step_context["steps"]:
                if self.stop_flag:
                    break

                step_num = step["num"]
                filename = step["filename"]
                self._set_step_status(p_path, step_context, step_num, "in_progress")

                key_refs = self._collect_key_references(memory)
                step_context["key_references_by_file"] = key_refs
                self._write_step_context(p_path, step_context)

                brief = self._build_step_brief(user_message, step_context, step, key_refs)
                file_rules = self._build_step_file_rules(filename)
                step_msg = self._build_step_user_prompt(step, total_steps, brief, file_rules)

                self.root.after(0, lambda n=step_num, fn=filename: self._add_message(f"\n[STEP] {n}/{total_steps}: {fn}", "warning"))

                success = False
                max_retries = wf["max_step_retries"]
                step_num_predict = self._step_num_predict_for_filename(wf, filename)

                for attempt in range(max_retries + 1):
                    if self.stop_flag:
                        break

                    exec_system = (
                        "You are a senior software engineer. "
                        "Reply ONLY with a valid JSON object like: "
                        "{\\\"cmd1\\\": \\\"Set-Content -Path 'file' -Value 'content'\\\"}. "
                        "No markdown, no explanations, no extra text. "
                        "Do not output <think> tags."
                    )
                    exec_messages = [
                        {"role": "system", "content": exec_system},
                        {"role": "user", "content": step_msg},
                    ]

                    prompt_preview = step_msg[:4000]
                    if len(step_msg) > 4000:
                        prompt_preview += "\n...[PROMPT TRONCATO IN LOG]..."
                    logger.info(
                        f"=== STEP {step_num} PROMPT attempt {attempt + 1} ===\n"
                        f"SYSTEM:\n{exec_system}\n"
                        f"USER:\n{prompt_preview}"
                    )
                    logger.info(
                        f"=== STEP {step_num} attempt {attempt + 1} === messages_count={len(exec_messages)} "
                        f"num_predict_override={step_num_predict}"
                    )

                    response = ""
                    original_predict = self.ollama.options.get("num_predict")
                    self.ollama.options["num_predict"] = step_num_predict
                    try:
                        for chunk in self.ollama.chat(exec_messages, stream=True):
                            if self.stop_flag:
                                break
                            response += chunk
                    finally:
                        if original_predict is None:
                            self.ollama.options.pop("num_predict", None)
                        else:
                            self.ollama.options["num_predict"] = original_predict

                    if self.stop_flag:
                        break

                    clean_response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL | re.IGNORECASE).strip()
                    logger.info(f"=== STEP {step_num} RISPOSTA ({len(clean_response)} chars) ===\n{clean_response[:2000]}")

                    if len(clean_response) > wf["step_max_response_chars"]:
                        logger.warning(
                            f"STEP {step_num}: risposta troppo lunga ({len(clean_response)} > {wf['step_max_response_chars']})"
                        )
                        parsed = None
                        parse_error = "Risposta troppo lunga"
                    else:
                        parsed = self.parser.parse(clean_response)
                        if (not parsed.is_valid or not parsed.commands) and "{" in clean_response:
                            parsed = self.parser.parse(clean_response[clean_response.find("{"):])
                        parse_error = parsed.error if parsed else "Parser error"

                    if parsed and parsed.is_valid and parsed.commands:
                        if not self._commands_target_expected_file(parsed.commands, filename):
                            only_non_command_values = all(
                                not self._is_write_command_string(cmd) for cmd in parsed.commands
                            )
                            if only_non_command_values:
                                direct_content = self._extract_direct_file_content_from_response(clean_response, filename)
                                if direct_content and self._write_direct_step_content(p_path, filename, direct_content):
                                    valid_step_file, step_file_reason = self._validate_written_step_file(p_path, step_context, filename)
                                    if not valid_step_file:
                                        parse_error = step_file_reason
                                        logger.warning(f"STEP {step_num}: {parse_error}")
                                        self.root.after(0, lambda r=step_file_reason: self._add_message(f"[ERR] {r}", "error"))
                                    else:
                                        self._update_memory_from_file(memory, filename, clean_response)
                                        if filename not in created_files:
                                            created_files.append(filename)
                                        self.root.after(0, lambda fn=filename: self._add_message(f"[OK] {fn} creato (fallback content)", "success"))
                                        success = True
                                else:
                                    parse_error = f"Contenuto diretto non valido per {filename}"
                                    logger.warning(f"STEP {step_num}: {parse_error}")
                            else:
                                parse_error = f"Comandi non allineati al file target {filename}"
                                logger.warning(f"STEP {step_num}: {parse_error}")
                        else:
                            for cmd in parsed.commands:
                                if self._is_command_likely_truncated(cmd):
                                    parse_error = "Comando troncato o stringa -Value non chiusa"
                                    logger.warning(f"STEP {step_num}: {parse_error}")
                                    break
                                ok = self._execute_command_with_fallback(cmd, p_path, filename)
                                if ok:
                                    valid_step_file, step_file_reason = self._validate_written_step_file(p_path, step_context, filename)
                                    if not valid_step_file:
                                        parse_error = step_file_reason
                                        logger.warning(f"STEP {step_num}: {parse_error}")
                                        self.root.after(0, lambda r=step_file_reason: self._add_message(f"[ERR] {r}", "error"))
                                        continue
                                    self._update_memory_from_file(memory, filename, clean_response)
                                    if filename not in created_files:
                                        created_files.append(filename)
                                    self.root.after(0, lambda fn=filename: self._add_message(f"[OK] {fn} creato", "success"))
                                    success = True
                                    break
                                self.root.after(0, lambda: self._add_message("[ERR] Errore esecuzione comando", "error"))

                    if success:
                        break

                    if attempt < max_retries:
                        logger.warning(f"STEP {step_num} retry {attempt + 1}: {parse_error}")
                        self.root.after(0, lambda a=attempt + 1: self._add_message(f"[RETRY] {a}", "warning"))
                        step_msg += self._build_step_retry_hint(filename, parse_error)
                    else:
                        logger.error(f"STEP {step_num} fallito: {parse_error}")

                if success:
                    self._set_step_status(p_path, step_context, step_num, "done")
                else:
                    self._set_step_status(p_path, step_context, step_num, "failed")
                    memory.add_decision(f"Step {step_num} fallito per {filename}")
                    self.root.after(0, lambda fn=filename: self._add_message(f"[FAIL] {fn} FALLITO", "error"))

            memory.save()
            step_context["key_references_by_file"] = self._collect_key_references(memory)
            remaining = [s for s in step_context["steps"] if s.get("status") == "pending"]
            step_context["current_step"] = remaining[0]["num"] if remaining else None
            self._write_step_context(p_path, step_context)

            failed = [s["filename"] for s in step_context["steps"] if s.get("status") != "done"]
            if not failed:
                logger.info(f"=== WORKFLOW COMPLETATO - File: {created_files} ===")
                self.root.after(0, lambda: self._add_message("\n[OK] PROGETTO COMPLETATO", "success"))
            else:
                logger.warning(f"Workflow incompleto, file non completati: {failed}")
                self.root.after(0, lambda f=failed: self._add_message(f"[WARN] Step incompleti: {', '.join(f)}", "warning"))

            self.mode = "default"

        except Exception as exc:
            logger.error(f"ERRORE WORKFLOW: {exc}")
            self.root.after(0, lambda e=str(exc): self._add_message(f"[ERR] ERRORE: {e}", "error"))

        finally:
            self.is_thinking = False
            self.stop_flag = False
            self.root.after(0, lambda: self.thinking_anim.stop())
            self.root.after(0, lambda: self._set_status("Connesso", "success"))
            self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    def _execute_agentic_workflow(self, user_message, project_path):
        """Instrada /new e /fix al workflow deterministico step-by-step."""
        return self._execute_direct_workflow(user_message, project_path)

    def _execute_command_with_fallback(self, cmd: str, p_path: Path, filename: str) -> bool:
        """Esegue comando con fallback Python nativo, parsing robusto e VALIDAZIONE."""
        try:
            import re
            cmd_str = cmd.strip()

            if self._is_command_likely_truncated(cmd_str):
                logger.error("Comando rifiutato: output troncato o stringa -Value non chiusa")
                return False
            
            if cmd_str.startswith("Set-Content") or cmd_str.startswith("Add-Content"):
                # Estrai Path
                p_match = re.search(r"-Path\s+'([^']*)'", cmd_str)
                if not p_match:
                    p_match = re.search(r"-Path\s+\"([^\"]*)\"", cmd_str)
                if not p_match:
                    logger.error(f" Nessun -Path trovato nel comando")
                    return False
                target_name = Path(p_match.group(1)).name
                expected_name = Path(filename).name
                if target_name.lower() != expected_name.lower():
                    logger.error(
                        f"Comando rifiutato: target '{target_name}' diverso da step file '{expected_name}'"
                    )
                    return False
                
                # Estrai Value con parsing ROBUSTO
                content = self._extract_value_from_command(cmd_str)
                if content is None:
                    logger.error(f" Impossibile estrarre -Value dal comando")
                    return False
                content = self._repair_probable_overescaped_content(filename, content)
                
                # === VALIDAZIONE CRITICA ===
                validation = self._validate_file_content(filename, content)
                if not validation['valid']:
                    logger.error(f" VALIDAZIONE FALLITA per {filename}: {validation['reason']}")
                    return False
                # =========================
                
                t_file = p_path / expected_name
                t_file.parent.mkdir(parents=True, exist_ok=True)
                is_append = cmd_str.startswith("Add-Content") or bool(
                    re.search(r"(^|\s)-Append(?:\s|$)", cmd_str, re.IGNORECASE)
                )
                mode = 'a' if is_append else 'w'
                with open(t_file, mode, encoding='utf-8') as f:
                    f.write(content)
                logger.info(f" File creato: {t_file.name} ({len(content)} bytes)")
                return True
            
            # Supporto heredoc: cat << 'EOF' > file o cat << 'EOF' > file
            heredoc_match = re.search(
                r"cat\s+<<\s*'?EOF'?\s*>\s*(.+?)(?:\s*\n|\s*\\n)",
                cmd_str
            )
            if heredoc_match:
                heredoc_path = heredoc_match.group(1).strip().strip("'\"")
                target_name = Path(heredoc_path).name
                expected_name = Path(filename).name
                if target_name.lower() != expected_name.lower():
                    logger.error(
                        f"Heredoc rifiutato: target '{target_name}' diverso da step file '{expected_name}'"
                    )
                    return False
                # Estrai contenuto tra la prima riga e EOF finale
                # Il contenuto  tutto dopo il primo newline fino a EOF
                first_nl = cmd_str.find('\n', heredoc_match.end())
                if first_nl == -1:
                    # Prova con \\n letterale
                    parts = cmd_str.split('\\n', 1)
                    if len(parts) > 1:
                        content = parts[1]
                    else:
                        content = cmd_str[heredoc_match.end():]
                else:
                    content = cmd_str[first_nl + 1:]

                # Rimuovi EOF finale
                content = re.sub(r'\n\s*EOF\s*$', '', content)
                content = re.sub(r'\\n\s*EOF\s*$', '', content)
                # Converti \\n letterali in newline reali
                content = content.replace('\\n', '\n')
                content = content.replace('\\t', '\t')
                content = self._repair_probable_overescaped_content(filename, content)

                if content.strip():
                    validation = self._validate_file_content(filename, content)
                    if not validation['valid']:
                        logger.error(f" VALIDAZIONE FALLITA per {filename}: {validation['reason']}")
                        return False

                    t_file = p_path / expected_name
                    t_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(t_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f" File creato (heredoc): {t_file.name} ({len(content)} bytes)")
                    return True

            # Fallback a shell
            ok, out = self.file_ops.execute_command(cmd)
            return ok
        except Exception as e:
            logger.error(f"Errore esecuzione: {e}")
            return False
    
    def _extract_value_from_command(self, cmd_str: str) -> str | None:
        """
        Estrae il contenuto da -Value con parsing robusto.
        Gestisce stringhe quote-based e here-string PowerShell.
        """
        v_match = re.search(r"-Value\b", cmd_str)
        if not v_match:
            return None

        value_start_pos = v_match.end()
        while value_start_pos < len(cmd_str) and cmd_str[value_start_pos] in " \t":
            value_start_pos += 1

        if value_start_pos >= len(cmd_str):
            return None

        # Supporto here-string PowerShell: -Value @' ... '@ oppure -Value @" ... "@
        if cmd_str.startswith("@'", value_start_pos) or cmd_str.startswith('@"', value_start_pos):
            opener = cmd_str[value_start_pos:value_start_pos + 2]
            closer = "'@" if opener == "@'" else '"@'
            content_start = value_start_pos + 2
            if cmd_str.startswith("\r\n", content_start):
                content_start += 2
            elif content_start < len(cmd_str) and cmd_str[content_start] == "\n":
                content_start += 1

            end_pos = cmd_str.find(closer, content_start)
            if end_pos >= 0:
                return self._decode_command_value(cmd_str[content_start:end_pos], None)

            # Fallback tollerante per output qwen2.5: "-Value @'...'" (manca terminatore "'@")
            tail = cmd_str[content_start:].strip()
            if tail.endswith("'"):
                candidate = tail[:-1]
                if candidate.strip():
                    return self._decode_command_value(candidate, None)
            if tail.endswith('"'):
                candidate = tail[:-1]
                if candidate.strip():
                    return self._decode_command_value(candidate, None)
            return None

        quote_char = cmd_str[value_start_pos]
        if quote_char not in ("'", '"'):
            return None

        content_chars: list[str] = []
        pos = value_start_pos + 1

        while pos < len(cmd_str):
            char = cmd_str[pos]

            if char == quote_char:
                if quote_char == "'" and pos + 1 < len(cmd_str) and cmd_str[pos + 1] == "'":
                    content_chars.append("'")
                    pos += 2
                    continue
                if quote_char == '"' and content_chars and content_chars[-1] == "`":
                    content_chars[-1] = '"'
                    pos += 1
                    continue

                content = self._decode_command_value("".join(content_chars), quote_char)
                remainder = cmd_str[pos + 1:].strip()
                if quote_char == "'" and remainder and not remainder.startswith("-"):
                    tail = cmd_str[value_start_pos + 1:]
                    last_quote_rel = tail.rfind("'")
                    if last_quote_rel > 0:
                        return self._decode_command_value(tail[:last_quote_rel], quote_char)
                return content

            if char == "\\" and pos + 1 < len(cmd_str):
                next_char = cmd_str[pos + 1]
                if next_char == "n":
                    content_chars.append("\n")
                    pos += 2
                    continue
                if next_char == "t":
                    content_chars.append("\t")
                    pos += 2
                    continue
                if next_char == "\\":
                    content_chars.append("\\")
                    pos += 2
                    continue
                if next_char == quote_char:
                    content_chars.append(quote_char)
                    pos += 2
                    continue

            content_chars.append(char)
            pos += 1

        tail = cmd_str[value_start_pos + 1:]
        last_quote_rel = tail.rfind(quote_char)
        if last_quote_rel > 0:
            return self._decode_command_value(tail[:last_quote_rel], quote_char)
        return None

    def _decode_command_value(self, raw_value: str, quote_char: str | None) -> str:
        """Decodifica escape comuni mantenendo robustezza verso output LLM non perfetti."""
        value = raw_value
        if quote_char == "'":
            value = value.replace("''", "'")
        value = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
        value = value.replace('\\"', '"').replace("\\'", "'")
        return value

    def _repair_probable_overescaped_content(self, filename: str, content: str) -> str:
        """
        Ripara over-escaping tipico LLM (es. `\\[` e `\\]` in codice) quando il pattern e' sistematico.
        Evita modifiche aggressive: de-escape solo se non esistono parentesi quadre non escapeate.
        """
        ext = Path(filename).suffix.lower()
        if ext not in {".js", ".ts", ".css", ".html", ".py", ".java", ".json", ".xml", ".sql", ".md", ".txt"}:
            return content

        repaired = content
        escaped_open = repaired.count("\\[")
        escaped_close = repaired.count("\\]")
        if escaped_open >= 3 and escaped_close >= 3:
            unescaped_open = len(re.findall(r"(?<!\\)\[", repaired))
            unescaped_close = len(re.findall(r"(?<!\\)\]", repaired))
            if unescaped_open == 0 and unescaped_close == 0:
                repaired = repaired.replace("\\[", "[").replace("\\]", "]")
                logger.warning(
                    f"Riparazione auto over-escape applicata su {filename}: "
                    f"de-escape [] ({escaped_open}/{escaped_close})"
                )

        return repaired

    def _is_command_likely_truncated(self, cmd: str) -> bool:
        """Rileva comandi probabilmente troncati prima della chiusura del contenuto."""
        cmd_str = (cmd or "").strip()
        if not cmd_str:
            return True
        if cmd_str.endswith("\\") or cmd_str.endswith("`"):
            return True

        here_single = cmd_str.find("-Value @'")
        if here_single >= 0 and cmd_str.find("'@", here_single + 8) == -1:
            recovered = self._extract_value_from_command(cmd_str)
            if not recovered or len(recovered.strip()) < 5:
                return True

        here_double = cmd_str.find('-Value @"')
        if here_double >= 0 and cmd_str.find('"@', here_double + 8) == -1:
            recovered = self._extract_value_from_command(cmd_str)
            if not recovered or len(recovered.strip()) < 5:
                return True

        if re.search(r"-Value\s+'", cmd_str):
            if not re.search(r"-Value\s+'(?:.|\n)*'(?:\s+-[A-Za-z][\w-]*(?:\s+[^-].*)?)?\s*$", cmd_str):
                return True

        if re.search(r'-Value\s+"', cmd_str):
            if not re.search(r'-Value\s+"(?:.|\n)*"(?:\s+-[A-Za-z][\w-]*(?:\s+[^-].*)?)?\s*$', cmd_str):
                return True

        return False
    
    def _validate_file_content(self, filename: str, content: str) -> dict:
        """Valida che il contenuto del file sia plausibile e non un placeholder."""
        stripped = content.strip()

        if len(stripped) < 20:
            return {'valid': False, 'reason': f'Contenuto troppo corto ({len(stripped)} chars)'}

        if stripped in ['...', 'TODO', 'fixme']:
            return {'valid': False, 'reason': 'Contenuto placeholder'}

        if '...' in stripped and len(stripped) < 100:
            return {'valid': False, 'reason': 'Contiene placeholder "..."'}

        ext = filename.lower().split('.')[-1] if '.' in filename else ''

        if ext == 'html':
            if '<html' not in stripped.lower() and '<!doctype' not in stripped.lower():
                return {'valid': False, 'reason': 'HTML: manca tag <html> o <!DOCTYPE>'}

        elif ext == 'css':
            if '{' not in content or '}' not in content:
                return {'valid': False, 'reason': 'CSS: mancano parentesi graffe'}

        elif ext in {'js', 'ts'}:
            if stripped.startswith('.'):
                return {'valid': False, 'reason': f'{ext.upper()}: inizia con "." (errore parsing)'}
            if stripped.lstrip().startswith('<!--'):
                return {'valid': False, 'reason': f'{ext.upper()}: contiene commento HTML in testa'}
            if 'function' not in stripped.lower() and '=>' not in stripped:
                return {'valid': False, 'reason': f'{ext.upper()}: manca almeno una funzione'}

        return {'valid': True, 'reason': 'OK'}

    def _update_memory_from_file(self, memory: ProjectMemory, filename: str, response: str) -> None:
        """Aggiorna memoria progetto con sole chiavi estratte (no snippet completi)."""
        content = ""
        clean = self._sanitize_llm_response(response)
        parsed = self.parser.parse(clean)
        if parsed and parsed.is_valid and parsed.commands:
            for cmd in parsed.commands:
                cmd_str = (cmd or "").strip()
                if cmd_str.startswith("Set-Content") or cmd_str.startswith("Add-Content"):
                    candidate = self._extract_value_from_command(cmd_str)
                    if candidate:
                        content = candidate
                        break

        if not content:
            json_match = re.search(r'\{.*\}', clean, re.DOTALL)
            if json_match:
                value_match = re.search(r"-Value\s+'(.+)'", json_match.group(0), re.DOTALL)
                if value_match:
                    content = value_match.group(1).replace("''", "'").replace('\\n', '\n')

        if not content:
            content = clean

        ext = Path(filename).suffix.lower()
        purpose = {
            '.html': 'Struttura HTML',
            '.css': 'Stili CSS',
            '.js': 'Logica JavaScript',
            '.ts': 'Logica TypeScript',
            '.py': 'Logica Python',
        }.get(ext, f'File {ext or "sconosciuto"}')

        elements: dict = {}

        if ext == '.html':
            ids = re.findall(r"id=[\"']([^\"']+)[\"']", content)
            class_attrs = re.findall(r"class=[\"']([^\"']+)[\"']", content)
            classes = []
            for attr in class_attrs:
                classes.extend([tok for tok in re.split(r"\s+", attr.strip()) if tok])
            button_ids = re.findall(r'<button[^>]*\bid=["\']([^"\']+)["\']', content, re.IGNORECASE)
            has_css_link = bool(re.search(r"<link[^>]*href=[\"'][^\"']+\.css[\"']", content, re.IGNORECASE))
            has_js_link = bool(re.search(r"<script[^>]*src=[\"'][^\"']+\.(?:js|ts)[\"']", content, re.IGNORECASE))
            has_inline_style = bool(re.search(r'<style[^>]*>.*?</style>', content, re.DOTALL | re.IGNORECASE))
            has_inline_script = bool(re.search(r'<script(?![^>]*src=)[^>]*>.*?</script>', content, re.DOTALL | re.IGNORECASE))
            elements = {
                'ids': ids,
                'classes': classes,
                'button_ids': button_ids,
                'has_css_link': [str(has_css_link)],
                'has_js_link': [str(has_js_link)],
                'has_inline_style': [str(has_inline_style)],
                'has_inline_script': [str(has_inline_script)],
            }
            if has_inline_style or has_inline_script:
                memory.add_decision(f'ATTENZIONE: {filename} contiene codice inline')

        elif ext == '.css':
            selectors = re.findall(r'([.#][a-zA-Z0-9_-]+)\s*\{', content)
            elements = {
                'selectors': selectors,
            }

        elif ext in {'.js', '.ts'}:
            functions = re.findall(r'function\s+([a-zA-Z0-9_]+)', content)
            functions += re.findall(r'([a-zA-Z0-9_]+)\s*=\s*\([^)]*\)\s*=>', content)
            variables = re.findall(r'(?:let|const|var)\s+([a-zA-Z0-9_]+)', content)
            used_ids = re.findall(r"getElementById\(\s*[\"']([^\"']+)[\"']\s*\)", content)
            used_ids += re.findall(r"querySelector\(\s*[\"']#([^\"']+)[\"']\s*\)", content)
            used_classes = re.findall(r"(?:querySelectorAll|querySelector)\(\s*[\"']([^\"']+)[\"']\s*\)", content)
            elements = {
                'functions': functions,
                'variables': variables,
                'used_ids': used_ids,
                'used_classes': used_classes,
            }

        elif ext == '.py':
            functions = re.findall(r'def\s+([a-zA-Z0-9_]+)\s*\(', content)
            classes = re.findall(r'class\s+([a-zA-Z0-9_]+)\s*(?:\(|:)', content)
            variables = re.findall(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*', content, re.MULTILINE)
            elements = {
                'functions': functions,
                'classes': classes,
                'variables': variables[:20],
            }

        else:
            symbols = re.findall(r'(?:function|def|class)\s+([a-zA-Z0-9_]+)', content)
            if symbols:
                elements = {'functions': symbols}

        memory.register_file(filename, purpose, elements)

    def _clear_chat(self):
        """Pulisce la chat e crea nuova sessione."""
        if messagebox.askyesno("Conferma", "Pulire la chat e iniziare nuova sessione?\n\nPerderai il contesto corrente."):
            # Stop eventuale inferenza
            if self.is_thinking:
                self._stop_inference()

            # Pulisci chat
            self.chat_display.config(state=tk.NORMAL)
            self.chat_display.delete("1.0", tk.END)
            self.chat_display.config(state=tk.DISABLED)

            # Nuova sessione
            self._new_session()

            # Mostra di nuovo il banner con suggerimenti
            self._show_welcome_banner()
        self._discover_specialized_models()

    def _new_session(self):
        """Crea una nuova sessione."""
        self.session = self.session_manager.create_session()
        self.session_label.config(text=f"Sessione: {self.session.id[:8]}")
        self._add_message(" Nuova sessione iniziata.", "info")

    def _refresh_models(self):
        """Aggiorna la lista dei modelli."""
        if self.ollama and self.connected:
            self._add_message(" Aggiornamento modelli...", "info")
            all_models = self.ollama.list_models()
            # Mostra TUTTI i modelli, non solo shellbot
            self.models = all_models
            shell_models = [m for m in all_models if "shellbot" in m.lower()]
            
            if not shell_models and all_models:
                self._add_message(f" Nessun modello shellBot trovato. {len(all_models)} modelli disponibili:", "warning")
            elif shell_models:
                self._add_message(f" {len(shell_models)} modelli shellBot su {len(all_models)} totali:", "success")
            
            self.models_listbox.delete(0, tk.END)
            for i, m in enumerate(all_models, 1):
                is_shell = "shellbot" in m.lower()
                is_active = m == self.ollama.model
                if is_active:
                    prefix = " "
                elif is_shell:
                    prefix = f" {i}. "
                else:
                    prefix = f"   {i}. "
                self.models_listbox.insert(tk.END, f"{prefix}{m}")
                self._add_message(f"  {prefix}{m}", "model_list")
            
            if not all_models:
                self._add_message(" Nessun modello disponibile", "warning")

    # Comandi rapidi
    def _cmd_fix(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/fix")
        self._send_message()

    def _cmd_new(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/new")
        self._send_message()

    def _cmd_reverse(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/reverse")
        tag = self.model_docs or (self.models[0] if self.models else None)
        if tag and self.ollama and self.ollama.model != tag:
            self.ollama.model = tag
            self._add_message(f" Modello: {tag} (DOCS/REVERSE)", "info")
        elif not tag:
            self._add_message(" Nessun modello shellbot DOCS trovato", "warning")
        self._send_message()

    def _cmd_help(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/help")
        self._send_message()

    def _cmd_model(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/model ")
        self.input_field.focus()

    def _cmd_context(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/context")
        self._send_message()

    def _cmd_safe(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/safe")
        self._send_message()

    def _cmd_auto(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/auto")
        self._send_message()

    def _cmd_test(self):
        self.input_field.delete("1.0", tk.END)
        self.input_field.insert("1.0", "/test")
        self._send_message()

    def _cmd_clear(self):
        self._clear_chat()

    def _cmd_exit(self):
        if messagebox.askyesno("Esci", "Uscire dall'applicazione?"):
            self.root.quit()

    def _change_directory(self):
        """Cambia directory di lavoro."""
        directory = filedialog.askdirectory()
        if directory:
            self.file_ops = FileOperations(directory)
            self.path_label.config(text=f"Path: {directory}")
            self._add_message(f" Directory: {directory}", "info")

    def _show_about(self):
        """Mostra informazioni."""
        messagebox.showinfo(
            "Informazioni",
            " Ollama File System Bridge\n\n"
            "Interfaccia grafica per interagire con Ollama LLM\n"
            "e gestire file system locale.\n\n"
            "Modalit:\n"
            "  /fix   - Fix codice esistente\n"
            "  /new   - Crea nuovo progetto\n"
            "  /reverse - Genera documentazione\n\n"
            " 2026 - MIT License"
        )


def main():
    """Avvia l'applicazione GUI."""
    logger.info("=== FUNZIONE MAIN CHIAMATA ===")
    root = tk.Tk()
    logger.info("Tk root creato")

    # Icona (se disponibile)
    try:
        root.iconbitmap("@icon.xbm")
    except:
        pass

    logger.info("Avvio OllamaBridgeGUI...")
    app = OllamaBridgeGUI(root)
    logger.info("GUI inizializzata, avvio mainloop...")
    root.mainloop()


if __name__ == "__main__":
    main()


