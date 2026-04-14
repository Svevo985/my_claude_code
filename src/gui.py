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
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
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
            text="",
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
        self.root.title("🦙 Ollama File System Bridge")
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

    # ── Utils modelli shellbot ──────────────────────────────────────────
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
                self._add_message(f"⚠️ Conversione {target_tag} fallita: {out[:120]}", "warning")

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        return {
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "llama3.2",
                "timeout": 1800
            }
        }

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
            text="╔═══════════════════════════════════════════════════════════╗",
            bg=self.colors["accent"], fg="white", font=("Consolas", 9)
        ).pack()

        title_text = tk.Frame(banner, bg=self.colors["bg_dark"])
        title_text.pack(fill=tk.X, padx=10)

        tk.Label(
            title_text,
            text="║   🦙 OLLAMA FILE SYSTEM BRIDGE",
            bg=self.colors["bg_dark"], fg="white", font=("Consolas", 14, "bold")
        ).pack(anchor=tk.W)

        tk.Label(
            title_text,
            text="║   Interfaccia Grafica per LLM + File System",
            bg=self.colors["bg_dark"], fg=self.colors["gray"], font=("Consolas", 9)
        ).pack(anchor=tk.W)

        tk.Label(
            title_frame,
            text="╚═══════════════════════════════════════════════════════════╝",
            bg=self.colors["accent"], fg="white", font=("Consolas", 9)
        ).pack()

        return banner

    def _create_status_bar(self, parent):
        """Crea la barra di stato."""
        status = tk.Frame(parent, bg=self.colors["bg_light"], height=30)
        status.pack(fill=tk.X, side=tk.BOTTOM, padx=2, pady=2)

        # Stato connessione
        self.status_label = tk.Label(
            status, text="● Disconnesso",
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
            inner_frame, text="⚡ COMANDI DISPONIBILI",
            bg=self.colors["bg_light"], fg=self.colors["cyan"],
            font=("Consolas", 11, "bold"), pady=10
        ).pack(fill=tk.X)

        # Separator
        ttk.Separator(inner_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)

        # Modalità di lavoro
        tk.Label(
            inner_frame, text="📋 MODALITÀ DI LAVORO",
            bg=self.colors["bg_light"], fg=self.colors["warning"],
            font=("Consolas", 10, "bold"), pady=5
        ).pack(anchor=tk.W, padx=10)

        commands = [
            ("🔧 /fix", "Fixa codice esistente", self._cmd_fix, "Legge file, non crea doc"),
            ("🆕 /new", "Nuovo progetto", self._cmd_new, "Crea da zero con claude.md"),
            ("📖 /reverse", "Documentazione", self._cmd_reverse, "Genera DOCUMENTAZIONE.md"),
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
            inner_frame, text="⚙️ GESTIONE",
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
            inner_frame, text="🤖 MODELLI DISPONIBILI",
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
            inner_frame, text="⟳ Aggiorna lista modelli", command=self._refresh_models,
            bg=self.colors["accent"], fg="white",
            activebackground=self.colors["accent_light"],
            font=("Consolas", 9), relief=tk.FLAT,
            cursor="hand2", pady=5
        ).pack(fill=tk.X, padx=10, pady=5)

        # Info box
        info_box = tk.Label(
            inner_frame,
            text="💡 Suggerimento:\nUsa /fix per modificare\ncodice esistente.\nUsa /new per creare\nnuovi progetti.",
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
            center_frame, text=" 💬 Chat ",
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
            input_frame, text="»",
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
            btn_frame, text="⏹️ STOP", command=self._stop_inference,
            bg=self.colors["error"], fg="white",
            activebackground="#ff6b6b",
            font=("Consolas", 10, "bold"), relief=tk.FLAT,
            cursor="hand2", padx=15, pady=8,
            state=tk.DISABLED
        )
        self.stop_btn.pack(fill=tk.X, pady=(0, 5))

        self.send_btn = tk.Button(
            btn_frame, text="📤 Invia", command=self._send_message,
            bg=self.colors["success"], fg="black",
            activebackground="#5fd9c0",
            font=("Consolas", 10, "bold"), relief=tk.FLAT,
            cursor="hand2", padx=15, pady=8
        )
        self.send_btn.pack(fill=tk.X, pady=(0, 5))

        self.clear_btn = tk.Button(
            btn_frame, text="🗑️ Pulisci", command=self._clear_chat,
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
        # Priorità 1: modello con suffisso esatto legato a shellbot
        for m in self.models:
            ml = m.lower()
            if f"shellbot-{suffix}" in ml or f"-shellbot-{suffix}" in ml:
                return m
        # Priorità 2: modello che contiene sia 'shellbot' che il suffisso
        for m in self.models:
            ml = m.lower()
            if f"{suffix}" in ml and "shellbot" in ml:
                return m
        # Priorità 3: fallback su qualsiasi modello che contiene il suffisso (es. gemma4NewCreate)
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
            self._add_message(f"🎯 Modello CREATE/FIX: {self.model_create}", "info")
        if self.model_docs:
            self._add_message(f"🎯 Modello DOCS/REVERSE: {self.model_docs}", "info")

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
                }

                self.ollama = OllamaClient(base_url, model, timeout, options=ollama_options)

                if not self.ollama.is_available():
                    self.root.after(0, self._add_message, "⚠️ Ollama non disponibile, tentativo di avvio automatico...", "warning")
                    success, msg = self.ollama.ensure_available()
                    if not success:
                        self.root.after(0, self._on_connection_failed, f"Ollama non avviabile: {msg}")
                        return
                    self.root.after(0, self._add_message, f"✅ Ollama avviato: {msg}", "success")

                if self.ollama.is_available():
                    # Autoconversione in varianti shellBot prima di filtrare
                    force_rebuild = self.config.get("ollama", {}).get("force_rebuild_shellbot", False)
                    # self._auto_convert_models(force=force_rebuild) # ❌ Disabilitato automatismo su richiesta utente

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
        self._set_status("● Connesso", "success")
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
                self._add_message(f"📦 {len(shell_models)} modelli shellBot su {len(self.models)} totali:", "success")
            else:
                self._add_message(f"📦 {len(self.models)} modelli disponibili (nessuno shellBot):", "warning")
            
            for i, m in enumerate(self.models, 1):
                is_shell = "shellbot" in m.lower()
                is_active = m == self.ollama.model
                if is_active:
                    prefix = "► "
                elif is_shell:
                    prefix = f"🤖 {i}. "
                else:
                    prefix = f"   {i}. "
                self.models_listbox.insert(tk.END, f"{prefix}{m}")
                self._add_message(f"  {prefix}{m}", "model_list")
        else:
            self._add_message("⚠️ Nessun modello disponibile", "warning")

        self.input_field.focus()

    def _show_welcome_banner(self):
        """Mostra banner di benvenuto con info complete."""
        self._add_message("╔═══════════════════════════════════════════════════════════╗", "banner")
        self._add_message("║   Benvenuto in Ollama File System Bridge!                 ║", "banner")
        self._add_message("╚═══════════════════════════════════════════════════════════╝", "banner")
        self._add_message("", "info")
        os_name = self.env_info.get("system", "?")
        shell_desc = self.env_info.get("description", "?")
        self._add_message(f"OS: {os_name} | Shell: {shell_desc}", "info")
        self._add_message("", "info")
        self._add_message(f"🤖 Modello attivo: {self.ollama.model}", "success")
        self._add_message("", "info")
        self._add_message("💡 MODALITÀ DISPONIBILI:", "system")
        self._add_message("   🔧 /fix   - Fixa codice esistente (legge file, non crea doc)", "info")
        self._add_message("   🆕 /new   - Crea nuovo progetto da zero (con claude.md)", "info")
        self._add_message("   📖 /reverse - Genera documentazione (DOCUMENTAZIONE.md)", "info")
        self._add_message("", "info")
        self._add_message("⚙️ COMANDI UTILI:", "system")
        self._add_message("   /help  - Mostra tutti i comandi", "info")
        self._add_message("   /model <nome> - Cambia modello", "info")
        self._add_message("   /context - Mostra claude.md corrente", "info")
        self._add_message("   /safe, /auto, /test - Toggle impostazioni", "info")
        self._add_message("", "info")
        self._add_message("⏹️ Premi STOP per interrompere l'inferenza in corso", "warning")
        self._add_message("", "info")

    def _on_connection_failed(self, error):
        """Callback per connessione fallita."""
        self._set_status("● Disconnesso", "error")
        self.model_label.config(text="Modello: --")
        self._add_message(f"❌ Errore connessione: {error}", "error")
        self._add_message("💡 Assicurati che 'ollama serve' sia in esecuzione.", "warning")
        self._add_message("   Poi clicca '⟳ Aggiorna lista modelli'", "info")

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
            prefix = "» TU"
            tag = "user"
        elif msg_type == "ai":
            prefix = "🤖 AI"
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
            self._set_status("● Interrotto", "warning")
            self._add_message("⏹️ Inferenza interrotta dall'utente", "warning")

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
            messagebox.showwarning("Attenzione", "Ollama non è connesso!\nControlla che 'ollama serve' sia attivo.")
            return

        # ✅ CONTROLLA SE È UN COMANDO LOCALE (inizia con /)
        if message.startswith('/'):
            self._execute_local_command(message)
            return

        # ✅ Auto-detect reverse engineering da richiesta naturale con path
        auto_path = self._extract_path_from_text(message)
        if auto_path and (self._looks_like_reverse_intent(message) or self._is_just_path(message, auto_path)):
            self._add_message(message, "user")
            self.input_field.delete("1.0", tk.END)
            self.stop_flag = False
            self._add_message(f"📖 Reverse Engineering di: {auto_path}", "info")
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
                self._add_message(f"🤖 Modello corrente: {self.ollama.model}", "info")
                self._add_message("💡 Usa: /model <nome_modello>", "info")
                if self.models:
                    self._add_message("📋 Modelli disponibili:", "info")
                    for i, m in enumerate(self.models, 1):
                        cur = "► " if m == self.ollama.model else f"{i}. "
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
            # NON cambiare modello se l'utente ha scelto un modello "full coder" come qwen3.5
            current_model_lower = (self.ollama.model or "").lower()
            is_full_coder = any(x in current_model_lower for x in ['qwen', 'coder', 'sushi'])
            
            if not is_full_coder:
                tag = self.model_create or (self.models[0] if self.models else None)
                if tag and self.ollama and self.ollama.model != tag:
                    self.ollama.model = tag
                    self._add_message(f"🔄 Modello: {tag} (CREATE/FIX)", "info")
                elif not tag:
                    self._add_message("⚠️ Nessun modello shellbot CREATE trovato", "warning")
            else:
                self._add_message(f"✅ Uso {self.ollama.model} (modelllo completo - pianifico + eseguo)", "info")
            
            self._add_message("🔧 Modalità FIX attivata", "success")
            self._add_message("  • Leggerà file esistenti prima di agire", "info")
            self._add_message("  • Non creerà README.md (usa claude.md)", "info")
            self._add_message("  • Aggiornerà claude.md con i fix effettuati", "info")
            self._add_message("💡 Ora scrivi la richiesta di fix (es: 'fixa il gioco che non parte')", "system")

        elif command == '/new':
            self.mode = 'new'
            # NON cambiare modello se l'utente ha scelto un modello "full coder" come qwen3.5
            current_model_lower = (self.ollama.model or "").lower()
            is_full_coder = any(x in current_model_lower for x in ['qwen', 'coder', 'sushi'])
            
            if not is_full_coder:
                tag = self.model_create or (self.models[0] if self.models else None)
                if tag and self.ollama and self.ollama.model != tag:
                    self.ollama.model = tag
                    self._add_message(f"🔄 Modello: {tag} (CREATE/FIX)", "info")
                elif not tag:
                    self._add_message("⚠️ Nessun modello shellbot CREATE trovato", "warning")
            else:
                self._add_message(f"✅ Uso {self.ollama.model} (modelllo completo - pianifico + eseguo)", "info")
            
            self._add_message("🆕 Modalità NEW PROJECT attivata", "success")
            self._add_message("  • Può creare claude.md per tracciamento", "info")
            self._add_message("  • Struttura completa del progetto", "info")
            self._add_message("💡 Ora scrivi cosa creare (es: 'crea un gioco del tris in /path')", "system")

        elif command == '/reverse':
            if args:
                target_path = Path(self._strip_surrounding_quotes(args.strip()))
                if not target_path.exists():
                    self._add_message(f"❌ Path non trovato: {target_path}", "error")
                    return
                self._add_message(f"📖 Reverse Engineering di: {target_path}", "info")
                self._reverse_engineer_gui(target_path)
            else:
                self._add_message("📖 Reverse Engineering", "info")
                self._add_message("💡 Usa: /reverse /path/del/progetto", "system")

        elif command == '/session' or command == '/sessions':
            self._add_message(f"📋 Sessione corrente: {self.session.id if self.session else 'Nessuna'}", "info")

        else:
            self._add_message(f"❌ Comando sconosciuto: {command}", "error")
            self._add_message("💡 Usa /help per vedere tutti i comandi", "info")

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
        self._add_message("╔═══════════════════════════════════════════════════════════╗", "banner")
        self._add_message("║   COMANDI DISPONIBILI                                     ║", "banner")
        self._add_message("╚═══════════════════════════════════════════════════════════╝", "banner")
        self._add_message("", "info")
        self._add_message("📋 MODALITÀ DI LAVORO:", "system")
        self._add_message("  🔧 /fix         - Fixa codice esistente", "info")
        self._add_message("  🆕 /new         - Crea nuovo progetto da zero", "info")
        self._add_message("  📖 /reverse     - Genera documentazione", "info")
        self._add_message("", "info")
        self._add_message("⚙️ GESTIONE:", "system")
        self._add_message("  /help          - Mostra questo aiuto", "info")
        self._add_message("  /model <nome>  - Cambia modello LLM", "info")
        self._add_message("  /context       - Mostra claude.md corrente", "info")
        self._add_message("  /safe          - Toggle safety (ON/OFF)", "info")
        self._add_message("  /auto          - Auto-continue (ON/OFF)", "info")
        self._add_message("  /test          - Auto-test (ON/OFF)", "info")
        self._add_message("  /clear         - Pulisci la chat", "info")
        self._add_message("  /exit          - Esci dall'applicazione", "info")
        self._add_message("", "info")
        self._add_message("💡 Esempi:", "system")
        self._add_message("  /fix", "code")
        self._add_message("  fixa il gioco del tris che non parte", "code")
        self._add_message("", "info")
        self._add_message("  /model qwen2.5-coder:14b", "code")
        self._add_message("", "info")
        self._add_message("  /new", "code")
        self._add_message("  crea un gestionale per biblioteca in /path/proj", "code")

    def _change_model(self, model_name):
        """Cambia il modello LLM."""
        self._add_message(f"⟳ Cambio modello: {model_name}...", "info")

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
            self._add_message(f"✓ Modello cambiato: {model_found}", "success")

            # Nuova sessione con nuovo modello
            self.session = self.session_manager.create_session()
            self.session_label.config(text=f"Sessione: {self.session.id[:8]}")
        else:
            self._add_message(f"❌ Modello non trovato: {model_name}", "error")
            self._add_message("💡 Usa /model senza argomenti per vedere la lista", "info")

    def _show_context(self):
        """Mostra il contenuto di claude.md se esiste."""
        if self.file_ops and self.file_ops.working_dir:
            claude_path = Path(self.file_ops.working_dir) / "claude.md"
            if not claude_path.exists():
                claude_path = Path(self.file_ops.working_dir) / "CLAUDE.md"

            if claude_path.exists():
                try:
                    content = claude_path.read_text(encoding='utf-8', errors='replace')
                    self._add_message("📄 Contenuto di claude.md:", "info")
                    self._add_message("─" * 60, "system")
                    for line in content.split('\n')[:50]:  # Max 50 righe
                        self._add_message(line, "code")
                    if len(content.split('\n')) > 50:
                        self._add_message("... (troncato)", "info")
                except Exception as exc:
                    self._add_message(f"❌ Errore lettura: {e}", "error")
            else:
                self._add_message("⚠️ Nessun claude.md trovato nella directory corrente", "warning")
        else:
            self._add_message("⚠️ Directory di lavoro non impostata", "warning")

    def _reverse_engineer_gui(self, target: Path):
        """Genera documentazione per un progetto in modalità GUI."""
        import pathlib
        
        def reverse_thread():
            self.is_thinking = True
            self.root.after(0, lambda: self._set_status("● Reverse engineering...", "warning"))
            self.root.after(0, lambda: self.thinking_anim.start(self.thinking_container))
            
            try:
                self._reverse_log(f"reverse_start target={target}")
                # Scansione struttura e indice file
                self.root.after(0, lambda: self._add_message(f"📂 Scansione struttura: {target}", "info"))
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
                        f"📌 Policy: docs={d if d else 'none'} | roots={r if r else 'all'} | candidati={c}",
                        "info",
                    )
                )

                seen_files = stats.get("seen_files", 0)
                ignored = stats.get("ignored_ext", 0) + stats.get("ignored_size", 0) + stats.get("ignored_other", 0)
                self.root.after(0, lambda s=seen_files, i=ignored, c=len(candidates), d=stats.get("ignored_dirs", 0):
                    self._add_message(
                        f"📊 File visti: {s} | scartati scan: {i} | candidati(post-policy): {c} | dir ignorate: {d}",
                        "info",
                    )
                )
                self.root.after(0, lambda e=policy.get("excluded_tests", 0), cfg=policy.get("excluded_config", 0), lim=policy.get("limited", False), l=policy.get("limit", 0):
                    self._add_message(
                        f"🧹 Policy: test esclusi={e} | config esclusi={cfg} | limite candidati={l} | limitato={lim}",
                        "info",
                    )
                )
                if not candidates:
                    self._reverse_log("no_candidates")
                    self.root.after(0, lambda: self._add_message("❌ Nessun file rilevante trovato", "error"))
                    return
                tree = build_tree_from_paths(
                    [rel for rel, _, _ in candidates],
                    root_name=target.name,
                    max_lines=400,
                )
                self._reverse_log(f"tree_lines={tree.count(chr(10)) + 1 if tree else 0}")
                index_text, allowed_set = format_candidate_index(candidates)

                # Rileva se è un progetto Java PRIMA della selezione
                # Controlla se esistono file .java e pom.xml/build.gradle nella root
                has_java_files = any(
                    item[0].suffix.lower() == ".java"
                    for item in candidates
                )
                has_build_file = (target / "pom.xml").exists() or (target / "build.gradle").exists() or (target / "settings.gradle").exists()
                is_java_project = has_java_files and has_build_file
                is_spring = _is_spring_boot_project(target) if is_java_project else False
                
                if is_spring:
                    self.root.after(0, lambda: self._add_message("🍃 Rilevato progetto SPRING BOOT - Priorità alle classi @Service", "success"))
                    self._reverse_log("spring_boot_project=True")
                
                java_instruction = ""
                if is_java_project:
                    java_instruction = """
⚠️ PROGETTO JAVA MICROSERVIZIO - REGOLE SPECIALI:
- PRIORITÀ 1: Leggi TUTTE le classi *Service.java (contengono la logica di business)
- PRIORITÀ 2: Leggi le classi *Controller.java (API endpoint) e la classe Application principale
- PRIORITÀ 3: Leggi *Repository.java e DTO solo se necessario per contesto
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
                        self.root.after(0, lambda: self._add_message("⏹️ [Interrotto]", "warning"))
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
                    
                # Per progetti Java: includi SEMPRE le classi Service (priorità massima)
                java_services = []
                java_controllers = []
                if is_java_project:
                    java_services = find_java_service_classes(candidates)
                    java_controllers = find_java_controller_classes(candidates)
                    if java_services:
                        self._reverse_log(f"java_services_found={len(java_services)}")
                        if is_spring:
                            self.root.after(0, lambda n=len(java_services):
                                self._add_message(f"🍃 {n} classi Service Spring trovate - INCLUSE AUTOMATICAMENTE", "success")
                            )
                        else:
                            self.root.after(0, lambda n=len(java_services):
                                self._add_message(f"📦 Trovate {n} classi Service Java", "info")
                            )

                if not selected_by_llm:
                    selection_source = "fallback"
                    selected_by_llm = pick_default_files(candidates, limit=10)
                    self._reverse_log(f"fallback_selected={len(selected_by_llm)}")

                # Costruisci lista finale: PRIMA le Service (se Spring), poi le altre selezionate
                selected = []
                
                # Se è Spring Boot: metti Service ALL'INIZIO assolutamente
                if is_spring and java_services:
                    selected.extend(java_services)
                    self._reverse_log(f"spring_services_added_first={len(java_services)}")
                
                # Poi aggiungi le selezionate da LLM/fallback
                for item in selected_by_llm:
                    if item not in selected:
                        selected.append(item)
                
                # Aggiungi Controller se non sono già inclusi (max 15 file totali)
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
                    self._add_message(f"📚 {l} ({n}):\n{s}", "code")
                )
                if added_docs:
                    added_list = "\n".join([f"- {p.as_posix()}" for p in added_docs])
                    self.root.after(0, lambda s=added_list:
                        self._add_message(f"📎 File aggiunti dal bridge (docs):\n{s}", "code")
                    )

                files_content, read_stats = read_files_content_with_stats(
                    target, selected, max_chars_per_file=4000, max_total_chars=20000
                )
                self._reverse_log(f"files_content_len={len(files_content)}")
                self._reverse_log(f"files_read={read_stats.get('files_read')} total_chars={read_stats.get('total_chars')} truncated={read_stats.get('truncated')}")
                if not files_content:
                    self._reverse_log("no_files_content")
                    self.root.after(0, lambda: self._add_message("❌ Nessun contenuto letto", "error"))
                    return
                self.root.after(0, lambda r=read_stats.get("files_read", 0), ch=read_stats.get("total_chars", 0):
                    self._add_message(f"📥 File letti: {r} | caratteri totali: {ch}", "info")
                )

                # Fase 2: genera documentazione
                # Imposta opzioni per documentazione lunga
                original_num_predict = self.ollama.options.get('num_predict', 2048)
                original_num_ctx = self.ollama.options.get('num_ctx', 8192)
                original_timeout = self.ollama.timeout
                self.ollama.options['num_ctx'] = 16384
                self.ollama.options['num_predict'] = 8192  # Più spazio per documentazione completa
                self.ollama.timeout = 600  # 10 minuti timeout
                self._reverse_log("llm_options num_ctx=16384 num_predict=8192 timeout=600")

                java_doc_instruction = ""
                if is_java_project:
                    java_doc_instruction = """
⚠️ PROGETTO JAVA MICROSERVIZIO - ISTRUZIONI SPECIALI:
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
                        self.root.after(0, lambda: self._add_message("⏹️ [Interrotto]", "warning"))
                        break
                    response += chunk
                self._reverse_log(f"final_resp_len={len(response)}")

                # Ripristina opzioni
                self.ollama.options['num_predict'] = original_num_predict
                self.ollama.options['num_ctx'] = original_num_ctx
                self.ollama.timeout = original_timeout
                self.root.after(0, lambda: self.thinking_anim.stop())

                if response:
                    self.root.after(0, lambda: self._add_message(f"📝 Response ({len(response)} chars):", "info"))
                    self.root.after(0, lambda: self._add_message(response[:2000] + ("..." if len(response) > 2000 else ""), "code"))

                    parsed = self.parser.parse(response)
                    if parsed.is_valid and parsed.commands:
                        self._reverse_log(f"final_commands={len(parsed.commands)}")
                        self.root.after(0, lambda: self._add_message(f"✓ {len(parsed.commands)} comandi", "success"))
                        for i, cmd in enumerate(parsed.commands, 1):
                            ok, out = self.file_ops.execute_command(cmd)
                            if ok:
                                self.root.after(0, lambda idx=i: self._add_message(f"✓ Comando {idx} eseguito", "success"))
                            else:
                                self.root.after(0, lambda e=out, idx=i: self._add_message(f"✗ Comando {idx}: {e}", "error"))

                        doc_file = target / "DOCUMENTAZIONE.md"
                        if doc_file.exists():
                            self.root.after(0, lambda: self._add_message(f"📝 Documentazione salvata: {doc_file}", "success"))
                            content = doc_file.read_text(encoding='utf-8', errors='replace')[:1500]
                            self.root.after(0, lambda c=content: self._add_message(f"\n{c}...", "code"))
                    else:
                        # fallback: salva response come doc se contiene markdown
                        self.root.after(0, lambda: self._add_message("💡 Salvataggio manuale della documentazione...", "info"))
                        doc_file = target / "DOCUMENTAZIONE.md"
                        md_start = response.find('# ')
                        if md_start >= 0:
                            doc_content = response[md_start:]
                            doc_content = doc_content.replace('\\n', '\n')
                            doc_content = re.sub(r' +\n', '\n', doc_content)
                            doc_content = re.sub(r'\n{3,}', '\n\n', doc_content)
                            try:
                                doc_file.write_text(doc_content)
                                self.root.after(0, lambda: self._add_message(f"📝 Documentazione salvata: {doc_file}", "success"))
                                self.root.after(0, lambda: self._add_message("✅ Contenuto convertito: \\n → newline reali", "info"))
                            except Exception as exc:
                                self.root.after(0, lambda e=e: self._add_message(f"⚠️ Salvataggio fallito: {e}", "warning"))
                else:
                    self.root.after(0, lambda: self._add_message("⚠️ Nessuna risposta", "warning"))
                    
            except Exception as exc:
                error_msg = str(exc)
                self.root.after(0, lambda err=error_msg: self._add_message(f"❌ Errore: {err}", "error"))
            finally:
                self.is_thinking = False
                self.root.after(0, lambda: self._set_status("● Connesso", "success"))
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
        self._add_message(f"🛡️ Safety: {status}", "success")
        if self.state['safe']:
            self._add_message("  • Comandi distruttivi richiederanno conferma", "info")
        else:
            self._add_message("  • Attenzione: comandi distruttivi eseguiti senza conferma", "warning")

    def _toggle_auto(self):
        """Toggle auto-continue."""
        self.state['auto_c'] = not self.state.get('auto_c', True)
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
        status = "ON" if self.state['auto_c'] else "OFF"
        self._add_message(f"🔁 Auto-continue: {status}", "success")

    def _toggle_test(self):
        """Toggle auto-test."""
        self.state['auto_t'] = not self.state.get('auto_t', True)
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except:
            pass
        status = "ON" if self.state['auto_t'] else "OFF"
        self._add_message(f"🧪 Auto-test: {status}", "success")

    def _process_message(self, user_message):
        """Elabora il messaggio con LLM in thread separato."""

        # Controlli preliminari
        if not self.session:
            self._add_message("⚠️ Sessione non inizializzata, ne creo una nuova...", "warning")
            self._new_session()

        if not self.ollama or not self.connected:
            self._add_message("❌ Ollama non è connesso", "error")
            self._add_message("💡 Verifica che 'ollama serve' sia in esecuzione", "info")
            return

        def process(Path=Path):
            self.is_thinking = True
            self.root.after(0, lambda: self._set_status("● Pensando...", "warning"))
            self.root.after(0, lambda: self.thinking_anim.start(self.thinking_container))

            # Disabilita pulsanti
            self.root.after(0, lambda: self.send_btn.config(state=tk.DISABLED))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))

            try:
                # ✅ ESTRAI PATH dal messaggio utente (per /fix o fix di progetto esistente)
                # path_match = re.search(r'(/[a-zA-Z0-9_./-]+)', user_message)
                auto_path = self._extract_path_from_text(user_message)
                project_path = None
                if auto_path:
                    project_path = Path(auto_path)
                    if not project_path.exists():
                        project_path = None

                # ✅ WORKFLOW AGENTICO INTERATIVO PER '/new'
                if getattr(self, 'mode', 'default') == 'new':
                    self._execute_agentic_workflow(user_message, project_path)
                    return

                # ✅ RILEVA MODALITÀ /reverse
                is_reverse = "/reverse" in user_message.lower() or "reverse" in user_message.lower() or "documentazione" in user_message.lower()

                # ✅ LEGGI FILE ESISTENTI se è un fix o reverse di progetto esistente
                file_context = ""
                if project_path and project_path.exists():
                    self.root.after(0, lambda: self._add_message(f"📂 Lettura file da: {project_path}", "info"))

                    # Leggi file di codice + config + doc
                    code_files = []
                    
                    if is_reverse:
                        # Per /reverse leggi TUTTO ricorsivamente
                        self.root.after(0, lambda: self._add_message("🔍 Modalità REVERSE: lettura completa del progetto...", "info"))
                        
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
                            # Per reverse: più contenuto per file (3000 chars)
                            max_chars = 3000 if is_reverse else 1500
                            file_context += f"## {rel_path}:\n```\n{content[:max_chars]}\n```\n\n"
                        except Exception as exc:
                            pass

                    if file_context:
                        self.root.after(0, lambda: self._add_message(f"✓ Trovati {len(code_files)} file", "success"))
                        # Aggiungi contesto come primo messaggio
                        self.session.add_message("user", f"## Contesto file esistenti:\n\n{file_context}\n\n## PATH progetto: {project_path}")

                # Aggiungi messaggio utente
                self.session.add_message("user", user_message)

                # Debug: controlla che ci siano messaggi
                messages = self.session.to_ollama_messages()
                if not messages:
                    self.root.after(0, lambda: self._add_message("⚠️ Nessun messaggio nella sessione", "warning"))
                    return

                # Chiama Ollama
                response = ""
                for chunk in self.ollama.chat(messages, stream=True):
                    if self.stop_flag:
                        self.root.after(0, lambda: self._add_message("⏹️ [Interrotto dall'utente]", "warning"))
                        break
                    response += chunk

                # Controlla se la risposta è vuota
                if not response or not response.strip():
                    self.root.after(0, lambda: self._add_message("⚠️ Nessuna risposta dall'LLM", "warning"))
                    self.root.after(0, lambda: self._add_message("💡 Prova a riformulare la richiesta o cambia modello", "info"))
                else:
                    # ✅ LOG COMPLETO DELLA RESPONSE
                    self.root.after(0, lambda: self._add_message(f"📝 RAW Response ({len(response)} chars):", "info"))
                    self.root.after(0, lambda: self._add_message(response[:2000] + ("..." if len(response) > 2000 else ""), "code"))

                    # ✅ PARSING ED ESECUZIONE COMANDI
                    parsed = self.parser.parse(response)

                    if not parsed.is_valid:
                        self.root.after(0, lambda: self._add_message(f"❌ Parsing fallito: {parsed.error}", "error"))
                        self.root.after(0, lambda: self._add_message(f"💡 Raw JSON: {parsed.raw_response[:500]}", "warning"))
                        self.session.add_message("assistant", response)
                    elif parsed.commands:
                        self.root.after(0, lambda: self._add_message(f"✓ {len(parsed.commands)} comandi parsati", "success"))

                        # Esegui comandi - sincrono per evitare bug con lambda
                        for i, cmd in enumerate(parsed.commands, 1):
                            self.root.after(0, lambda c=cmd, idx=i: self._add_message(f"[{idx}] {c[:100]}...", "info"))
                            ok, out = self.file_ops.execute_command(cmd)
                            if ok:
                                output_msg = f"✓ Comando {i} eseguito"
                                if out and len(out) < 500:
                                    output_msg += f"\n  Output: {out}"
                                self.root.after(0, lambda m=output_msg: self._add_message(m, "success"))
                            else:
                                self.root.after(0, lambda e=out, idx=i: self._add_message(f"✗ Comando {idx} fallito: {e}", "error"))

                        self.session.add_message("assistant", response)
                    else:
                        self.session.add_message("assistant", response)
                        self.root.after(0, lambda: self._add_message(response, "ai"))

            except Exception as exc:
                # Gestione errori dettagliata
                error_msg = str(exc) if exc else "Errore sconosciuto"
                error_type = type(exc).__name__

                self.root.after(0, lambda: self._add_message(f"❌ Errore ({error_type}): {error_msg}", "error"))

                # Suggerimenti basati sul tipo di errore
                if "Connection" in error_type or "connection" in error_msg.lower():
                    self.root.after(0, lambda: self._add_message("💡 Verifica che 'ollama serve' sia in esecuzione", "info"))
                elif "Timeout" in error_type or "timeout" in error_msg.lower():
                    self.root.after(0, lambda: self._add_message("💡 Il modello sta impiegando troppo tempo, prova con un modello più veloce", "info"))
                elif "500" in error_msg:
                    self.root.after(0, lambda: self._add_message("💡 Errore interno di Ollama, prova a riavviare il servizio", "info"))
                elif "404" in error_msg:
                    self.root.after(0, lambda: self._add_message("💡 Modello non trovato, usa /model per cambiare", "info"))
                else:
                    self.root.after(0, lambda: self._add_message("💡 Riprova o controlla i log per dettagli", "info"))

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
                    self.root.after(0, lambda: self._add_message(f"⚠️ Errore log: {log_err}", "warning"))

            finally:
                self.is_thinking = False
                self.stop_flag = False
                self.root.after(0, lambda: self.thinking_anim.stop())
                self.root.after(0, lambda: self._set_status("● Connesso", "success"))
                self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

        threading.Thread(target=process, daemon=True).start()

    def _execute_direct_workflow(self, user_message, project_path):
        """Workflow a 2 fasi con memoria di progetto per coerenza tra step."""
        try:
            logger.info(f"=== INIZIO WORKFLOW CON MEMORIA ===")
            logger.info(f"Modello planner: {self.ollama.model}")
            logger.info(f"User message: {user_message[:200]}")
            logger.info(f"Project path: {project_path}")
            
            self.root.after(0, lambda: self._add_message("\n🧠 FASE 1: PIANIFICAZIONE CON MEMORIA...", "info"))
            
            # Costruisci il path del progetto
            p_path = project_path or Path(".")
            p_path.mkdir(parents=True, exist_ok=True)
            
            # Inizializza memoria di progetto
            memory = ProjectMemory(p_path)
            memory.clear()  # Pulisci memoria precedente
            
            # Estrai info dal messaggio utente
            project_name = "Progetto"
            if "tris" in user_message.lower():
                project_name = "Gioco del Tris"
            elif "calcolatrice" in user_message.lower():
                project_name = "Calcolatrice"
            
            memory.set_project_info(project_name, user_message[:200])
            logger.info(f"Memoria inizializzata per: {project_name}")
            
            # Prompt SOLO per pianificazione - SENZA codice, SOLO contratti
            plan_prompt = f"""Sei un software architect senior. Il tuo compito è creare un PIANO ARCHITETTURALE con CONTRATTI tra file.

⚠️ REGOLE ASSOLUTE:
- ❌ VIETATO scrivere codice in qualsiasi forma
- ❌ VIETATO scrivere frammenti CSS, JS, HTML
- ❌ VIETATO scrivere comandi PowerShell
- ✅ SCRIVI SOLO descrizioni testuali di COSA deve contenere ogni file
- ✅ DEFINISCI i contratti: ID, classi, nomi funzioni che i file si scambiano

PROGETTO: {user_message}

FORMATO OUTPUT RICHIESTO:

## Descrizione Progetto
[2-3 righe che spiegano COSA fa l'applicazione]

## File Da Creare

### index.html
Scopo: [descrizione verbale dello scopo]
Elementi richiesti:
- Container principale con ID "app" o "game-container"
- Griglia 3x3 con 9 celle, ognuna con classe "cell" e data-index da 0 a 8
- Display stato con ID "status" che mostra il turno corrente
- Bottone reset con ID "reset-btn"
- Link a style.css nel <head>
- Link a script.js prima di </body>
NON scrivere: codice HTML, tag, attributi completi

### style.css
Scopo: [descrizione verbale]
Elementi da stilizzare:
- Selettore: .cell (100px, flexbox per centrare, bordo, hover effect)
- Selettore: #status (font grande, colore)
- Selettore: #reset-btn (padding, background, hover)
- Layout: grid 3x3 per il board
NON scrivere: regole CSS complete, valori esatti

### script.js
Scopo: [descrizione verbale]
Variabili globali:
- board: array di 9 elementi
- currentPlayer: 'X' o 'O'
- gameActive: boolean
Funzioni richieste:
- handleCellClick(event): gestisce click su cella
- checkResult(): controlla vittoria/pareggio
- resetGame(): resetta stato
ID da referenziare: #status, #reset-btn
Classi da manipolare: .cell, .cell.x, .cell.o
NON scrivere: implementazione funzioni, codice JS

## Contratto tra file
- index.html ESPONE: #status, #reset-btn, .cell[data-index]
- style.css STILIZZA: .cell, #status, #reset-btn
- script.js MANIPOLA: #status.textContent, .cell.classList, #reset-btn.addEventListener

Genera ORA il piano per: {user_message}"""

            self.root.after(0, lambda: self._add_message("\n📝 Generazione piano...", "info"))

            logger.info(f"=== PIANO PROMPT ===\n{plan_prompt[:2000]}")
            plan_resp = ""
            for chunk in self.ollama.chat([{"role": "user", "content": plan_prompt}], stream=True):
                if self.stop_flag:
                    break
                plan_resp += chunk

            logger.info(f"=== PIANO RISPOSTA ({len(plan_resp)} chars) ===\n{plan_resp[:3000]}")

            if self.stop_flag:
                return

            if not plan_resp.strip():
                logger.error("ERRORE: risposta del piano è VUOTA. Il modello non ha risposto nulla.")
                self.root.after(0, lambda: self._add_message("❌ Risposta piano vuota - controlla i log", "error"))

            # Salva il piano
            plan_file = p_path / "claude_plan.md"
            plan_file.write_text(plan_resp, encoding="utf-8", errors="replace")
            logger.info(f"Piano salvato ({len(plan_resp)} chars)")
            self.root.after(0, lambda: self._add_message(f"📝 Piano salvato", "success"))
            
            # Estrai nomi file dal piano
            import re
            file_patterns = {
                'index.html': r'(?:index\.html|html)',
                'style.css': r'(?:style\.css|css)',
                'script.js': r'(?:script\.js|js)'
            }
            
            steps = []
            for filename, pattern in file_patterns.items():
                if re.search(pattern, plan_resp, re.IGNORECASE):
                    steps.append(filename)
            
            if not steps:
                steps = ['index.html', 'style.css', 'script.js']  # Default per web projects
            
            logger.info(f"Step da eseguire: {steps}")
            
            # FASE 2: Esecuzione con memoria
            self.root.after(0, lambda: self._add_message(f"\n🚀 FASE 2: ESECUZIONE {len(steps)} FILE", "info"))
            
            # File creati con successo
            created_files = []
            
            for i, filename in enumerate(steps, 1):
                if self.stop_flag:
                    break
                    
                # Ottieni memoria attuale da iniettare
                memory_context = memory.get_memory_summary()
                
                # Costruisci regole specifiche per tipo file
                ext = filename.lower().split('.')[-1] if '.' in filename else ''
                file_rules = ""
                if ext == 'html':
                    file_rules = """REGOLE HTML:
- VIETATO <style>...</style> inline
- VIETATO <script>...</script> inline
- OBBLIGATORIO: <link rel="stylesheet" href="style.css"> nel <head>
- OBBLIGATORIO: <script src="script.js"></script> prima di </body>
- Scrivi HTML completo con <!DOCTYPE html>"""
                elif ext == 'css':
                    file_rules = """REGOLE CSS:
- SOLO regole CSS, niente HTML o JS
- Ogni regola su riga separata (usa \\n tra le regole)
- Codice completo e funzionante"""
                elif ext == 'js':
                    file_rules = """REGOLE JS:
- SOLO codice JavaScript, niente HTML o CSS
- USA SOLO virgolette DOPPIE "" per le stringhe (MAI virgolette singole '')
- getElementById("id") e querySelectorAll(".class") con virgolette doppie
- Funzioni complete con parentesi graffe { }
- Codice completo e funzionante"""

                step_msg = f"""## STEP {i}/{len(steps)}: CREA {filename}

Piano: {plan_resp[:800]}

{memory_context}

{file_rules}

## FORMATO OBBLIGATORIO:
CREA SOLO {filename}. Rispondi SOLO con JSON:
{{"cmd1": "Set-Content -Path '{filename}' -Value 'CONTENUTO_COMPLETO_QUI'"}}

Escaping: ' nel contenuto = '' | newline = \\\\n | tab = \\\\t | " nel contenuto = \\\\"
Il codice deve essere COMPLETO e FUNZIONANTE.
"""
                
                self.root.after(0, lambda fn=filename, idx=i: self._add_message(f"\n▶ STEP {idx}: {fn}", "warning"))
                
                # Chiama LLM con retry
                max_retries = 2
                success = False
                
                for attempt in range(max_retries + 1):
                    if self.stop_flag:
                        break

                    # System prompt JSON iniettato via API (non nel modelfile)
                    exec_system = (
                        "You are a senior software engineer. "
                        "Reply ONLY with a valid JSON object like: "
                        "{\"cmd1\": \"Set-Content -Path 'filename' -Value 'content'\"}. "
                        "Escape single quotes inside content as ''. "
                        "Use \\n for newlines. No explanations, no markdown, no text outside JSON."
                    )
                    exec_messages = [
                        {"role": "system", "content": exec_system},
                        {"role": "user", "content": step_msg}
                    ]

                    logger.info(f"=== STEP {i} attempt {attempt+1}: invio prompt ({len(step_msg)} chars) ===\n{step_msg[:1500]}")

                    response = ""
                    for chunk in self.ollama.chat(exec_messages, stream=True):
                        if self.stop_flag:
                            break
                        response += chunk

                    logger.info(f"=== STEP {i} RISPOSTA ({len(response)} chars) ===\n{response[:2000]}")

                    if self.stop_flag:
                        break

                    # Rimuovi eventuali thinking tags prima del parsing
                    clean_response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL | re.IGNORECASE).strip()

                    # Estrai JSON
                    json_match = re.search(r'\{.*\}', clean_response, re.DOTALL)
                    if json_match:
                        parsed = self.parser.parse(json_match.group(0))
                        if not parsed.is_valid:
                            logger.warning(f"JSON trovato ma non valido: {parsed.error}. JSON estratto: [{json_match.group(0)[:300]}]")
                        if parsed.is_valid and parsed.commands:
                            # Esegui comandi
                            for cmd in parsed.commands:
                                ok = self._execute_command_with_fallback(cmd, p_path, filename)
                                if ok:
                                    # Aggiorna memoria
                                    self._update_memory_from_file(memory, filename, response)
                                    created_files.append(filename)
                                    self.root.after(0, lambda fn=filename: self._add_message(f"✓ {fn} creato", "success"))
                                    success = True
                                    break
                                else:
                                    self.root.after(0, lambda: self._add_message("✗ Errore esecuzione", "error"))
                        
                        if success:
                            break
                        else:
                            if attempt < max_retries:
                                logger.warning(f"Retry {attempt+1} per {filename}")
                                self.root.after(0, lambda a=attempt+1: self._add_message(f"🔄 Retry {a}...", "warning"))
                                step_msg += "\n\n⚠️ RISPOSTA PRECEDENTE NON VALIDA! Riprova con JSON corretto."
                    else:
                        if attempt < max_retries:
                            logger.warning(f"Nessun JSON trovato nella risposta (attempt {attempt+1}). Risposta ricevuta: [{response[:500]}]")
                            self.root.after(0, lambda a=attempt+1: self._add_message(f"🔄 Retry {a}...", "warning"))
                            step_msg += "\n\n⚠️ NON hai generato JSON! Rispondi SOLO con JSON valido."
                        else:
                            logger.error(f"Nessun JSON trovato dopo tutti i tentativi. Ultima risposta: [{response[:1000]}]")
                
                if not success:
                    logger.error(f"Fallito creazione {filename} dopo {max_retries+1} tentativi")
                    self.root.after(0, lambda fn=filename: self._add_message(f"✗ {fn} FALLITO", "error"))
            
            # VALIDAZIONE FINALE
            logger.info(f"File creati: {created_files}")
            required_files = ['index.html', 'style.css', 'script.js']
            missing = [f for f in required_files if f not in created_files]
            
            if missing:
                self.root.after(0, lambda m=missing: self._add_message(f"⚠️ File mancanti: {', '.join(m)}", "warning"))
                self.root.after(0, lambda: self._add_message("🔄 Tentativo recupero...", "info"))
                
                # Retry per file mancanti
                for missing_file in missing:
                    retry_msg = f"""## RECUPERO FILE MANCANTE: {missing_file}

Il progetto NON funziona senza {missing_file}!

{memory.get_memory_summary()}

## REGOLE:
- Se {missing_file} == "style.css": SOLO CSS, selettori .cell, #status, #reset-btn
- Se {missing_file} == "index.html": SOLO HTML con <link href="style.css"> e <script src="script.js">
- Se {missing_file} == "script.js": SOLO JS con getElementById e querySelectorAll

Genera SOLO JSON: {{"cmd1": "Set-Content -Path '{missing_file}' -Value '...'"}}"""
                    
                    retry_resp = ""
                    for chunk in self.ollama.chat([{"role": "user", "content": retry_msg}], stream=True):
                        if self.stop_flag:
                            break
                        retry_resp += chunk
                    
                    if retry_resp:
                        json_match = re.search(r'\{.*\}', retry_resp, re.DOTALL)
                        if json_match:
                            parsed = self.parser.parse(json_match.group(0))
                            if parsed.is_valid and parsed.commands:
                                for cmd in parsed.commands:
                                    ok = self._execute_command_with_fallback(cmd, p_path, missing_file)
                                    if ok:
                                        created_files.append(missing_file)
                                        self.root.after(0, lambda fn=missing_file: self._add_message(f"✓ {fn} recuperato!", "success"))
            
            memory.save()
            logger.info(f"=== WORKFLOW COMPLETATO - File: {created_files} ===")
            self.root.after(0, lambda: self._add_message("\n🎉 PROGETTO COMPLETATO", "success"))
            self.mode = 'default'
            
        except Exception as exc:
            logger.error(f"ERRORE: {exc}")
            self.root.after(0, lambda e=str(exc): self._add_message(f"❌ ERRORE: {e}", "error"))
        
        finally:
            self.is_thinking = False
            self.stop_flag = False
            self.root.after(0, lambda: self.thinking_anim.stop())
            self.root.after(0, lambda: self._set_status("● Connesso", "success"))
            self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    def _execute_command_with_fallback(self, cmd: str, p_path: Path, filename: str) -> bool:
        """Esegue comando con fallback Python nativo, parsing robusto e VALIDAZIONE."""
        try:
            import re
            cmd_str = cmd.strip()
            
            if cmd_str.startswith("Set-Content") or cmd_str.startswith("Add-Content"):
                # Estrai Path
                p_match = re.search(r"-Path\s+'([^']*)'", cmd_str)
                if not p_match:
                    p_match = re.search(r"-Path\s+\"([^\"]*)\"", cmd_str)
                if not p_match:
                    logger.error(f"❌ Nessun -Path trovato nel comando")
                    return False
                
                # Estrai Value con parsing ROBUSTO
                content = self._extract_value_from_command(cmd_str)
                if content is None:
                    logger.error(f"❌ Impossibile estrarre -Value dal comando")
                    return False
                
                # === VALIDAZIONE CRITICA ===
                validation = self._validate_file_content(filename, content)
                if not validation['valid']:
                    logger.error(f"❌ VALIDAZIONE FALLITA per {filename}: {validation['reason']}")
                    return False
                # =========================
                
                t_file = p_path / Path(p_match.group(1)).name
                t_file.parent.mkdir(parents=True, exist_ok=True)
                mode = 'a' if cmd_str.startswith("Add-Content") else 'w'
                with open(t_file, mode, encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"✅ File creato: {t_file.name} ({len(content)} bytes)")
                return True
            
            # Supporto heredoc: cat << 'EOF' > file o cat << 'EOF' > file
            heredoc_match = re.search(
                r"cat\s+<<\s*'?EOF'?\s*>\s*(.+?)(?:\s*\n|\s*\\n)",
                cmd_str
            )
            if heredoc_match:
                heredoc_path = heredoc_match.group(1).strip().strip("'\"")
                # Estrai contenuto tra la prima riga e EOF finale
                # Il contenuto è tutto dopo il primo newline fino a EOF
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

                if content.strip():
                    validation = self._validate_file_content(filename, content)
                    if not validation['valid']:
                        logger.error(f"❌ VALIDAZIONE FALLITA per {filename}: {validation['reason']}")
                        return False

                    t_file = p_path / Path(heredoc_path).name
                    t_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(t_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"✅ File creato (heredoc): {t_file.name} ({len(content)} bytes)")
                    return True

            # Fallback a shell
            ok, out = self.file_ops.execute_command(cmd)
            return ok
        except Exception as e:
            logger.error(f"Errore esecuzione: {e}")
            return False
    
    def _extract_value_from_command(self, cmd_str: str) -> str:
        """
        Estrae il contenuto da -Value con parsing robusto.
        Gestisce virgolette escapate '' e \n.
        """
        v_start = cmd_str.find("-Value ")
        if v_start == -1:
            v_start = cmd_str.find("-Value\t")
        
        if v_start == -1:
            return None
        
        # Trova l'inizio del valore
        value_start_pos = v_start + 7
        while value_start_pos < len(cmd_str) and cmd_str[value_start_pos] in ' \t':
            value_start_pos += 1
        
        if value_start_pos >= len(cmd_str):
            return None
        
        quote_char = cmd_str[value_start_pos]
        if quote_char not in ("'", '"'):
            return None
        
        # Parsing carattere per carattere per gestire escaping
        content_chars = []
        pos = value_start_pos + 1  # salta virgoletta iniziale
        
        while pos < len(cmd_str):
            char = cmd_str[pos]
            
            # Fine stringa: virgoletta non escapata
            if char == quote_char:
                # Controlla se è escapata (SEGUITA da altra virgoletta uguale → '')
                if quote_char == "'" and pos + 1 < len(cmd_str) and cmd_str[pos + 1] == "'":
                    # '' → aggiungi una singola ' e salta entrambe
                    content_chars.append("'")
                    pos += 2
                    continue
                else:
                    # Virgoletta di chiusura trovata
                    break
            
            # Gestione backslash escapes
            if char == '\\' and pos + 1 < len(cmd_str):
                next_char = cmd_str[pos + 1]
                if next_char == 'n':
                    content_chars.append('\n')
                    pos += 2
                    continue
                elif next_char == 't':
                    content_chars.append('\t')
                    pos += 2
                    continue
                elif next_char == '\\':
                    content_chars.append('\\')
                    pos += 2
                    continue
                elif next_char == quote_char:
                    content_chars.append(quote_char)
                    pos += 2
                    continue
            
            content_chars.append(char)
            pos += 1
        
        content = ''.join(content_chars)
        return content
    
    def _validate_file_content(self, filename: str, content: str) -> dict:
        """Valida che il contenuto del file sia valido e NON un placeholder."""
        stripped = content.strip()
        
        # Controllo 1: contenuto non vuoto/minimo
        if len(stripped) < 20:
            return {'valid': False, 'reason': f'Contenuto troppo corto ({len(stripped)} chars)'}
        
        # Controllo 2: NO placeholder
        if stripped in ['...', '...', 'TODO', 'fixme']:
            return {'valid': False, 'reason': 'Contenuto è un placeholder'}
        
        if '...' in stripped and len(stripped) < 100:
            return {'valid': False, 'reason': 'Contiene "..." come placeholder'}
        
        # Controllo 3: validazione per tipo file
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        
        if ext == 'html':
            if '<html' not in stripped.lower() and '<!doctype' not in stripped.lower():
                return {'valid': False, 'reason': 'HTML: manca tag <html> o <!DOCTYPE>'}
            if 'style.css' not in stripped.lower():
                return {'valid': False, 'reason': 'HTML: manca link a style.css'}
            if 'script.js' not in stripped.lower():
                return {'valid': False, 'reason': 'HTML: manca script src="script.js"'}
            if '<style>' in stripped.lower():
                return {'valid': False, 'reason': 'HTML: CSS inline non permesso'}
            if '<script>' in stripped.lower() and 'src=' not in stripped.lower():
                return {'valid': False, 'reason': 'HTML: JS inline non permesso'}
        
        elif ext == 'css':
            if '{' not in content or '}' not in content:
                return {'valid': False, 'reason': 'CSS: mancano parentesi graffe'}
            # CSS dovrebbe avere multiple righe, non tutto su una riga
            if '\n' not in content and len(stripped) > 200:
                return {'valid': False, 'reason': 'CSS: tutto su una riga, serve newline'}
        
        elif ext == 'js':
            # NO punto iniziale
            if stripped.startswith('.'):
                return {'valid': False, 'reason': 'JS: inizia con "." (errore parsing)'}
            if 'function' not in stripped.lower() and '=>' not in stripped:
                return {'valid': False, 'reason': 'JS: manca almeno una funzione'}
            # Controllo virgolette non chiuse - conta le virgolette singole
            single_quotes = stripped.count("'")
            # Se dispari, c'è una virgoletta non chiusa
            if single_quotes % 2 != 0:
                return {'valid': False, 'reason': f'JS: {single_quotes} virgolette singole (numero dispari = sintassi rotta)'}
            # Controllo stringhe vuote malformate
            if "!== '" in stripped or "== '" in stripped:
                if "''" not in stripped:
                    return {'valid': False, 'reason': 'JS: confronto con stringa vuota malformato (usa "" non \')'}
        
        return {'valid': True, 'reason': 'OK'}

    def _update_memory_from_file(self, memory: ProjectMemory, filename: str, response: str) -> None:
        """Aggiorna memoria basandosi sul file creato."""
        import re
        
        # Estrai il contenuto effettivo dal JSON response
        content = ""
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            # Cerca il Value nel comando
            value_match = re.search(r"-Value\s+'(.+)'", json_match.group(0), re.DOTALL)
            if value_match:
                content = value_match.group(1)
                # Unescape
                content = content.replace("''", "'").replace('\\n', '\n')
        
        if not content:
            content = response  # Fallback
        
        if filename == 'index.html':
            ids = re.findall(r'id=["\']([^"\']+)["\']', content)
            classes = re.findall(r'class=["\']([^"\']+)["\']', content)
            has_css_link = bool(re.search(r'<link[^>]*href=["\']style\.css["\']', content))
            has_js_link = bool(re.search(r'<script[^>]*src=["\']script\.js["\']', content))
            has_inline_style = bool(re.search(r'<style[^>]*>.*?</style>', content, re.DOTALL))
            has_inline_script = bool(re.search(r'<script(?![^>]*src=)[^>]*>.*?</script>', content, re.DOTALL))
            
            memory.register_file(filename, "Struttura HTML", {
                "ids": ids,
                "classes": classes,
                "has_css_link": [str(has_css_link)],
                "has_js_link": [str(has_js_link)],
                "has_inline_style": [str(has_inline_style)],
                "has_inline_script": [str(has_inline_script)]
            })
            
            if has_inline_style or has_inline_script:
                logger.warning(f"⚠️ {filename} contiene CSS/JS inline!")
                memory.add_decision(f"ATTENZIONE: {filename} ha codice inline invece di file separati")
                
        elif filename == 'style.css':
            selectors = re.findall(r'([.#][a-zA-Z0-9_-]+)\s*\{', content)
            memory.register_file(filename, "Stili CSS", {
                "selectors": selectors
            })
            
        elif filename == 'script.js':
            functions = re.findall(r'function\s+([a-zA-Z0-9_]+)', content)
            variables = re.findall(r'(?:let|const|var)\s+([a-zA-Z0-9_]+)', content)
            used_ids = re.findall(r'getElementById\(["\']([^"\']+)["\']\)', content)
            used_classes = re.findall(r'(?:querySelectorAll|querySelector)\(["\']([^"\']+)["\']\)', content)
            memory.register_file(filename, "Logica JavaScript", {
                "functions": functions,
                "variables": variables,
                "used_ids": used_ids,
                "used_classes": used_classes
            })

    def _execute_agentic_workflow(self, user_message, project_path):
        """Esegue il workflow in due fasi: Pianificazione + Esecuzione Iterativa."""
        try:
            # VERIFICA se il modello corrente è un modello "coder" completo (qwen3.5, ecc.)
            # Se sì, salta il workflow agentic e usa il modello COME esecutore diretto
            current_model_lower = self.ollama.model.lower()
            is_full_coder = any(x in current_model_lower for x in ['qwen', 'coder', 'sushi'])
            
            if is_full_coder:
                # ✅ USA QWEN3.5 COME PIANIFICATORE + ESECUTORE
                return self._execute_direct_workflow(user_message, project_path)
            
            # Altrimenti usa il workflow agentic classico (pianificatore + esecutore separati)
            self.root.after(0, lambda: self._add_message("\n🧠 FASE 1: PIANIFICAZIONE ARCHITETTURALE...", "info"))
            
            # Usa gemma:latest (o fallback) per pianificare, NON il modello 'create' con i vincoli JSON
            planner_model = self.config.get("ollama", {}).get("planner_model", "gemma:latest")
            installed = [m for m in self.ollama.list_models()]
            if planner_model not in installed and installed:
                planner_model = installed[0] 
                
            original_model = self.ollama.model
            self.ollama.model = planner_model
            self.root.after(0, lambda: self._add_message(f"Uso {planner_model} per progettare...", "system"))
            
            plan_prompt = f"""Sei un software architect. Dividi questo progetto in piccoli step sequenziali (max 5).

REGOLA FONDAMENTALE:
- DEVI DEDICARE UN SOLO FILE PER OGNI STEP (es: Step 1 solo per index.html, Step 2 solo per style.css, Step 3 solo per script.js).
- OGNI step DEVE menzionare ESPlicitamente il nome del file con il formato: `nomefile.estensione` (con backticks!)
- DESCRIVI il contenuto dettagliato di ogni file, NON solo la struttura generale.
- ⚠️ IMPORTANTE: Per progetti WEB, devi avere ESATTAMENTE 3 step:
  Step 1: `index.html` - con <link rel="stylesheet" href="style.css"> e <script src="script.js"></script>
  Step 2: `style.css` - con tutti gli stili (layout, colori, hover, responsive)
  Step 3: `script.js` - con tutta la logica (eventi, funzioni, condizioni)

Rispondi SOLO in Markdown strutturato esattamente in questo formato:

# Sommario
Breve descrizione funzionale del progetto (2-3 righe).

# Step 1
Creazione del file `index.html`. Descrivi ESATTAMENTE cosa deve contenere: struttura HTML, elementi DOM, collegamenti a CSS/JS.

# Step 2
Creazione del file `style.css`. Descrivi gli stili completi: layout, colori, tipografia, responsive design.

# Step 3
Creazione del file `script.js`. Descrivi la logica completa: variabili, funzioni, event handler, condizioni.

Progetto richiesto: {user_message}"""
            
            plan_resp = ""
            for chunk in self.ollama.chat([{"role": "user", "content": plan_prompt}], stream=True):
                if self.stop_flag: break
                plan_resp += chunk
                
            # Ripristina modello rigoroso
            self.ollama.model = original_model
            if self.stop_flag: return
            
            p_path = project_path or Path(".")
            p_path.mkdir(parents=True, exist_ok=True)
            try:
                (p_path / "claude_plan.md").write_text(plan_resp, encoding="utf-8", errors="replace")
                self.root.after(0, lambda: self._add_message(f"📝 Piano salvato in {p_path / 'claude_plan.md'}", "success"))
            except Exception as e:
                self.root.after(0, lambda: self._add_message(f"⚠️ Impossibile salvare claude_plan.md: {e}", "warning"))
                
            # Parsing del piano Markdown
            import re
            summary_match = re.search(r'# Sommario\n(.*?)(?=\n# Step)', plan_resp, re.DOTALL | re.IGNORECASE)
            summary = summary_match.group(1).strip() if summary_match else ""
            
            steps = []
            step_matches = re.finditer(r'# Step \d+(.*?)(?=\n# Step |\Z)', plan_resp, re.DOTALL | re.IGNORECASE)
            for m in step_matches:
                s = m.group(1).strip()
                if s: steps.append(s)
                
            if not steps:
                steps = [plan_resp] # fallback se formatta male
                
            self.root.after(0, lambda: self._add_message(f"\n🚀 FASE 2: ESECUZIONE DI {len(steps)} STEP CON {self.ollama.model}", "info"))
            
            for i, step_text in enumerate(steps, 1):
                if self.stop_flag: break
                self.root.after(0, lambda idx=i: self._add_message(f"\n▶──────── STEP {idx}/{len(steps)} ────────◀", "warning"))
                
                # Migliora il testo dello step per essere PIÙ specifico sul file da creare
                # Estrai il nome file dal testo dello step
                import re
                file_match = re.search(r'`([a-zA-Z0-9_.-]+)`', step_text)
                file_name = file_match.group(1) if file_match else "il file richiesto"
                
                # Estrai l'estensione per capire il tipo
                ext = file_name.split('.')[-1].lower() if '.' in file_name else ""
                file_type_map = {
                    'html': 'HTML strutturato con link a CSS/JS',
                    'css': 'CSS con stili completi (layout, colori, hover)',
                    'js': 'JavaScript con logica completa (eventi, funzioni, condizioni)',
                    'py': 'Python con codice funzionante',
                    'java': 'Java con classi complete'
                }
                file_desc = file_type_map.get(ext, 'codice completo')
                
                # Messaggi specifici in base al tipo di file
                extra_rules = ""
                if ext == 'html':
                    extra_rules = "\n⚠️ DEVI INCLUDERE: <link rel='stylesheet' href='style.css'> E <script src='script.js'></script>"
                elif ext == 'css':
                    extra_rules = "\n⚠️ DEVI INCLUDERE: tutti gli stili (body, container, elementi, hover, responsive)"
                elif ext == 'js':
                    extra_rules = "\n⚠️ DEVI INCLUDERE: event listeners, funzioni principali, logica di gioco/app"
                
                step_msg = f"""## PROGETTO (Contesto generale):
{summary}

## STEP {i}/{len(steps)} - DEVI CREARE QUESTO FILE: {file_name}
{step_text}

## ISTRUZIONI PER CREARE {file_name}:
- Tipo file: {file_desc}
- Path: usa SOLO il nome '{file_name}' nel parametro -Path
- Formato: Set-Content -Path '{file_name}' -Value 'codice_completo'
{extra_rules}

## REGOLE CRUCIALI:
1. ✅ File DA CREARE: {file_name} (NON altri file!)
2. ✅ CODICE COMPLETO: NO placeholder, NO '// ...', NO '/* insert code */'
3. ✅ NEWLINE: usa \\n per andare a capo nel Value
4. ✅ VIRGOLETTE: se il codice ha ' (apice singolo), escapalo con '' (doppio apice)
5. ✅ PARENTESI graffe {{ }} nel CSS/JS VANNO BENISSIMO - NON escaparle!
6. ❌ NON creare file diversi da {file_name}
7. ❌ NON usare cat << EOF (è sintassi bash, non PowerShell!)
8. ❌ NON saltare newline - ogni riga deve essere separata da \\n
9. ⚠️ Il file DEVE essere COMPLETO e FUNZIONANTE da solo

## ESEMPIO CORRETTO per {file_name}:
Set-Content -Path '{file_name}' -Value 'riga 1\\nriga 2 {{ con parentesi }}\\nriga 3'

## OUTPUT RICHIESTO:
JSON con UNA SOLA chiave cmd1 (o più se necessario) contenente il comando Set-Content per {file_name}."""
                
                s_resp = ""
                for chunk in self.ollama.chat([{"role": "user", "content": step_msg}], stream=True):
                    if self.stop_flag: break
                    s_resp += chunk
                    
                if self.stop_flag: break
                
                self.root.after(0, lambda l=len(s_resp): self._add_message(f"📝 JSON dallo step ({l} crt)", "system"))
                
                parsed = self.parser.parse(s_resp)
                if parsed.is_valid and parsed.commands:
                    for idx, cmd in enumerate(parsed.commands, 1):
                        self.root.after(0, lambda c=cmd[:80]: self._add_message(f"⚙️ Eseguo: {c}...", "info"))
                        
                        cmd_str = cmd.strip()
                        intercepted = False
                        
                        try:
                            import re
                            if cmd_str.startswith("New-Item") and "-ItemType Directory" in cmd_str:
                                p_match = re.search(r"-Path\s+'(.*?)'", cmd_str)
                                if p_match:
                                    target_name = Path(p_match.group(1)).name
                                    target_dir = p_path / target_name
                                    target_dir.mkdir(parents=True, exist_ok=True)
                                    self.root.after(0, lambda: self._add_message("   ✓ Directory creata (Python Native)", "success"))
                                    intercepted = True
                            
                            elif cmd_str.startswith("Set-Content") or cmd_str.startswith("Add-Content"):
                                # Estrai Path
                                p_match = re.search(r"-Path\s+'([^']*)'", cmd_str)
                                if not p_match:
                                    p_match = re.search(r"-Path\s+\"([^\"]*)\"", cmd_str)
                                
                                # Estrai Value - APPROCCIO MIGLIORATO
                                # Trova l'inizio di -Value
                                v_start = cmd_str.find("-Value ")
                                if v_start == -1:
                                    v_start = cmd_str.find("-Value\t")
                                
                                if p_match and v_start != -1:
                                    # Estrai tutto dopo -Value
                                    value_start_pos = v_start + 7  # salta "-Value "
                                    # Skip whitespace
                                    while value_start_pos < len(cmd_str) and cmd_str[value_start_pos] in ' \t':
                                        value_start_pos += 1
                                    
                                    # Determina il delimitatore (singola o doppia virgoletta)
                                    if value_start_pos < len(cmd_str):
                                        quote_char = cmd_str[value_start_pos]
                                        if quote_char in ("'", '"'):
                                            # Trova la virgoletta di chiusura (ultima della stringa)
                                            content_start = value_start_pos + 1
                                            # Cerca l'ULTIMA occorrenza della stessa virgoletta
                                            content_end = cmd_str.rfind(quote_char)
                                            if content_end > content_start:
                                                content = cmd_str[content_start:content_end]
                                                # Fix escaped quotes
                                                if quote_char == "'":
                                                    content = content.replace("''", "'")
                                                elif quote_char == '"':
                                                    content = content.replace('\\"', '"')
                                                
                                                # Fix newlines e tabs
                                                content = content.replace('\\n', '\n').replace('\\t', '\t')
                                                
                                                # Usa solo il NOME del file
                                                file_name = Path(p_match.group(1).replace('\\', '/').split('/')[-1]).name
                                                t_file = p_path / file_name
                                                t_file.parent.mkdir(parents=True, exist_ok=True)
                                                mode = 'a' if cmd_str.startswith("Add-Content") else 'w'
                                                with open(t_file, mode, encoding='utf-8') as f:
                                                    f.write(content)
                                                self.root.after(0, lambda m=mode: self._add_message(f"   ✓ File {'acceso' if m=='a' else 'scritto'} (Python Native)", "success"))
                                                intercepted = True
                        except Exception as e:
                            self.root.after(0, lambda err=e: self._add_message(f"   ⚠️ Fallback nativo: {err}", "warning"))
                            
                        if not intercepted:
                            ok, out = self.file_ops.execute_command(cmd)
                            if ok:
                                self.root.after(0, lambda: self._add_message("   ✓ Completato (Shell)", "success"))
                            else:
                                self.root.after(0, lambda e=out: self._add_message(f"   ✗ Errore Shell: {e}", "error"))
                else:
                    self.root.after(0, lambda err=parsed.error: self._add_message(f"❌ Errore parsing: {err}", "error"))
                    self.root.after(0, lambda r=s_resp[:100]: self._add_message(f"Contenuto: {r}...", "warning"))
            
            self.root.after(0, lambda: self._add_message("\n🎉 PROGETTO COMPLETATO", "success"))
            self.mode = 'default'
            
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self._add_message(f"❌ ERRORE WORKFLOW: {e}", "error"))
            
        finally:
            self.is_thinking = False
            self.stop_flag = False
            self.root.after(0, lambda: self.thinking_anim.stop())
            self.root.after(0, lambda: self._set_status("● Connesso", "success"))
            self.root.after(0, lambda: self.send_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

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
        self._add_message("🔄 Nuova sessione iniziata.", "info")

    def _refresh_models(self):
        """Aggiorna la lista dei modelli."""
        if self.ollama and self.connected:
            self._add_message("⟳ Aggiornamento modelli...", "info")
            all_models = self.ollama.list_models()
            # Mostra TUTTI i modelli, non solo shellbot
            self.models = all_models
            shell_models = [m for m in all_models if "shellbot" in m.lower()]
            
            if not shell_models and all_models:
                self._add_message(f"⚠️ Nessun modello shellBot trovato. {len(all_models)} modelli disponibili:", "warning")
            elif shell_models:
                self._add_message(f"✓ {len(shell_models)} modelli shellBot su {len(all_models)} totali:", "success")
            
            self.models_listbox.delete(0, tk.END)
            for i, m in enumerate(all_models, 1):
                is_shell = "shellbot" in m.lower()
                is_active = m == self.ollama.model
                if is_active:
                    prefix = "► "
                elif is_shell:
                    prefix = f"🤖 {i}. "
                else:
                    prefix = f"   {i}. "
                self.models_listbox.insert(tk.END, f"{prefix}{m}")
                self._add_message(f"  {prefix}{m}", "model_list")
            
            if not all_models:
                self._add_message("⚠️ Nessun modello disponibile", "warning")

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
            self._add_message(f"🔄 Modello: {tag} (DOCS/REVERSE)", "info")
        elif not tag:
            self._add_message("⚠️ Nessun modello shellbot DOCS trovato", "warning")
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
            self._add_message(f"📁 Directory: {directory}", "info")

    def _show_about(self):
        """Mostra informazioni."""
        messagebox.showinfo(
            "Informazioni",
            "🦙 Ollama File System Bridge\n\n"
            "Interfaccia grafica per interagire con Ollama LLM\n"
            "e gestire file system locale.\n\n"
            "Modalità:\n"
            "  /fix   - Fix codice esistente\n"
            "  /new   - Crea nuovo progetto\n"
            "  /reverse - Genera documentazione\n\n"
            "© 2026 - MIT License"
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


