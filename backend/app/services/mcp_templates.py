"""Allowlisted MCP templates for the catalog. No free-form command."""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status

# Keep in sync with local-runtime/templates/*.yaml. The runtime reads the YAML;
# the backend only needs public metadata and param validation (no PyYAML).
_TEMPLATES: dict[str, dict[str, Any]] = {
    "azure-devops": {
        "id": "azure-devops",
        "display_name": "Azure DevOps",
        "hidden": False,
        "params_schema": {
            "organization": {
                "type": "string",
                "pattern": r"^[A-Za-z0-9][A-Za-z0-9-]*$",
            },
        },
        "secrets": [{"name": "AZURE_DEVOPS_PAT", "env": "ADO_MCP_AUTH_TOKEN"}],
    },
    "test-echo": {
        "id": "test-echo",
        "display_name": "Test Echo",
        "hidden": True,
        "params_schema": {},
        "secrets": [],
    },
}


class TemplateValidationError(ValueError):
    """Unknown template or invalid params."""


def get_template(template_id: str) -> dict[str, Any]:
    template = _TEMPLATES.get(template_id)
    if template is None:
        raise TemplateValidationError(f"unknown template_id {template_id!r}")
    return template


def public_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template["id"],
            "display_name": template["display_name"],
            "params_schema": template["params_schema"],
            "secrets": template["secrets"],
        }
        for template in _TEMPLATES.values()
        if not template.get("hidden")
    ]


def validate_template_params(template_id: str, params: dict[str, Any] | None) -> dict[str, str]:
    template = get_template(template_id)
    schema = template.get("params_schema") or {}
    incoming = params or {}
    cleaned: dict[str, str] = {}
    for key, rules in schema.items():
        if key not in incoming or incoming[key] in (None, ""):
            raise TemplateValidationError(f"missing param {key!r}")
        value = str(incoming[key])
        pattern = (rules or {}).get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            raise TemplateValidationError(f"param {key!r} does not match the template pattern")
        if any(token in value for token in (";", "|", "&", "`", "$", "\n", "..")):
            raise TemplateValidationError(f"param {key!r} contains forbidden characters")
        cleaned[key] = value
    extra = set(incoming) - set(schema)
    if extra:
        raise TemplateValidationError(f"unexpected params: {sorted(extra)}")
    return cleaned


def validate_or_400(template_id: str, params: dict[str, Any] | None) -> dict[str, str]:
    try:
        return validate_template_params(template_id, params)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def catalog_secret_refs(template_id: str, incoming: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Store only env-var names. Never persist a secret value from the client."""
    template = get_template(template_id)
    for item in incoming or []:
        pointer = str(item.get("ref") or "")
        if pointer and not _ENV_NAME.fullmatch(pointer):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="secret_refs.ref must be an environment variable name, not a secret value",
            )
    return [
        {"name": item["name"], "backend": "env", "ref": item["name"]}
        for item in (template.get("secrets") or [])
    ]
