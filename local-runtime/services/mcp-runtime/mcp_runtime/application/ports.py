"""Ports for mcp-runtime."""
from __future__ import annotations

from typing import Any, Protocol

from mcp_runtime.domain.types import HealthInfo, SecretRef

# JSON-RPC / template param maps stay as dict at the wire boundary.
JsonObject = dict[str, Any]


class ProcessSupervisor(Protocol):
    def register(
        self,
        server_id: int,
        template_id: str,
        params: dict[str, Any],
        secret_refs: list[SecretRef] | None = None,
    ) -> object: ...

    def start(self, server_id: int) -> object: ...

    def stop(self, server_id: int) -> object: ...

    def restart(self, server_id: int) -> object: ...

    def health(self, server_id: int) -> HealthInfo: ...

    def call(
        self,
        server_id: int,
        method: str,
        params: JsonObject | None = None,
    ) -> JsonObject: ...

    def stop_all(self) -> None: ...
