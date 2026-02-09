"""
In-memory session manager for Professor Tux.
Replace with Redis / DB for production.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def create(self, mode: str, topic: Optional[str] = None,
               course_filter: Optional[str] = None, use_lectures: bool = True) -> dict:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "mode": mode,
            "topic": topic,
            "course_filter": course_filter,
            "use_lectures": use_lectures,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[dict]:
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, role: str, content: str):
        if session_id in self._sessions:
            self._sessions[session_id]["history"].append(
                {"role": role, "content": content}
            )

    def update_mode(self, session_id: str, mode: str):
        if session_id in self._sessions:
            self._sessions[session_id]["mode"] = mode

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None
