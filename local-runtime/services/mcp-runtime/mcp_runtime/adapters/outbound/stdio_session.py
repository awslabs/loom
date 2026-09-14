"""One-line JSON-RPC over a child process stdin/stdout."""
from __future__ import annotations

import json
import threading
from typing import Any


from mcp_runtime.domain.errors import StdioError


_REDACT_MARKERS = ("token", "pat", "authorization", "bearer", "password", "secret")


def sanitize_stderr(lines: list[str], limit: int = 8) -> str:
    """Last stderr lines for diagnostics. Never echo secret-looking values."""
    cleaned: list[str] = []
    for line in lines[-limit:]:
        lower = line.lower()
        if any(marker in lower for marker in _REDACT_MARKERS):
            cleaned.append("[redacted]")
            continue
        text = line.strip()
        if len(text) > 200:
            text = text[:200] + "…"
        if text:
            cleaned.append(text)
    return " | ".join(cleaned)


class StdioSession:
    def __init__(self, process: Any, timeout_s: float = 30.0) -> None:
        self._process = process
        self._timeout_s = timeout_s
        self._next_id = 1
        self._lock = threading.Lock()
        self.stderr_tail: list[str] = []
        stderr = getattr(process, "stderr", None)
        if stderr is not None:
            reader = threading.Thread(target=self._drain_stderr, args=(stderr,), daemon=True)
            reader.start()

    def _drain_stderr(self, stderr: Any) -> None:
        try:
            for raw in stderr:
                line = raw.rstrip("\n") if isinstance(raw, str) else ""
                if not line:
                    continue
                self.stderr_tail.append(line)
                if len(self.stderr_tail) > 40:
                    self.stderr_tail.pop(0)
        except Exception:
            return

    def _child_hint(self) -> str:
        hint = sanitize_stderr(self.stderr_tail)
        return f" ({hint})" if hint else ""

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        with self._lock:
            payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                payload["params"] = params
            stdin = self._process.stdin
            if stdin is None:
                raise StdioError("child stdio is closed")
            stdin.write(json.dumps(payload) + "\n")
            stdin.flush()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
            stdin = self._process.stdin
            stdout = self._process.stdout
            if stdin is None or stdout is None:
                raise StdioError("child stdio is closed")
            stdin.write(json.dumps(payload) + "\n")
            stdin.flush()
            holder: list[str] = []

            def _read() -> None:
                holder.append(stdout.readline())

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(self._timeout_s)
            if reader.is_alive():
                raise StdioError("child timed out")
            line = holder[0] if holder else ""
            if not line:
                raise StdioError(f"child closed stdout{self._child_hint()}")
            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise StdioError("child returned non-JSON") from exc
