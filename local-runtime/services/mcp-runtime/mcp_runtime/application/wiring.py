"""Composition root."""
from __future__ import annotations

from mcp_runtime.adapters.outbound.process_supervisor import SUPERVISOR, Supervisor
from mcp_runtime.application.ports import ProcessSupervisor


def default_supervisor() -> ProcessSupervisor:
    return SUPERVISOR


def new_supervisor() -> ProcessSupervisor:
    return Supervisor()
