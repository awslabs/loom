"""AWS Agent Registry service for managing registry records."""
import json
import logging
import os
import re
import time
from typing import Any

import boto3

from app.models.a2a import A2aAgent
from app.models.mcp import McpServer, McpTool

logger = logging.getLogger(__name__)

# ARN pattern: arn:aws:bedrock-agentcore:{region}:{account}:registry/{id}
_REGISTRY_ARN_PATTERN = re.compile(
    r"^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:registry/[a-zA-Z0-9_-]+$"
)

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
_client: "RegistryClient | None" = None


def get_registry_client() -> "RegistryClient":
    """Return (or lazily create) the module-level RegistryClient singleton."""
    global _client
    if _client is None:
        registry_id = os.getenv("LOOM_REGISTRY_ID", "")
        region = os.getenv("AWS_REGION", "us-east-1")
        _client = RegistryClient(registry_id=registry_id, region=region)
    return _client


def configure_registry(registry_id: str, region: str | None = None) -> "RegistryClient":
    """Reconfigure the singleton with a new registry ID. Called on settings update."""
    global _client
    rgn = region or os.getenv("AWS_REGION", "us-east-1")
    _client = RegistryClient(registry_id=registry_id, region=rgn)
    return _client


def init_registry_from_db(db_session) -> None:
    """Load registry config from site_settings on startup. Falls back to env var."""
    from app.models.site_setting import SiteSetting
    setting = db_session.query(SiteSetting).filter(SiteSetting.key == "loom_registry_id").first()
    registry_id = ""
    if setting and setting.value:
        registry_id = parse_registry_id_from_arn(setting.value)
    if not registry_id:
        registry_id = os.getenv("LOOM_REGISTRY_ID", "")
    if registry_id:
        configure_registry(registry_id)
        logger.info("Registry client initialized with registry_id=%s", registry_id)
    else:
        logger.info("No registry configured; governance features disabled")


def validate_registry_arn(arn: str) -> str:
    """Validate a registry ARN and return the registry ID, or raise ValueError."""
    if not _REGISTRY_ARN_PATTERN.match(arn):
        raise ValueError(
            f"Invalid registry ARN: {arn}. "
            "Expected format: arn:aws:bedrock-agentcore:<region>:<account>:registry/<id>"
        )
    return parse_registry_id_from_arn(arn)


def parse_registry_id_from_arn(arn: str) -> str:
    """Extract registry ID from an ARN string. Returns empty string if not parseable."""
    parts = arn.split("/")
    return parts[-1] if len(parts) >= 2 else ""


# ---------------------------------------------------------------------------
# RegistryClient
# ---------------------------------------------------------------------------
class RegistryClient:
    """Thin wrapper around the Bedrock AgentCore registry APIs."""

    def __init__(self, registry_id: str, region: str) -> None:
        self.registry_id = registry_id
        self.region = region

        if self.registry_id:
            session = boto3.Session(region_name=region)
            self.control = session.client("bedrock-agentcore-control")
            self.data = session.client("bedrock-agentcore")
        else:
            self.control = None
            self.data = None
            logger.warning("LOOM_REGISTRY_ID not set; registry operations will return empty results")

    # -- guard ---------------------------------------------------------------
    def _require_registry(self) -> bool:
        """Return True when the registry is configured, False otherwise."""
        if not self.registry_id or self.control is None:
            logger.debug("Registry not configured; skipping operation")
            return False
        return True

    # -- control-plane -------------------------------------------------------
    def get_registry(self) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.get_registry(registryId=self.registry_id)

    def create_record(
        self,
        name: str,
        descriptor_type: str,
        descriptors: dict[str, Any],
        record_version: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        kwargs: dict[str, Any] = dict(
            registryId=self.registry_id,
            name=name,
            descriptorType=descriptor_type,
            descriptors=descriptors,
            recordVersion=record_version,
        )
        if description:
            kwargs["description"] = description
        logger.info("create_record payload: %s", json.dumps(kwargs, indent=2, default=str))
        result = self.control.create_registry_record(**kwargs)
        # create response may only have recordArn; extract recordId from it
        if "recordId" not in result and "recordArn" in result:
            arn_parts = result["recordArn"].split("/")
            if len(arn_parts) >= 2:
                result["recordId"] = arn_parts[-1]
        return result

    def get_record(self, record_id: str) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.get_registry_record(
            registryId=self.registry_id,
            recordId=record_id,
        )

    def wait_for_record(self, record_id: str, poll_interval: int = 5) -> dict[str, Any]:
        """Poll until the record leaves the CREATING state."""
        if not self._require_registry():
            return {}
        while True:
            rec = self.get_record(record_id)
            status = rec.get("status", "")
            if status != "CREATING":
                logger.info("Record %s reached status %s", record_id, status)
                return rec
            logger.debug("Record %s still CREATING; polling in %ds", record_id, poll_interval)
            time.sleep(poll_interval)

    def list_records(self) -> dict[str, Any]:
        if not self._require_registry():
            return {"registryRecords": []}
        return self.control.list_registry_records(registryId=self.registry_id)

    def submit_for_approval(self, record_id: str) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.submit_registry_record_for_approval(
            registryId=self.registry_id,
            recordId=record_id,
        )

    def approve_record(self, record_id: str, reason: str = "Approved via Loom") -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.update_registry_record_status(
            registryId=self.registry_id,
            recordId=record_id,
            status="APPROVED",
            statusReason=reason,
        )

    def reject_record(self, record_id: str, reason: str) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.update_registry_record_status(
            registryId=self.registry_id,
            recordId=record_id,
            status="REJECTED",
            statusReason=reason,
        )

    def update_record_status(self, record_id: str, status: str, reason: str) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.update_registry_record_status(
            registryId=self.registry_id,
            recordId=record_id,
            status=status,
            statusReason=reason,
        )

    def update_record(
        self,
        record_id: str,
        name: str,
        descriptor_type: str,
        descriptors: dict[str, Any],
        record_version: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        update_descriptors = self._wrap_descriptors_for_update(descriptors)
        kwargs: dict[str, Any] = dict(
            registryId=self.registry_id,
            recordId=record_id,
            name=name,
            descriptorType=descriptor_type,
            descriptors=update_descriptors,
            recordVersion=record_version,
        )
        if description:
            kwargs["description"] = {"optionalValue": description}
        logger.info("update_record payload: %s", json.dumps(kwargs, indent=2, default=str))
        return self.control.update_registry_record(**kwargs)

    @staticmethod
    def _wrap_descriptors_for_update(descriptors: dict[str, Any]) -> dict[str, Any]:
        """Wrap create-style descriptors in the optionalValue structure required by UpdateRegistryRecord."""
        inner = {}
        for dtype, fields in descriptors.items():
            wrapped_fields = {}
            for field_name, field_value in fields.items():
                wrapped_fields[field_name] = {"optionalValue": field_value}
            inner[dtype] = {"optionalValue": wrapped_fields}
        return {"optionalValue": inner}

    def delete_record(self, record_id: str) -> dict[str, Any]:
        if not self._require_registry():
            return {}
        return self.control.delete_registry_record(
            registryId=self.registry_id,
            recordId=record_id,
        )

    # -- data-plane ----------------------------------------------------------
    def search_records(self, query: str, max_results: int = 10) -> dict[str, Any]:
        if not self._require_registry():
            return {"results": []}
        return self.data.search_registry_records(
            registryIds=[self.registry_id],
            searchQuery=query,
            maxResults=max_results,
        )

    # -- descriptor builders -------------------------------------------------
    @staticmethod
    def build_mcp_descriptors(server: McpServer, tools: list[McpTool], namespace: str = "aws.agentcore") -> dict[str, Any]:
        """Build MCP-type descriptors conforming to the MCP InitializeResult schema."""
        MCP_DESCRIPTION_MAX_LENGTH = 100
        namespaced_name = f"{namespace}/{server.name}"
        transport_type = server.transport_type or "streamable_http"
        remote_type = "streamable-http" if transport_type == "streamable_http" else transport_type
        server_info: dict[str, Any] = {
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": namespaced_name,
            "description": (server.description or "")[:MCP_DESCRIPTION_MAX_LENGTH],
            "version": "1.0.0",
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": namespaced_name,
                "version": "1.0.0",
            },
            "remotes": [{
                "type": remote_type,
                "url": server.endpoint_url,
            }],
        }
        if server.description:
            server_info["instructions"] = server.description[:MCP_DESCRIPTION_MAX_LENGTH]

        tool_definitions = []
        for tool in tools:
            tool_def: dict[str, Any] = {
                "name": tool.tool_name,
                "description": (tool.description or "")[:MCP_DESCRIPTION_MAX_LENGTH],
            }
            schema = tool.get_input_schema()
            if schema:
                tool_def["inputSchema"] = schema
            else:
                tool_def["inputSchema"] = {"type": "object", "properties": {}}
            tool_definitions.append(tool_def)

        return {
            "mcp": {
                "server": {
                    "inlineContent": json.dumps(server_info),
                },
                "tools": {
                    "inlineContent": json.dumps({"tools": tool_definitions}),
                },
            }
        }

    @staticmethod
    def build_agent_descriptors(agent) -> dict[str, Any]:
        """Build A2A-type descriptors from a Loom Agent."""
        agent_card = {
            "protocolVersion": "0.3",
            "name": agent.name or agent.runtime_id,
            "description": agent.description or "",
            "url": agent.endpoint_arn or agent.arn,
            "version": "1.0.0",
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "default",
                    "name": agent.name or agent.runtime_id,
                    "description": agent.description or "Default skill",
                    "tags": ["loom"],
                }
            ],
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
        }
        return {
            "a2a": {
                "agentCard": {
                    "schemaVersion": "0.3",
                    "inlineContent": json.dumps(agent_card),
                },
            }
        }

    @staticmethod
    def build_a2a_descriptors(agent: A2aAgent) -> dict[str, Any]:
        """Build A2A-type descriptors conforming to the A2A AgentCard spec."""
        raw = agent.agent_card_raw or "{}"
        source = json.loads(raw) if isinstance(raw, str) else raw

        raw_caps = source.get("capabilities", {})
        capabilities: dict[str, Any] = {}
        if "streaming" in raw_caps:
            capabilities["streaming"] = raw_caps["streaming"]
        if not capabilities:
            capabilities["streaming"] = False

        raw_skills = source.get("skills", [])
        skills = []
        for s in raw_skills:
            skills.append({
                "id": s.get("id", "default"),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "tags": s.get("tags", []),
            })
        if not skills:
            skills = [{"id": "default", "name": agent.name, "description": agent.description or "Default skill", "tags": ["loom"]}]

        card: dict[str, Any] = {
            "protocolVersion": source.get("protocolVersion", "0.3"),
            "name": source.get("name", agent.name),
            "description": source.get("description", agent.description or ""),
            "version": source.get("version", "1.0.0"),
            "url": source.get("url", agent.base_url or ""),
            "capabilities": capabilities,
            "skills": skills,
            "defaultInputModes": source.get("defaultInputModes", ["text/plain"]),
            "defaultOutputModes": source.get("defaultOutputModes", ["text/plain"]),
        }

        logger.info("build_a2a_descriptors card: %s", json.dumps(card, indent=2))

        return {
            "a2a": {
                "agentCard": {
                    "schemaVersion": "0.3",
                    "inlineContent": json.dumps(card),
                },
            }
        }
