"""
LLM backend adapters for Professor Tux.
======================================
Uses a single Ollama-compatible chat endpoint, optionally authenticated.
"""

from __future__ import annotations

import os
import json
import logging
import shutil
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlparse

import requests

logger = logging.getLogger("professor_tux.backends")

REQUEST_TIMEOUT = float(os.getenv("MODEL_REQUEST_TIMEOUT", "60"))


def _normalize_ollama_base_url(value: str, default: str) -> str:
    base_url = (value or default).strip().rstrip("/")
    if base_url.endswith("/api"):
        base_url = base_url[:-4]
    return base_url


def _format_bytes(size_bytes: int | float | None) -> str:
    if not isinstance(size_bytes, (int, float)) or size_bytes <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    return f"{value:.1f} {unit}"


def _normalize_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content or "")


class BackendError(RuntimeError):
    """Raised when an upstream model backend call fails."""


class BackendToolsUnsupported(BackendError):
    """Raised when the active model rejects a request because it cannot use tools."""


def _read_error_payload(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except (ValueError, requests.RequestException):
        pass
    try:
        return (response.text or "").strip()
    except Exception:
        return ""


@dataclass(frozen=True)
class ModelDescriptor:
    provider: str
    label: str
    model: str
    description: str = ""

    @property
    def selection(self) -> str:
        return f"{self.provider}::{self.model}"


class ModelBackend(ABC):
    provider_id: str
    provider_label: str

    @property
    @abstractmethod
    def default_model(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[ModelDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def validate_model(self, model: str):
        raise NotImplementedError

    @abstractmethod
    def is_ready(self, model: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        tools: list[dict] | None = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        tools: list[dict] | None = None,
    ) -> Iterable[dict]:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> Iterable[str]:
        raise NotImplementedError


class OllamaBackend(ModelBackend):
    def __init__(
        self,
        *,
        provider_id: str = "ollama",
        provider_label: str = "Ollama Local",
        base_url: str | None = None,
        default_model: str | None = None,
        default_description: str = "Ollama",
        configured_message: str = "Configured default · Ollama not verified",
        model_options: list[str] | None = None,
    ):
        self.provider_id = provider_id
        self.provider_label = provider_label
        self._base_url = _normalize_ollama_base_url(
            base_url or os.getenv("OLLAMA_BASE_URL", ""),
            "http://127.0.0.1:11434",
        )
        self._default_model = (
            default_model
            if default_model is not None
            else os.getenv("OLLAMA_MODEL", "qwen3.5:4b").strip()
        )
        self._keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "5m").strip() or "5m"
        self._default_description = default_description
        self._configured_message = configured_message
        self._model_options = model_options or []
        self._server_start_lock = threading.Lock()

    @property
    def default_model(self) -> str:
        return self._default_model

    def is_configured(self) -> bool:
        return bool(self._base_url)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _raise_http_error(self, response: requests.Response, context: str):
        body = _read_error_payload(response)
        if response.status_code == 400 and "does not support tools" in body.lower():
            raise BackendToolsUnsupported(body or "Model does not support tools")
        detail = f" — {body}" if body else ""
        raise BackendError(
            f"{self.provider_label} {context} failed: HTTP {response.status_code}{detail}"
        )

    def is_local_endpoint(self) -> bool:
        parsed = urlparse(self._base_url)
        host = (parsed.hostname or "").strip().lower()
        return host in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}

    def _get(self, path: str, timeout: float = REQUEST_TIMEOUT) -> requests.Response:
        try:
            response = requests.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise BackendError(f"{self.provider_label} is unreachable at {self._base_url}: {exc}") from exc
        return response

    def _post(
        self,
        path: str,
        *,
        payload: dict,
        stream: bool = False,
        timeout: float = REQUEST_TIMEOUT,
    ) -> requests.Response:
        try:
            response = requests.post(
                f"{self._base_url}{path}",
                headers=self._headers(),
                json=payload,
                timeout=timeout,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise BackendError(f"{self.provider_label} request failed: {exc}") from exc
        return response

    def _remote_model_names(self) -> list[str]:
        if self.provider_id == "ollama":
            self.ensure_server_running()
        response = self._get("/api/tags")
        response.raise_for_status()
        data = response.json()
        names = []
        for item in data.get("models", []):
            name = item.get("name")
            if name:
                names.append(name)
        return names

    def list_models(self) -> list[ModelDescriptor]:
        try:
            if self.provider_id == "ollama":
                self.ensure_server_running()
            response = self._get("/api/tags")
            response.raise_for_status()
            data = response.json()
        except (BackendError, requests.RequestException, ValueError) as exc:
            logger.warning("Failed to query %s models: %s", self.provider_label, exc)
            names = self._model_options
            if names:
                return [
                    ModelDescriptor(
                        provider=self.provider_id,
                        model=name,
                        label=name,
                        description=f"{self._default_description} · configured list",
                    )
                    for name in names
                ]
            if self._default_model:
                return [
                    ModelDescriptor(
                        provider=self.provider_id,
                        model=self._default_model,
                        label=self._default_model,
                        description=self._configured_message,
                    )
                ]
            return []

        models: list[ModelDescriptor] = []
        for item in data.get("models", []):
            name = item.get("name")
            if not name:
                continue
            details = [self._default_description]
            size = _format_bytes(item.get("size"))
            if size:
                details.insert(0, size)
            models.append(
                ModelDescriptor(
                    provider=self.provider_id,
                    model=name,
                    label=name,
                    description=" · ".join(details),
                )
            )
        models.sort(key=lambda model: model.label.lower())
        return models

    def validate_model(self, model: str):
        if not model or not model.strip():
            raise ValueError("Model name is required")

    def is_reachable(self, timeout: float = 3.0) -> bool:
        try:
            response = self._get("/api/tags", timeout=timeout)
        except BackendError:
            if self._maybe_switch_to_docker_host(timeout=timeout):
                return True
            return False
        return response.status_code == 200

    def _manages_local_server(self) -> bool:
        if self.provider_id != "ollama":
            return False
        parsed = urlparse(self._base_url)
        host = (parsed.hostname or "").strip().lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _maybe_switch_to_docker_host(self, timeout: float = 3.0) -> bool:
        if self.provider_id != "ollama":
            return False
        if not os.path.exists("/.dockerenv"):
            return False

        parsed = urlparse(self._base_url)
        host = (parsed.hostname or "").strip().lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False

        fallback_base = f"{parsed.scheme or 'http'}://host.docker.internal:{parsed.port or 11434}"
        try:
            response = requests.get(
                f"{fallback_base}/api/tags",
                headers=self._headers(),
                timeout=timeout,
            )
        except requests.RequestException:
            return False
        if response.status_code != 200:
            return False

        logger.info(
            "Local Ollama at %s was unreachable inside Docker; using %s instead.",
            self._base_url,
            fallback_base,
        )
        self._base_url = fallback_base
        return True

    def ensure_server_running(self, startup_timeout: float = 20.0) -> bool:
        if not self._manages_local_server():
            return False
        if self.is_reachable():
            return False

        with self._server_start_lock:
            if self.is_reachable():
                return False

            executable = shutil.which("ollama")
            if not executable:
                raise BackendError("Ollama CLI is not installed. Install Ollama to use local models.")

            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                kwargs["start_new_session"] = True

            logger.info("Starting local Ollama server via '%s serve'", executable)
            subprocess.Popen([executable, "serve"], **kwargs)

            deadline = time.time() + startup_timeout
            while time.time() < deadline:
                if self.is_reachable(timeout=2.0):
                    logger.info("Local Ollama server is ready at %s", self._base_url)
                    return True
                time.sleep(0.5)

        raise BackendError(
            f"Ollama is installed but the local server did not become ready at {self._base_url} within {startup_timeout:.0f}s."
        )

    def has_model(self, model: str) -> bool:
        if not model:
            return False
        return model in self._remote_model_names()

    def pull_model(
        self,
        model: str,
        progress_callback: Callable[[dict], None] | None = None,
    ):
        if not model:
            raise ValueError("Model name is required")
        if self.provider_id == "ollama":
            self.ensure_server_running()

        payload = {"model": model, "stream": True}
        with self._post("/api/pull", payload=payload, stream=True, timeout=None) as response:
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise BackendError(f"{self.provider_label} pull failed: {exc}") from exc

            final_status = ""
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    raise BackendError(str(data["error"]))
                final_status = data.get("status", final_status)
                if progress_callback is not None:
                    progress_callback(data)

            if final_status and "success" not in final_status.lower():
                logger.info("%s pull finished with status: %s", self.provider_label, final_status)

    def is_ready(self, model: str) -> bool:
        if not model:
            return False
        try:
            if self.provider_id == "ollama":
                self.ensure_server_running()
            if self._model_options:
                return model in self._model_options
            response = self._get("/api/tags", timeout=10)
            if response.status_code != 200:
                return False
            data = response.json()
        except (BackendError, ValueError, requests.RequestException):
            return False
        return any(item.get("name") == model for item in data.get("models", []))

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        tools: list[dict] | None = None,
    ) -> dict:
        if self.provider_id == "ollama":
            self.ensure_server_running()
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self._keep_alive,
            "tools": tools or [],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
            },
        }
        response = self._post("/api/chat", payload=payload)
        if not response.ok:
            self._raise_http_error(response, "chat")
        try:
            data = response.json()
        except ValueError as exc:
            raise BackendError(f"Invalid {self.provider_label} response: {exc}") from exc
        if data.get("error"):
            raise BackendError(str(data["error"]))
        return data

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        tools: list[dict] | None = None,
    ) -> Iterable[dict]:
        if self.provider_id == "ollama":
            self.ensure_server_running()
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,
            "keep_alive": self._keep_alive,
            "tools": tools or [],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
            },
        }
        with self._post("/api/chat", payload=payload, stream=True) as response:
            if not response.ok:
                self._raise_http_error(response, "stream")
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    raise BackendError(str(data["error"]))
                message = data.get("message") or {}
                if message:
                    message["content"] = _normalize_content(message.get("content"))
                yield data

    def generate(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        data = self.chat(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        message = data.get("message") or {}
        return _normalize_content(message.get("content"))

    def generate_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> Iterable[str]:
        for data in self.chat_stream(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            message = data.get("message") or {}
            token = _normalize_content(message.get("content"))
            if token:
                yield token
