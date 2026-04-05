from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger("OpsSentry.SessionManager")

class SessionEntry(BaseModel):
    id: str
    uid: str
    did: str
    history_path: Path
    created_at: str
    updated_at: str

class SessionManager:
    """
    会话管理器。
    负责单体对话和群聊会话的生命周期管理及历史记录持久化。
    存储路径: ~/.accio/sessions/<id>/history.jsonl
    """

    def __init__(self, accio_home: Path) -> None:
        self.accio_home = accio_home
        self.sessions_dir = accio_home / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def get_or_create_session(self, uid: str, did: str, session_id: Optional[str] = None) -> SessionEntry:
        if not session_id:
            session_id = f"sess_{uid}_{did}_{int(datetime.now().timestamp())}"
        
        session_path = self.sessions_dir / session_id
        session_path.mkdir(parents=True, exist_ok=True)
        
        history_path = session_path / "history.jsonl"
        if not history_path.exists():
            history_path.touch()

        return SessionEntry(
            id=session_id,
            uid=uid,
            did=did,
            history_path=history_path,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )

    def append_history(self, session_id: str, message: Dict[str, Any]) -> None:
        session_path = self.sessions_dir / session_id
        history_path = session_path / "history.jsonl"
        
        if not history_path.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.touch()

        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def load_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        session_path = self.sessions_dir / session_id
        history_path = session_path / "history.jsonl"
        
        if not history_path.exists():
            return []

        history = []
        with open(history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return history

    def list_user_sessions(self, uid: str) -> List[SessionEntry]:
        # TODO: Implement session index if needed for scalability
        results = []
        for session_dir in self.sessions_dir.iterdir():
            if session_dir.is_dir() and session_dir.name.startswith(f"sess_{uid}_"):
                # In a real impl, we'd read a metadata file
                results.append(SessionEntry(
                    id=session_dir.name,
                    uid=uid,
                    did=session_dir.name.split("_")[2],
                    history_path=session_dir / "history.jsonl",
                    created_at="", # Placeholder
                    updated_at=""  # Placeholder
                ))
        return results
