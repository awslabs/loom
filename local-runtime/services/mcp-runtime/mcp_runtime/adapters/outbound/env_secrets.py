"""Resolve SecretReference values. Never log the secret."""
from __future__ import annotations

import os
from typing import Any


from mcp_runtime.domain.errors import SecretError


def resolve_secret_refs(refs: list[dict[str, Any]], template_secrets: list[dict[str, str]]) -> dict[str, str]:
    """Return env-name → value for the child process."""
    env_map: dict[str, str] = {}
    by_name = {item["name"]: item for item in template_secrets}
    for ref in refs:
        name = ref.get("name")
        if not name or name not in by_name:
            raise SecretError(f"secret {name!r} is not declared on the template")
        backend = (ref.get("backend") or "env").lower()
        pointer = ref.get("ref") or name
        value = _resolve(backend, str(pointer), str(name))
        env_name = by_name[name].get("env") or name
        env_map[env_name] = value
    return env_map


def _resolve(backend: str, pointer: str, secret_name: str) -> str:
    if backend == "env":
        if not pointer.isidentifier():
            raise SecretError(f"secret {secret_name} reference is not an environment variable name")
        value = os.environ.get(pointer, "")
        if not value:
            raise SecretError(f"secret {secret_name} is not set in the runtime environment")
        return value
    if backend == "secrets_manager":
        from app.services.secrets import get_secret  # type: ignore

        region = os.getenv("AWS_REGION", "us-east-1")
        return get_secret(pointer, region)
    raise SecretError(f"unknown secret backend {backend!r}")
