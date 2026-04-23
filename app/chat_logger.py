"""Append-only JSONL logger for chat interactions."""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger("professor_tux.chatlog")

LOG_DIR = os.getenv("CHAT_LOG_DIR", "./data/logs")
LOG_FILE = "chat_logs.jsonl"


@dataclass
class ChatLogEntry:
    timestamp: str
    ip: str
    session_id: str
    mode: str
    topic: Optional[str]
    question: str
    system_prompt: str
    response: str
    sources_used: list[str]
    duration_ms: int
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ChatLogger:
    """Append-only JSONL chat logger."""

    def __init__(self, log_dir: str | Path | None = None):
        self._log_dir = Path(log_dir) if log_dir else Path(LOG_DIR)
        self._log_path = self._log_dir / LOG_FILE

    def initialize(self):
        os.makedirs(self._log_dir, exist_ok=True)
        if not self._log_path.exists():
            self._log_path.touch()
        logger.info("Chat logger ready: %s", self._log_path)

    def log(self, entry: ChatLogEntry):
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            logger.info(
                "CHAT ip=%s session=%s mode=%s duration=%dms question=%r",
                entry.ip, entry.session_id[:8], entry.mode,
                entry.duration_ms, entry.question[:80],
            )
        except Exception as e:
            logger.error("Failed to write chat log: %s", e)

    def get_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        session_filter: Optional[str] = None,
        ip_filter: Optional[str] = None,
    ) -> dict:
        """Read logs from file. Returns {total, logs[]}."""
        if not self._log_path.exists():
            return {"total": 0, "logs": []}

        all_entries = []
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if session_filter and entry.get("session_id") != session_filter:
                        continue
                    if ip_filter and entry.get("ip") != ip_filter:
                        continue
                    all_entries.append(entry)
                except json.JSONDecodeError:
                    continue

        all_entries.reverse()
        total = len(all_entries)
        page = all_entries[offset : offset + limit]
        return {"total": total, "logs": page}

    def clear(self) -> int:
        """Clear all logs. Returns count of entries deleted."""
        if not self._log_path.exists():
            return 0
        count = sum(1 for line in open(self._log_path) if line.strip())
        self._log_path.write_text("")
        return count
