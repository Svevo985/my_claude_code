"""Client per comunicare con l'API di Ollama."""

import json
import requests
from typing import Generator, Optional


class OllamaClient:
    """Client per l'API di Ollama."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3-coder-30b-reap",
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

        if stream:
            return self._stream_chat(url, payload)

        response = self._session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _stream_chat(self, url: str, payload: dict) -> Generator[str, None, None]:
        response = self._session.post(url, json=payload, timeout=self.timeout, stream=True)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if "message" in data and "content" in data["message"]:
                    yield data["message"]["content"]

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

        if stream:
            return self._stream_generate(url, payload)

        response = self._session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _stream_generate(self, url: str, payload: dict) -> Generator[str, None, None]:
        response = self._session.post(url, json=payload, timeout=self.timeout, stream=True)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if "response" in data:
                    yield data["response"]

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