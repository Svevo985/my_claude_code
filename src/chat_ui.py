#!/usr/bin/env python3
"""Chat UI testuale per Ollama Bridge usando Textual."""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static, RichLog, Button
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual import work
from pathlib import Path
import json
import sys
import time
import threading
from datetime import datetime

from src.ollama_client import OllamaClient
from src.session_manager import SessionManager

CONFIG_FILE = Path("./config.json")
STATE_FILE = Path("./.ollama_bridge_state.json")


class ChatMessage(Static):
    """Widget per un singolo messaggio chat."""
    
    def __init__(self, content: str, is_user: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.content = content
        self.is_user = is_user
    
    def compose(self) -> ComposeResult:
        prefix = "»" if self.is_user else "AI"
        style_class = "user-message" if self.is_user else "ai-message"
        self.add_class(style_class)
        yield Static(f"[bold]{prefix}[/bold] {self.content}", markup=True)


class ChatApp(App):
    """Applicazione chat TUI per Ollama."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #chat-container {
        height: 1fr;
        margin: 1 2;
    }
    
    #chat-log {
        height: 1fr;
        background: $surface;
        border: solid $primary;
        padding: 1;
        overflow-y: auto;
    }
    
    .user-message {
        background: $primary-darken-2;
        color: $text;
        padding: 1 2;
        margin: 1 0;
        border-left: thick $primary;
    }
    
    .ai-message {
        background: $surface;
        color: $text;
        padding: 1 2;
        margin: 1 0;
        border-left: thick $success;
    }
    
    #input-container {
        height: auto;
        margin: 0 2 1 2;
    }
    
    #chat-input {
        width: 1fr;
        height: 3;
    }
    
    #send-button {
        width: 10;
        margin-left: 1;
    }
    
    #status-bar {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 2;
    }
    
    #model-info {
        dock: right;
        padding: 0 2;
    }
    
    .thinking {
        color: $warning;
    }
    """
    
    BINDINGS = [
        Binding("ctrl+q", "quit", "Esci"),
        Binding("ctrl+l", "clear", "Pulisci"),
        Binding("ctrl+m", "send", "Invia"),
        Binding("escape", "focus_input", "Input"),
    ]
    
    def __init__(self, config: dict, state: dict):
        super().__init__()
        self.config = config
        self.state = state
        self.ollama = None
        self.session_manager = SessionManager()
        self.session = None
        self.is_thinking = False
        self._init_ollama()
    
    def _init_ollama(self):
        """Inizializza il client Ollama."""
        try:
            model = self.state.get('model') or self.config.get('ollama', {}).get('model', 'llama3.2')
            base_url = self.config.get('ollama', {}).get('base_url', 'http://localhost:11434')
            timeout = self.config.get('ollama', {}).get('timeout', 1800)
            
            ollama_options = {
                "temperature": 0.2,
                "top_p": 0.9,
                "top_k": 40,
                "num_ctx": 16384,
                "num_predict": 4096,
            }
            
            self.ollama = OllamaClient(base_url, model, timeout, options=ollama_options)
            self.session = self.session_manager.create_session()
        except Exception as e:
            self.ollama = None
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Container(id="chat-container"):
            yield RichLog(id="chat-log", highlight=True, markup=True)
        
        with Horizontal(id="input-container"):
            yield Input(placeholder="Scrivi il tuo messaggio... (Ctrl+M per inviare)", id="chat-input")
            yield Button("Invia", id="send-button", variant="primary")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Chiamato quando l'app è montata."""
        self.chat_log = self.query_one("#chat-log", RichLog)
        self.chat_input = self.query_one("#chat-input", Input)
        self.status_bar = self.query_one("#status-bar", Static) if self.query("#status-bar") else None
        
        # Messaggio di benvenuto
        self._add_message("Benvenuto! Chat con Ollama.\nModello: " + (self.ollama.model if self.ollama else "NON DISPONIBILE"), is_user=False)
        
        if not self.ollama:
            self._add_message("⚠️ Ollama non è disponibile. Assicurati che 'ollama serve' sia in esecuzione.", is_user=False)
        
        self.chat_input.focus()
    
    def _add_message(self, content: str, is_user: bool = False):
        """Aggiunge un messaggio alla chat."""
        style = "bold green" if is_user else "bold blue"
        prefix = "» TU" if is_user else "AI"
        self.chat_log.write(f"[{style}]{prefix}:[/{style}] {content}")
    
    def _add_thinking(self):
        """Mostra indicatore di 'pensando'."""
        self.chat_log.write("[yellow]AI sta pensando...[/yellow]")
        self.is_thinking = True
    
    def _remove_thinking(self):
        """Rimuove indicatore di 'pensando'."""
        self.is_thinking = False
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Gestisce il click del pulsante Invia."""
        if event.button.id == "send-button":
            self._send_message()
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Gestisce l'invio tramite Enter."""
        if event.input.id == "chat-input":
            self._send_message()
    
    def action_send(self) -> None:
        """Azione per inviare messaggio (Ctrl+M)."""
        self._send_message()
    
    def action_clear(self) -> None:
        """Pulisce la chat."""
        self.chat_log.clear()
        self.session = self.session_manager.create_session()
        self._add_message("Chat pulita. Nuova sessione iniziata.", is_user=False)
    
    def action_focus_input(self) -> None:
        """Porta il focus sull'input."""
        self.chat_input.focus()
    
    def _send_message(self):
        """Invia il messaggio corrente."""
        if self.is_thinking:
            return
        
        message = self.chat_input.value.strip()
        if not message:
            return
        
        if not self.ollama:
            self._add_message("⚠️ Ollama non è disponibile.", is_user=False)
            return
        
        # Aggiungi messaggio utente
        self._add_message(message, is_user=True)
        self.chat_input.value = ""
        
        # Avvia la chiamata LLM in background
        self._process_llm_response(message)
    
    @work(exclusive=True)
    def _process_llm_response(self, user_message: str):
        """Elabora la risposta LLM in un worker thread."""
        self.call_from_thread(self._add_thinking)
        
        try:
            # Aggiungi alla sessione
            self.session.add_message("user", user_message)
            
            # Chiama Ollama
            response = ""
            for chunk in self.ollama.chat(
                self.session.to_ollama_messages(),
                stream=True
            ):
                response += chunk
                # Aggiorna in tempo reale (opzionale)
            
            self.call_from_thread(self._remove_thinking)
            
            # Aggiungi risposta AI
            if response:
                self.session.add_message("assistant", response)
                self.call_from_thread(self._add_message, response, False)
            else:
                self.call_from_thread(self._add_message, "⚠️ Nessuna risposta ricevuta.", False)
                
        except Exception as e:
            self.call_from_thread(self._remove_thinking)
            self.call_from_thread(self._add_message, f"⚠️ Errore: {str(e)}", False)


def load_config() -> dict:
    """Carica la configurazione."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "llama3.2",
            "timeout": 1800
        }
    }


def load_state() -> dict:
    """Carica lo stato."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def main():
    """Avvia l'applicazione chat."""
    config = load_config()
    state = load_state()
    
    app = ChatApp(config, state)
    app.run()


if __name__ == "__main__":
    main()
