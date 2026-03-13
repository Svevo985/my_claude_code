"""
Operazioni sul file system con layer di sicurezza.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional


class FileOperations:
    """Gestisce le operazioni sul file system con controlli di sicurezza."""
    
    DESTRUCTIVE_COMMANDS = ['rm', 'rmdir', 'mv', 'cp', 'del', 'deltree']
    
    def __init__(
        self,
        working_directory: str = ".",
        allowed_directories: Optional[list[str]] = None
    ):
        self.working_directory = Path(working_directory).resolve()
        self.allowed_directories = (
            [Path(d).resolve() for d in allowed_directories]
            if allowed_directories
            else [self.working_directory]
        )
    
    def execute_command(self, command: str) -> tuple[bool, str]:
        """
        Esegue un comando shell e restituisce (successo, output).
        
        Args:
            command: Il comando da eseguire
        
        Returns:
            Tuple di (successo, output/error message)
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.working_directory,
                timeout=30
            )
            
            output = result.stdout
            if result.stderr:
                output += result.stderr
            
            return (result.returncode == 0, output.strip())
        
        except subprocess.TimeoutExpired:
            return (False, "Timeout: il comando ha impiegato troppo tempo")
        except Exception as e:
            return (False, f"Errore: {str(e)}")
    
    def is_destructive(self, command: str) -> bool:
        """Controlla se un comando è potenzialmente distruttivo."""
        cmd_lower = command.lower().strip()
        return any(
            cmd_lower.startswith(dc) or f" {dc} " in cmd_lower
            for dc in self.DESTRUCTIVE_COMMANDS
        )
    
    def is_path_allowed(self, path: str) -> bool:
        """Controlla se un percorso è nelle directory consentite."""
        try:
            resolved = Path(path).resolve()
            return any(
                str(resolved).startswith(str(allowed))
                for allowed in self.allowed_directories
            )
        except Exception:
            return False
    
    def read_file(self, filepath: str) -> tuple[bool, str]:
        """
        Legge il contenuto di un file.
        
        Args:
            filepath: Percorso del file
        
        Returns:
            Tuple di (successo, contenuto/error message)
        """
        try:
            full_path = self.working_directory / filepath
            if not self.is_path_allowed(str(full_path)):
                return (False, f"Accesso negato: {filepath} non è nelle directory consentite")
            
            with open(full_path, 'r', encoding='utf-8') as f:
                return (True, f.read())
        except FileNotFoundError:
            return (False, f"File non trovato: {filepath}")
        except PermissionError:
            return (False, f"Permesso negato: {filepath}")
        except Exception as e:
            return (False, f"Errore lettura: {str(e)}")
    
    def write_file(self, filepath: str, content: str) -> tuple[bool, str]:
        """
        Scrive contenuto in un file.
        
        Args:
            filepath: Percorso del file
            content: Contenuto da scrivere
        
        Returns:
            Tuple di (successo, messaggio)
        """
        try:
            full_path = self.working_directory / filepath
            if not self.is_path_allowed(str(full_path)):
                return (False, f"Accesso negato: {filepath} non è nelle directory consentite")
            
            # Crea directory se non esistono
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return (True, f"File scritto: {filepath}")
        except PermissionError:
            return (False, f"Permesso negato: {filepath}")
        except Exception as e:
            return (False, f"Errore scrittura: {str(e)}")
    
    def append_file(self, filepath: str, content: str) -> tuple[bool, str]:
        """Aggiunge contenuto a un file esistente."""
        try:
            full_path = self.working_directory / filepath
            if not self.is_path_allowed(str(full_path)):
                return (False, f"Accesso negato: {filepath}")
            
            with open(full_path, 'a', encoding='utf-8') as f:
                f.write(content)
            
            return (True, f"Contenuto aggiunto a: {filepath}")
        except Exception as e:
            return (False, f"Errore append: {str(e)}")
    
    def list_directory(self, path: str = ".") -> tuple[bool, str]:
        """Lista il contenuto di una directory."""
        try:
            full_path = self.working_directory / path
            if not self.is_path_allowed(str(full_path)):
                return (False, f"Accesso negato: {path}")
            
            items = []
            for item in sorted(full_path.iterdir()):
                prefix = "D" if item.is_dir() else "F"
                items.append(f"{prefix} {item.name}")
            
            return (True, "\n".join(items))
        except Exception as e:
            return (False, f"Errore lista: {str(e)}")
