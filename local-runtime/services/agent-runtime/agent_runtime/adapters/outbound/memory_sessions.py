"""In-memory session cancel registry."""
from __future__ import annotations

import threading


class MemorySessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel: dict[str, threading.Event] = {}

    def begin(self, session_id: str) -> threading.Event:
        with self._lock:
            event = threading.Event()
            self._cancel[session_id] = event
            return event

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            event = self._cancel.get(session_id)
            if event is None:
                return False
            event.set()
            return True

    def end(self, session_id: str) -> None:
        with self._lock:
            self._cancel.pop(session_id, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._cancel)
