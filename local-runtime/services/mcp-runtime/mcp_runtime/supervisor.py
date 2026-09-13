"""Process lifecycle for one stdio MCP per server_id."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from mcp_runtime.secrets import SecretError, resolve_secret_refs
from mcp_runtime.stdio import StdioError, StdioSession
from mcp_runtime.templates import get_template, render_args, render_env, validate_params

logger = logging.getLogger("mcp_runtime")

REGISTERED = "REGISTERED"
STARTING = "STARTING"
READY = "READY"
RUNNING = "RUNNING"
STOPPING = "STOPPING"
STOPPED = "STOPPED"
FAILED = "FAILED"
RESTARTING = "RESTARTING"


@dataclass
class ServerHandle:
    server_id: int
    template_id: str
    params: dict[str, str]
    secret_refs: list[dict[str, Any]]
    state: str = REGISTERED
    process: subprocess.Popen[str] | None = None
    session: StdioSession | None = None
    restarts: int = 0
    started_at: str | None = None
    last_error_code: str | None = None
    catalog_status: str = "inactive"


class Supervisor:
    def __init__(self) -> None:
        self._handles: dict[int, ServerHandle] = {}

    def register(
        self,
        server_id: int,
        template_id: str,
        params: dict[str, Any],
        secret_refs: list[dict[str, Any]] | None = None,
    ) -> ServerHandle:
        template = get_template(template_id)
        cleaned = validate_params(template, params or {})
        handle = ServerHandle(
            server_id=server_id,
            template_id=template_id,
            params=cleaned,
            secret_refs=list(secret_refs or []),
            state=REGISTERED,
        )
        existing = self._handles.get(server_id)
        if existing and existing.process:
            self.stop(server_id)
        self._handles[server_id] = handle
        return handle

    def start(self, server_id: int) -> ServerHandle:
        handle = self._require(server_id)
        template = get_template(handle.template_id)
        handle.state = STARTING
        handle.catalog_status = "active"
        command = template["command"]
        binary = shutil.which(command)
        if not binary and command == "python":
            binary = shutil.which("python3")
        elif not binary and command == "python3":
            binary = shutil.which("python")
        if not binary:
            handle.state = FAILED
            handle.catalog_status = "error"
            handle.last_error_code = "command_not_found"
            raise RuntimeError(f"command {command} is not on PATH")
        args = [binary, *render_args(template, handle.params)]
        child_env = os.environ.copy()
        child_env.update(render_env(template, handle.params))
        try:
            child_env.update(resolve_secret_refs(handle.secret_refs, template.get("secrets") or []))
        except SecretError:
            handle.state = FAILED
            handle.catalog_status = "error"
            handle.last_error_code = "secret_unresolved"
            raise
        try:
            process = subprocess.Popen(  # noqa: S603 — argv list, shell=False, command allowlisted
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=child_env,
                shell=False,
            )
        except OSError as exc:
            handle.state = FAILED
            handle.catalog_status = "error"
            handle.last_error_code = "spawn_failed"
            raise RuntimeError(str(exc)) from exc
        handle.process = process
        timeout = float(template.get("startup_timeout_s") or 30)
        handle.session = StdioSession(process, timeout_s=timeout)
        try:
            init = handle.session.call(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "loom-mcp-runtime", "version": "1.0.0"},
                },
            )
            if "error" in init:
                raise RuntimeError("initialize failed")
            handle.session.notify("notifications/initialized")
            listed = handle.session.call("tools/list")
            if "error" in listed:
                raise RuntimeError("tools/list failed")
        except Exception:
            self._kill(handle)
            handle.state = FAILED
            handle.catalog_status = "error"
            handle.last_error_code = "initialize_failed"
            raise
        handle.state = READY
        handle.started_at = datetime.now(timezone.utc).isoformat()
        handle.last_error_code = None
        return handle

    def call(self, server_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        handle = self._require(server_id)
        if handle.state not in (READY, RUNNING) or handle.session is None:
            handle = self.start(server_id)
        try:
            result = handle.session.call(method, params)
        except StdioError:
            handle.state = FAILED
            handle.catalog_status = "error"
            handle.last_error_code = "stdio_closed"
            raise
        if method == "tools/call":
            handle.state = RUNNING
        return result

    def stop(self, server_id: int) -> ServerHandle:
        handle = self._require(server_id)
        handle.state = STOPPING
        self._kill(handle)
        handle.state = STOPPED
        handle.catalog_status = "inactive"
        return handle

    def restart(self, server_id: int) -> ServerHandle:
        handle = self._require(server_id)
        template = get_template(handle.template_id)
        max_restarts = int(template.get("max_restarts") or 3)
        handle.state = RESTARTING
        if handle.process:
            self._kill(handle)
        handle.restarts += 1
        if handle.restarts > max_restarts:
            handle.state = FAILED
            handle.catalog_status = "error"
            handle.last_error_code = "max_restarts"
            raise RuntimeError("max restarts exceeded")
        return self.start(server_id)

    def health(self, server_id: int) -> dict[str, Any]:
        handle = self._require(server_id)
        pid = handle.process.pid if handle.process and handle.process.poll() is None else None
        return {
            "state": handle.state,
            "pid": pid,
            "restarts": handle.restarts,
            "started_at": handle.started_at,
            "last_error_code": handle.last_error_code,
        }

    def stop_all(self) -> None:
        for server_id in list(self._handles):
            try:
                self.stop(server_id)
            except Exception:
                logger.warning("failed to stop server %s", server_id, exc_info=True)

    def _require(self, server_id: int) -> ServerHandle:
        handle = self._handles.get(server_id)
        if handle is None:
            raise KeyError(server_id)
        return handle

    def _kill(self, handle: ServerHandle) -> None:
        process = handle.process
        handle.session = None
        handle.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


SUPERVISOR = Supervisor()
