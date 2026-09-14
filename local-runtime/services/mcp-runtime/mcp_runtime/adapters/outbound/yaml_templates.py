"""Load and validate allowlisted MCP templates. No free-form command."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from mcp_runtime.domain.errors import TemplateError

ALLOWED_COMMANDS = frozenset({"npx", "uvx", "python", "python3", "node"})
PARAM_PLACEHOLDER = re.compile(r"\{\{params\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


def templates_dir() -> Path:
    raw = os.environ.get("MCP_TEMPLATES_DIR", "")
    if raw:
        return Path(raw)
    # Default: local-runtime/services/mcp-runtime/templates (service-owned allowlist)
    return Path(__file__).resolve().parents[3] / "templates"


def load_templates() -> dict[str, dict[str, Any]]:
    directory = templates_dir()
    found: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        template_id = data.get("id")
        if not template_id:
            continue
        command = data.get("command")
        if command not in ALLOWED_COMMANDS:
            raise TemplateError(f"template {template_id!r} command {command!r} is not allowlisted")
        found[str(template_id)] = data
    return found


def get_template(template_id: str) -> dict[str, Any]:
    templates = load_templates()
    if template_id not in templates:
        raise TemplateError(f"unknown template_id {template_id!r}")
    return templates[template_id]


def public_templates() -> list[dict[str, Any]]:
    result = []
    for template in load_templates().values():
        if template.get("hidden"):
            continue
        result.append({
            "id": template["id"],
            "display_name": template.get("display_name") or template["id"],
            "params_schema": template.get("params_schema") or {},
            "secrets": [
                {"name": item["name"], "env": item.get("env") or item["name"]}
                for item in (template.get("secrets") or [])
            ],
        })
    return result


def validate_params(template: dict[str, Any], params: dict[str, Any]) -> dict[str, str]:
    schema = template.get("params_schema") or {}
    cleaned: dict[str, str] = {}
    for key, rules in schema.items():
        if key not in params or params[key] in (None, ""):
            raise TemplateError(f"missing param {key!r}")
        value = str(params[key])
        pattern = (rules or {}).get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            raise TemplateError(f"param {key!r} does not match the template pattern")
        if any(token in value for token in (";", "|", "&", "`", "$", "\n", "..")):
            raise TemplateError(f"param {key!r} contains forbidden characters")
        cleaned[key] = value
    extra = set(params) - set(schema)
    if extra:
        raise TemplateError(f"unexpected params: {sorted(extra)}")
    return cleaned


def _replace_params(raw: str, params: dict[str, str], *, kind: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise TemplateError(f"{kind} references unknown param {name!r}")
        return params[name]

    return PARAM_PLACEHOLDER.sub(_replace, raw)


def render_args(template: dict[str, Any], params: dict[str, str]) -> list[str]:
    return [_replace_params(str(raw), params, kind="arg") for raw in (template.get("args") or [])]


def render_env(template: dict[str, Any], params: dict[str, str]) -> dict[str, str]:
    """Non-secret child env from template `env:` + `{{params.*}}` placeholders."""
    rendered: dict[str, str] = {}
    for key, raw in (template.get("env") or {}).items():
        env_name = str(key)
        if not env_name.isidentifier():
            raise TemplateError(f"invalid env name {env_name!r}")
        rendered[env_name] = _replace_params(str(raw), params, kind="env")
    return rendered
