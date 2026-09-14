"""Ports for mcp-runtime."""
from __future__ import annotations

from typing import Any, Protocol


class ProcessSupervisor(Protocol):
    def register(
        self,
        server_id: int,
        template_id: str,
        params: dict[str, Any],
        secret_refs: list[dict[str, Any]] | None = None,
    ) -> Any: ...

    def start(self, server_id: int) -> Any: ...

    def stop(self, server_id: int) -> Any: ...

    def restart(self, server_id: int) -> Any: ...

    def health(self, server_id: int) -> dict[str, Any]: ...

    def call(
        self,
        server_id: int,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def stop_all(self) -> None: ...
