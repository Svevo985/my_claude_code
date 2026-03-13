"""
Gestore delle sessioni chat con contesto e storico.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Message:
    """Un messaggio nella chat."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    command_executed: Optional[str] = None
    command_output: Optional[str] = None


@dataclass
class Session:
    """Una sessione di chat completa."""
    id: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    working_directory: str = "."
    
    def add_message(
        self,
        role: str,
        content: str,
        command_executed: Optional[str] = None,
        command_output: Optional[str] = None
    ):
        """Aggiunge un messaggio alla sessione."""
        self.messages.append(Message(
            role=role,
            content=content,
            command_executed=command_executed,
            command_output=command_output
        ))
    
    def to_ollama_messages(self) -> list[dict]:
        """
        Converte la sessione nel formato per Ollama.
        
        Returns:
            Lista di messaggi per l'API Ollama
        """
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.messages
        ]
    
    def get_context_summary(self, max_messages: int = 10) -> str:
        """
        Ottiene un riassunto del contesto recente.
        
        Args:
            max_messages: Numero massimo di messaggi da includere
        
        Returns:
            Stringa con il riassunto del contesto
        """
        recent = self.messages[-max_messages:]
        summary_parts = []
        
        for msg in recent:
            if msg.role == "user":
                summary_parts.append(f"User: {msg.content[:100]}...")
            elif msg.role == "assistant":
                if msg.command_executed:
                    summary_parts.append(f"AI: executed '{msg.command_executed[:50]}...'")
                else:
                    summary_parts.append(f"AI: {msg.content[:100]}...")
        
        return "\n".join(summary_parts)


class SessionManager:
    """Gestisce multiple sessioni chat."""
    
    def __init__(self, history_dir: str = "./sessions"):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.current_session: Optional[Session] = None
        self._session_counter = 0
    
    def create_session(self, working_directory: str = ".") -> Session:
        """
        Crea una nuova sessione.
        
        Args:
            working_directory: Directory di lavoro per la sessione
        
        Returns:
            La nuova sessione creata
        """
        self._session_counter += 1
        session_id = f"session_{self._session_counter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.current_session = Session(
            id=session_id,
            working_directory=working_directory
        )
        
        return self.current_session
    
    def get_current_session(self) -> Optional[Session]:
        """Restituisce la sessione corrente."""
        return self.current_session
    
    def save_session(self, session: Optional[Session] = None) -> Path:
        """
        Salva una sessione su file.
        
        Args:
            session: La sessione da salvare (default: current_session)
        
        Returns:
            Percorso del file salvato
        """
        session = session or self.current_session
        if not session:
            raise ValueError("Nessuna sessione da salvare")
        
        filepath = self.history_dir / f"{session.id}.json"
        
        data = {
            "id": session.id,
            "created_at": session.created_at,
            "working_directory": session.working_directory,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    "command_executed": msg.command_executed,
                    "command_output": msg.command_output
                }
                for msg in session.messages
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return filepath
    
    def load_session(self, session_id: str) -> Session:
        """
        Carica una sessione da file.
        
        Args:
            session_id: ID della sessione da caricare
        
        Returns:
            La sessione caricata
        """
        filepath = self.history_dir / f"{session_id}.json"
        
        if not filepath.exists():
            raise FileNotFoundError(f"Sessione non trovata: {session_id}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        session = Session(
            id=data["id"],
            created_at=data["created_at"],
            working_directory=data["working_directory"]
        )
        
        for msg_data in data["messages"]:
            session.messages.append(Message(
                role=msg_data["role"],
                content=msg_data["content"],
                timestamp=msg_data["timestamp"],
                command_executed=msg_data.get("command_executed"),
                command_output=msg_data.get("command_output")
            ))
        
        self.current_session = session
        return session
    
    def list_sessions(self) -> list[str]:
        """Restituisce la lista delle sessioni salvate."""
        return [
            f.stem for f in self.history_dir.glob("session_*.json")
        ]
