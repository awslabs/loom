"""AgentCore Memory integration using Strands async hooks."""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
from strands.hooks.registry import HookRegistry
from strands.hooks.events import BeforeInvocationEvent, AfterInvocationEvent

logger = logging.getLogger(__name__)

# Default namespace used for memory record retrieval and event creation
_DEFAULT_NAMESPACE = "loom"
# Default actor ID for events created by the agent
_DEFAULT_ACTOR_ID = "loom-agent"

# AWS actorId constraint: [a-zA-Z0-9][a-zA-Z0-9-_/]*(?::[a-zA-Z0-9-_/]+)*[a-zA-Z0-9-_/]*
_ACTOR_ID_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9\-_/:]")


def _sanitize_actor_id(raw: str) -> str:
    """Sanitize actor_id to comply with AWS actorId constraints as a fallback."""
    sanitized = _ACTOR_ID_INVALID_CHARS.sub("-", raw)
    if not sanitized or not sanitized[0].isalnum():
        sanitized = "u-" + sanitized
    return sanitized


class MemoryHook:
    """Strands HookProvider that loads/saves conversation context via AgentCore Memory.

    The hook reads the memory store ID from the ``MEMORY_STORE_ID``
    environment variable. If the variable is unset or empty the hook
    operates as a no-op so callers can safely attach it regardless of
    whether memory is enabled.

    Callbacks are async so they integrate correctly with
    ``Agent.stream_async()`` (see strands-agents/sdk-python#1017).
    Synchronous boto3 calls are offloaded via ``asyncio.to_thread()``
    to avoid blocking the event loop.

    Tracks memory operations (retrievals and events sent) per invocation
    and emits a ``LOOM_MEMORY_TELEMETRY`` structured log line so the
    platform can parse usage for cost estimation.
    """

    def __init__(self, memory_store_id: str | None = None) -> None:
        store_id = memory_store_id or os.environ.get("MEMORY_STORE_ID", "")
        self.memory_store_id: str | None = store_id if store_id else None
        self._client: Any = None

        # Per-invocation counters for cost tracking
        self.retrievals: int = 0
        self.events_sent: int = 0
        # Track message count before invocation so we only save new messages
        self._pre_invocation_message_count: int = 0

        if not self.memory_store_id:
            logger.info("MEMORY_STORE_ID not set; MemoryHook is disabled")

    @property
    def client(self) -> Any:
        """Lazy-initialise the bedrock-agentcore client."""
        if self._client is None and self.memory_store_id:
            self._client = boto3.client(
                "bedrock-agentcore",
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )
        return self._client

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register async callbacks for invocation lifecycle events."""
        registry.add_callback(BeforeInvocationEvent, self._on_before_invocation)
        registry.add_callback(AfterInvocationEvent, self._on_after_invocation)

    async def _on_before_invocation(self, event: BeforeInvocationEvent) -> None:
        """Load conversation history from AgentCore Memory before invocation."""
        # Reset counters at the start of each invocation
        self.retrievals = 0
        self.events_sent = 0
        # Snapshot the agent's full message history length so after_invocation
        # only saves messages added during this invocation.  event.messages is
        # just the input to this call; event.agent.messages is the accumulated
        # conversation history the agent maintains across turns.
        agent_messages = getattr(event, "agent", None)
        if agent_messages is not None:
            agent_messages = getattr(agent_messages, "messages", None)
        self._pre_invocation_message_count = len(agent_messages) if agent_messages else 0

        if not self.memory_store_id:
            return

        logger.info("MemoryHook: before_invocation — retrieving from store '%s'", self.memory_store_id)

        try:
            query = ""
            if event.messages:
                for msg in reversed(event.messages):
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                query = block["text"]
                                break
                    if query:
                        break

            if not query:
                logger.info("MemoryHook: no query text found in messages; skipping memory retrieval")
                return

            response = await asyncio.to_thread(
                self.client.retrieve_memory_records,
                memoryId=self.memory_store_id,
                namespace=_DEFAULT_NAMESPACE,
                searchCriteria={
                    "searchQuery": query,
                },
            )
            records = response.get("memoryRecordSummaries", [])
            self.retrievals = len(records)
            logger.info(
                "MemoryHook: retrieved %d memory record(s) from store '%s'",
                len(records),
                self.memory_store_id,
            )
            if records:
                event.invocation_state["memory"] = records
        except ClientError as e:
            if e.response["Error"]["Code"] == "AccessDeniedException":
                logger.warning("Access denied retrieving memory from store '%s': %s", self.memory_store_id, e.response["Error"]["Message"])
            else:
                logger.exception("Failed to retrieve memory from store '%s'", self.memory_store_id)
        except Exception:
            logger.exception("Failed to retrieve memory from store '%s'", self.memory_store_id)

    async def _on_after_invocation(self, event: AfterInvocationEvent) -> None:
        """Save updated conversation context to AgentCore Memory after invocation."""
        if not self.memory_store_id:
            self._emit_telemetry()
            return

        logger.info("MemoryHook: after_invocation — saving to store '%s'", self.memory_store_id)

        try:
            # Use the agent's full message history rather than result.message
            # (AgentResult has singular `message`, not `messages`).
            messages = getattr(event.agent, "messages", None) or []
            if not messages:
                logger.info("MemoryHook: no messages to save to memory store")
                return

            # Only save messages added during this invocation
            new_messages = messages[self._pre_invocation_message_count:]
            if not new_messages:
                logger.info("MemoryHook: no new messages to save to memory store")
                return

            now = datetime.now(timezone.utc)
            session_id = event.invocation_state.get("session_id", "")
            actor_id = _sanitize_actor_id(event.invocation_state.get("actor_id") or _DEFAULT_ACTOR_ID)
            for msg in new_messages:
                role = msg.get("role", "OTHER").upper()
                # Map Strands roles to AgentCore Memory roles
                if role == "ASSISTANT":
                    ac_role = "ASSISTANT"
                elif role == "USER":
                    ac_role = "USER"
                else:
                    ac_role = "OTHER"

                # Extract text content from the message
                text = ""
                content = msg.get("content", [])
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            text = block["text"]
                            break
                if not text:
                    continue

                create_kwargs: dict[str, Any] = {
                    "memoryId": self.memory_store_id,
                    "actorId": actor_id,
                    "eventTimestamp": now,
                    "payload": [
                        {
                            "conversational": {
                                "content": {"text": text},
                                "role": ac_role,
                            }
                        }
                    ],
                }
                if session_id:
                    create_kwargs["sessionId"] = session_id

                await asyncio.to_thread(self.client.create_event, **create_kwargs)
                self.events_sent += 1

            logger.info(
                "MemoryHook: created %d event(s) in memory store '%s'",
                self.events_sent,
                self.memory_store_id,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "AccessDeniedException":
                logger.warning("Access denied saving memory to store '%s': %s", self.memory_store_id, e.response["Error"]["Message"])
            else:
                logger.exception("Failed to save memory to store '%s'", self.memory_store_id)
        except Exception:
            logger.exception("Failed to save memory to store '%s'", self.memory_store_id)
        finally:
            self._emit_telemetry()

    def _emit_telemetry(self) -> None:
        """Emit a structured log line with memory usage counters for cost tracking."""
        logger.info(
            "LOOM_MEMORY_TELEMETRY: retrievals=%d, events_sent=%d",
            self.retrievals,
            self.events_sent,
        )
