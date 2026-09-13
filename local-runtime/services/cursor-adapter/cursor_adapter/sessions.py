"""In-memory session map: Loom identity → Cursor agent id."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


DEFAULT_TTL_SECONDS = 60 * 60


@dataclass
class SessionRecord:
    key: str
    cursor_agent_id: str
    workspace: str
    created_at: float
    last_used_at: float


class SessionManager:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: callable | None = None) -> None:
        self._ttl = ttl_seconds
        self._now = now or time.time
        self._records: dict[str, SessionRecord] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._map_lock = threading.Lock()

    def make_key(
        self,
        tenant: str,
        agent_id: str,
        workspace: str,
        session_id: str,
    ) -> str:
        return f"{tenant}:{agent_id}:{workspace}:{session_id}"

    def lock_for(self, key: str) -> threading.Lock:
        with self._map_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def get(self, key: str) -> SessionRecord | None:
        self.expire()
        record = self._records.get(key)
        if record is None:
            return None
        record.last_used_at = self._now()
        return record

    def put(self, key: str, cursor_agent_id: str, workspace: str) -> SessionRecord:
        now = self._now()
        record = SessionRecord(
            key=key,
            cursor_agent_id=cursor_agent_id,
            workspace=workspace,
            created_at=now,
            last_used_at=now,
        )
        self._records[key] = record
        return record

    def expire(self) -> list[str]:
        cutoff = self._now() - self._ttl
        expired = [key for key, record in self._records.items() if record.last_used_at < cutoff]
        for key in expired:
            self._records.pop(key, None)
        return expired
