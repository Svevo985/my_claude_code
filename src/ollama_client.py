"""Client per comunicare con l'API di Ollama."""

import json
import logging
import subprocess
import time
import platform
import requests
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client per l'API di Ollama."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3-reap",
        timeout: int = 1800,
        options: Optional[dict] = None
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout
        self.options = options or {}
        self._session = requests.Session()

    def chat(
        self,
        messages: list[dict],
        stream: bool = True
    ) -> "dict | Generator[str, None, None]":
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream
        }
        if self.options:
            payload["options"] = self.options

        logger.debug(f"OllamaClient chat request payload: {json.dumps(payload, ensure_ascii=False)[:1000]}")

        if stream:
            return self._stream_chat(url, payload)

        response = self._session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        resp_json = response.json()
        logger.debug(f"OllamaClient chat response: {json.dumps(resp_json, ensure_ascii=False)[:1000]}")
        return resp_json

    def _stream_chat(self, url: str, payload: dict) -> Generator[str, None, None]:
        response = self._session.post(url, json=payload, timeout=self.timeout, stream=True)
        response.raise_for_status()
        logger.debug("OllamaClient chat streaming started")
        char_count = 0
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if "message" in data and "content" in data["message"]:
                    content = data["message"]["content"]
                    char_count += len(content)
                    yield content
        logger.debug(f"OllamaClient chat streaming finished, total characters received: {char_count}")

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        stream: bool = False
    ) -> "dict | Generator[str, None, None]":
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream
        }
        if self.options:
            payload["options"] = self.options
        if system:
            payload["system"] = system

        logger.debug(f"OllamaClient generate request payload: {json.dumps(payload, ensure_ascii=False)[:1000]}")

        if stream:
            return self._stream_generate(url, payload)

        response = self._session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        resp_json = response.json()
        logger.debug(f"OllamaClient generate response: {json.dumps(resp_json, ensure_ascii=False)[:1000]}")
        return resp_json

    def _stream_generate(self, url: str, payload: dict) -> Generator[str, None, None]:
        response = self._session.post(url, json=payload, timeout=self.timeout, stream=True)
        response.raise_for_status()
        logger.debug("OllamaClient generate streaming started")
        char_count = 0
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if "response" in data:
                    content = data["response"]
                    char_count += len(content)
                    yield content
        logger.debug(f"OllamaClient generate streaming finished, total characters received: {char_count}")

    def list_models(self) -> list[str]:
        url = f"{self.base_url}/api/tags"
        response = self._session.get(url, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return [model["name"] for model in data.get("models", [])]

    def is_available(self) -> bool:
        try:
            self._session.get(f"{self.base_url}/api/tags", timeout=5)
            return True
        except requests.exceptions.RequestException:
            return False

    def ensure_available(self) -> tuple[bool, str]:
        """
        Controlla se Ollama è disponibile, altrimenti tenta di riavviarlo.
        Ritorna (successo, messaggio).
        """
        # Prima prova: controlla se è già disponibile
        if self.is_available():
            return True, "Ollama è già disponibile"

        logger.info("Ollama non disponibile, tentativo di restart...")

        # Tenta di killare eventuali processi Ollama bloccati
        self._kill_ollama()

        # Avvia Ollama
        success, msg = self._start_ollama()
        if not success:
            return False, msg

        # Attendi che Ollama sia pronto (max 30 secondi)
        for i in range(30):
            time.sleep(1)
            if self.is_available():
                return True, "Ollama avviato con successo"

        return False, "Timeout: Ollama non risponde dopo 30 secondi"

    def _kill_ollama(self):
        """Killa eventuali processi Ollama bloccati."""
        system = platform.system()
        try:
            if system == "Windows":
                # Su Windows, killa il processo ollama.exe
                subprocess.run(
                    ["taskkill", "/F", "/IM", "ollama.exe"],
                    capture_output=True,
                    timeout=10
                )
                time.sleep(2)  # Attendi che il processo termini
            else:
                # Su Linux/Mac, killa il processo ollama
                subprocess.run(
                    ["pkill", "-f", "ollama"],
                    capture_output=True,
                    timeout=10
                )
                time.sleep(2)
            logger.info("Processi Ollama terminati")
        except subprocess.TimeoutExpired:
            logger.warning("Timeout nel kill di Ollama")
        except FileNotFoundError:
            logger.debug("Nessun processo Ollama da terminare")
        except Exception as e:
            logger.debug(f"Errore nel kill di Ollama: {e}")

    def _start_ollama(self) -> tuple[bool, str]:
        """Avvia Ollama in background."""
        system = platform.system()
        try:
            if system == "Windows":
                # Su Windows, avvia Ollama come processo separato
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Su Linux/Mac, avvia Ollama in background
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            logger.info("Ollama avviato")
            return True, "Ollama avviato"
        except FileNotFoundError:
            return False, "Ollama non trovato. Installa Ollama prima."
        except Exception as e:
            return False, f"Errore nell'avvio di Ollama: {e}"

    def check_model_exists(self, model_name: str) -> bool:
        """Controlla se un modello esiste in Ollama."""
        try:
            models = self.list_models()
            # Controlla sia il nome esatto che le varianti
            for m in models:
                if m == model_name or m.startswith(model_name.split(":")[0]):
                    return True
            return False
        except Exception:
            return False
