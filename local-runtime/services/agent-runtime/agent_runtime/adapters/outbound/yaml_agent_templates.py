"""Load allowlisted local agent templates from YAML (Spec 026)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.domain.agent_template import AgentTemplate, parse_agent_template
from agent_runtime.domain.errors import TemplateError


def templates_dir() -> Path:
    raw = os.environ.get("AGENT_TEMPLATES_DIR", "").strip()
    if raw:
        return Path(raw)
    # Default: local-runtime/services/agent-runtime/templates
    return Path(__file__).resolve().parents[3] / "templates"


def load_templates() -> dict[str, AgentTemplate]:
    directory = templates_dir()
    found: dict[str, AgentTemplate] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise TemplateError(f"template file {path.name} root must be a mapping")
        template = parse_agent_template(data)
        if template.id in found:
            raise TemplateError(f"duplicate template id {template.id!r}")
        found[template.id] = template
    return found


def get_template(template_id: str) -> AgentTemplate:
    templates = load_templates()
    if template_id not in templates:
        raise TemplateError(f"unknown template_id {template_id!r}")
    return templates[template_id]


def public_templates() -> list[dict[str, Any]]:
    """Catalog view for future create-local UI (no secrets values)."""
    result: list[dict[str, Any]] = []
    for template in load_templates().values():
        result.append({
            "id": template.id,
            "display_name": template.display_name,
            "description": template.description,
            "model_id": template.model_id,
            "allowed_model_ids": list(template.allowed_model_ids),
            "params_schema": template.params_schema,
            "secrets": list(template.secrets),
            "tags": dict(template.tags),
            "knowledge_files": list(template.knowledge_files),
        })
    return result
