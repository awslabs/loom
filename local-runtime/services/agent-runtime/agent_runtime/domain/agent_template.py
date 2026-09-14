"""Local agent template model and validation (Spec 026 / ADR 0013)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_runtime.domain.errors import TemplateError

TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
PARAM_PLACEHOLDER = re.compile(r"\{\{params\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


@dataclass(frozen=True)
class AgentTemplate:
    id: str
    display_name: str
    description: str
    system_prompt: str
    model_id: str
    allowed_model_ids: tuple[str, ...]
    knowledge_files: tuple[str, ...]
    knowledge_inline: str
    default_connector_template_ids: tuple[str, ...]
    params_schema: dict[str, Any]
    secrets: tuple[dict[str, str], ...]
    tags: dict[str, str]


def parse_agent_template(data: dict[str, Any]) -> AgentTemplate:
    """Validate a raw YAML mapping into an AgentTemplate."""
    if not isinstance(data, dict):
        raise TemplateError("template root must be a mapping")

    template_id = str(data.get("id") or "").strip()
    if not template_id:
        raise TemplateError("template id is required")
    if not TEMPLATE_ID_RE.fullmatch(template_id):
        raise TemplateError(
            f"template id {template_id!r} must match {TEMPLATE_ID_RE.pattern}"
        )

    system_prompt = data.get("system_prompt")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise TemplateError(f"template {template_id!r} system_prompt is required")

    model_id = str(data.get("model_id") or "").strip()
    if not model_id:
        raise TemplateError(f"template {template_id!r} model_id is required")

    raw_allowed = data.get("allowed_model_ids")
    if raw_allowed is None:
        allowed = (model_id,)
    elif not isinstance(raw_allowed, list) or not raw_allowed:
        raise TemplateError(f"template {template_id!r} allowed_model_ids must be a non-empty list")
    else:
        allowed = tuple(str(item).strip() for item in raw_allowed if str(item).strip())
        if not allowed:
            raise TemplateError(f"template {template_id!r} allowed_model_ids must be a non-empty list")
    if model_id not in allowed:
        raise TemplateError(
            f"template {template_id!r} model_id {model_id!r} must appear in allowed_model_ids"
        )

    knowledge = data.get("knowledge") or {}
    if knowledge is None:
        knowledge = {}
    if not isinstance(knowledge, dict):
        raise TemplateError(f"template {template_id!r} knowledge must be a mapping")
    files_raw = knowledge.get("files") or []
    if not isinstance(files_raw, list):
        raise TemplateError(f"template {template_id!r} knowledge.files must be a list")
    knowledge_files = tuple(str(item) for item in files_raw)
    inline = knowledge.get("inline") or ""
    if not isinstance(inline, str):
        raise TemplateError(f"template {template_id!r} knowledge.inline must be a string")

    mcp = data.get("mcp") or {}
    if not isinstance(mcp, dict):
        raise TemplateError(f"template {template_id!r} mcp must be a mapping")
    connectors_raw = mcp.get("default_connector_template_ids") or []
    if not isinstance(connectors_raw, list):
        raise TemplateError(
            f"template {template_id!r} mcp.default_connector_template_ids must be a list"
        )
    connectors = tuple(str(item) for item in connectors_raw)

    params_schema = data.get("params_schema") or {}
    if not isinstance(params_schema, dict):
        raise TemplateError(f"template {template_id!r} params_schema must be a mapping")

    secrets_raw = data.get("secrets") or []
    if not isinstance(secrets_raw, list):
        raise TemplateError(f"template {template_id!r} secrets must be a list")
    secrets: list[dict[str, str]] = []
    for item in secrets_raw:
        if not isinstance(item, dict) or "name" not in item:
            raise TemplateError(f"template {template_id!r} secrets entries need a name")
        secrets.append({
            "name": str(item["name"]),
            "env": str(item.get("env") or item["name"]),
        })

    tags_raw = data.get("tags") or {}
    if not isinstance(tags_raw, dict):
        raise TemplateError(f"template {template_id!r} tags must be a mapping")
    tags = {str(k): str(v) for k, v in tags_raw.items()}

    display_name = str(data.get("display_name") or template_id).strip() or template_id
    description = data.get("description") or ""
    if not isinstance(description, str):
        raise TemplateError(f"template {template_id!r} description must be a string")

    return AgentTemplate(
        id=template_id,
        display_name=display_name,
        description=description.strip(),
        system_prompt=system_prompt.strip(),
        model_id=model_id,
        allowed_model_ids=allowed,
        knowledge_files=knowledge_files,
        knowledge_inline=inline,
        default_connector_template_ids=connectors,
        params_schema=dict(params_schema),
        secrets=tuple(secrets),
        tags=tags,
    )


def validate_params(template: AgentTemplate, params: dict[str, Any] | None) -> dict[str, str]:
    """Require every params_schema key; reject extras and shell metacharacters."""
    raw = params or {}
    if not isinstance(raw, dict):
        raise TemplateError("params must be a mapping")
    cleaned: dict[str, str] = {}
    schema = template.params_schema
    for key in schema:
        if key not in raw or raw[key] in (None, ""):
            raise TemplateError(f"missing param {key!r}")
        value = str(raw[key]).strip()
        if any(token in value for token in (";", "|", "&", "`", "$", "\n")):
            raise TemplateError(f"param {key!r} contains forbidden characters")
        cleaned[key] = value
    extra = set(raw) - set(schema)
    if extra:
        raise TemplateError(f"unexpected params: {sorted(extra)}")
    return cleaned


def _apply_params(text: str, params: dict[str, str], *, kind: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise TemplateError(f"{kind} references unknown param {name!r}")
        return params[name]

    return PARAM_PLACEHOLDER.sub(_replace, text)


def resolve_system_prompt(
    template: AgentTemplate,
    *,
    params: dict[str, str] | None = None,
    override: str | None = None,
) -> str:
    """Effective system prompt: override wins; else template with params + inline."""
    if isinstance(override, str) and override.strip():
        return override.strip()
    cleaned = params if params is not None else validate_params(template, {})
    prompt = _apply_params(template.system_prompt, cleaned, kind="system_prompt")
    inline = template.knowledge_inline.strip()
    if inline:
        inline = _apply_params(inline, cleaned, kind="knowledge.inline")
        return f"{prompt.rstrip()}\n\n{inline}"
    return prompt


def materialize_agent_config(
    template: AgentTemplate,
    *,
    params: dict[str, Any] | None = None,
    system_prompt_override: str | None = None,
) -> dict[str, Any]:
    """Shape suitable for AGENT_CONFIG_JSON materialization (Spec 026 §5)."""
    cleaned = validate_params(template, params)
    return {
        "template_id": template.id,
        "template_params": cleaned,
        "model_id": template.model_id,
        "provider": "litellm",
        "base_url": "",
        "system_prompt": resolve_system_prompt(
            template, params=cleaned, override=system_prompt_override
        ),
        "allowed_model_ids": list(template.allowed_model_ids),
        "knowledge": {
            "files": list(template.knowledge_files),
            "inline": template.knowledge_inline,
        },
        "mcp": {
            "default_connector_template_ids": list(
                template.default_connector_template_ids
            ),
        },
        "tags": dict(template.tags),
    }
