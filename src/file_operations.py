"""
Operazioni sul file system con layer di sicurezza e adattamento shell.
"""

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _is_wsl() -> bool:
    """Rileva se il processo gira dentro WSL."""
    try:
        return "microsoft" in platform.release().lower() or "microsoft" in platform.version().lower()
    except Exception:
        return False


def _to_wsl_path(path: Path) -> str:
    """Converte un Path di Windows in formato /mnt/<drive>/... per WSL."""
    if path.drive:
        drive = path.drive.replace(":", "").lower()
        rel = path.relative_to(path.anchor).as_posix()
        return f"/mnt/{drive}/{rel}"
    return path.as_posix()


class FileOperations:
    """Gestisce le operazioni sul file system con controlli di sicurezza."""
    
    DESTRUCTIVE_COMMANDS = ['rm', 'rmdir', 'mv', 'cp', 'del', 'deltree']
    
    def __init__(
        self,
        working_directory: str = ".",
        allowed_directories: Optional[list[str]] = None,
        shell_override: Optional[str] = None,
        timeout: int = 30
    ):
        self.working_directory = Path(working_directory).resolve()
        self.allowed_directories = (
            [Path(d).resolve() for d in allowed_directories]
            if allowed_directories
            else [self.working_directory]
        )
        self.timeout = timeout
        self.shell_info = self._detect_shell_environment(shell_override)
    
    def _detect_shell_environment(self, shell_override: Optional[str]) -> dict:
        system = platform.system()
        is_wsl_env = _is_wsl()
        desired = shell_override.lower() if shell_override else None

        def info(runner: str, description: str, executable: Optional[str] = None, wsl_workdir: Optional[str] = None) -> dict:
            return {
                "system": system,
                "runner": runner,
                "description": description,
                "executable": executable,
                "wsl_workdir": wsl_workdir,
            }

        # Precedenza personalizzata
        if desired in {"powershell", "pwsh"}:
            return info("powershell", "PowerShell", executable=shutil.which("powershell") or shutil.which("pwsh"))
        if desired in {"wsl", "bash"}:
            if desired == "wsl" and shutil.which("wsl"):
                return info("wsl", "WSL bash", wsl_workdir=_to_wsl_path(self.working_directory))
            if desired == "bash" and shutil.which("bash"):
                return info("bash", "Bash (forzato)")

        if system == "Windows" and not is_wsl_env:
            if shutil.which("wsl"):
                return info("wsl", "Windows + WSL (bash)", wsl_workdir=_to_wsl_path(self.working_directory))
            if shutil.which("bash"):
                return info("bash", "Windows + Git Bash")
            ps_path = shutil.which("powershell") or shutil.which("pwsh")
            if ps_path:
                return info("powershell", "Windows PowerShell", executable=ps_path)
            return info("cmd", "Windows cmd.exe")

        # Linux / macOS / WSL
        bash_path = shutil.which("bash")
        return info("posix", "Posix shell", executable=bash_path)

    def execute_command(self, command: str, timeout: Optional[int] = None) -> tuple[bool, str]:
        """
        Esegue un comando shell adattandosi all'ambiente rilevato.
        """
        runner = self.shell_info.get("runner")
        timeout = timeout or self.timeout

        try:
            if runner == "wsl":
                workdir = self.shell_info.get("wsl_workdir") or _to_wsl_path(self.working_directory)
                wrapped = f"cd \"{workdir}\" && {command}"
                result = subprocess.run(
                    ["wsl", "bash", "-lc", wrapped],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            elif runner == "bash":
                workdir = self.format_path_for_shell(self.working_directory)
                wrapped = f"cd \"{workdir}\" && {command}"
                result = subprocess.run(
                    ["bash", "-lc", wrapped],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            elif runner == "powershell":
                exe = self.shell_info.get("executable") or "powershell"
                workdir = str(self.working_directory).replace("'", "''")
                ps_cmd = f"Set-Location -LiteralPath '{workdir}'; {command}"
                result = subprocess.run(
                    [exe, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            elif runner == "posix":
                result = subprocess.run(
                    command,
                    shell=True,
                    executable=self.shell_info.get("executable"),
                    capture_output=True,
                    text=True,
                    cwd=self.working_directory,
                    timeout=timeout,
                )
            else:  # cmd fallback
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=self.working_directory,
                    timeout=timeout,
                )

            output = result.stdout
            if result.stderr:
                output += result.stderr
            return (result.returncode == 0, output.strip())

        except subprocess.TimeoutExpired:
            return (False, "Timeout: il comando ha impiegato troppo tempo")
        except Exception as e:
            return (False, f"Errore: {str(e)}")

    def format_path_for_shell(self, path: Path) -> str:
        """Restituisce un path compatibile con la shell corrente."""
        runner = self.shell_info.get("runner")
        if runner == "wsl":
            return _to_wsl_path(path)
        if runner in {"bash", "posix"}:
            return path.as_posix()
        return str(path)

    def environment_info(self) -> dict:
        """Expose info sull'ambiente per logging/UI."""
        return self.shell_info | {
            "working_directory": str(self.working_directory)
        }
    
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
