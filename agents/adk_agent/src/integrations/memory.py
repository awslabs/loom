"""AgentCore Memory integration using an ADK BasePlugin.

Ports ``agents/strands_agent/src/integrations/memory.py``'s semantics
(same env var, same namespace/actor-id defaults, same
``LOOM_MEMORY_TELEMETRY`` structured log line) onto ADK's
``before_agent_callback``/``after_agent_callback`` plugin hooks, the
closest analog to Strands' ``BeforeInvocationEvent``/``AfterInvocationEvent``.

Message-history access differs: Strands exposes ``event.agent.messages``
(a flat list of role/content dicts); ADK exposes ``callback_context.session.events``
(a list of ``Event`` objects, each wrapping a ``types.Content`` with
``.parts``/``.role``). The "only save messages added during this invocation"
behavior is preserved by snapshotting ``len(session.events)`` before the
invocation, exactly like Strands snapshots ``len(agent.messages)``.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

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


def _extract_text(content: Optional[types.Content]) -> str:
    """Extract the first text part from a Content object, if any."""
    if content is None or not content.parts:
        return ""
    for part in content.parts:
        if part.text:
            return part.text
    return ""


class MemoryPlugin(BasePlugin):
    """ADK BasePlugin that loads/saves conversation context via AgentCore Memory.

    Reads the memory store ID from the ``MEMORY_STORE_ID`` environment
    variable. If unset or empty the plugin operates as a no-op so callers
    can safely attach it regardless of whether memory is enabled.

    Tracks memory operations (retrievals and events sent) per invocation and
    emits a ``LOOM_MEMORY_TELEMETRY`` structured log line so the platform can
    parse usage for cost estimation — same log format as Strands' MemoryHook.
    """

    def __init__(self, memory_store_id: str | None = None, name: str = "loom_memory_plugin") -> None:
        super().__init__(name=name)
        store_id = memory_store_id or os.environ.get("MEMORY_STORE_ID", "")
        self.memory_store_id: str | None = store_id if store_id else None
        self._client: Any = None

        # Per-invocation counters for cost tracking
        self.retrievals: int = 0
        self.events_sent: int = 0
        # Track event count before invocation so we only save new events
        self._pre_invocation_event_count: int = 0

        if not self.memory_store_id:
            logger.info("MEMORY_STORE_ID not set; MemoryPlugin is disabled")

    @property
    def client(self) -> Any:
        """Lazily initialize the bedrock-agentcore client."""
        if self._client is None and self.memory_store_id:
            self._client = boto3.client(
                "bedrock-agentcore",
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )
        return self._client

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        """Load conversation history from AgentCore Memory before invocation."""
        # Reset counters at the start of each invocation
        self.retrievals = 0
        self.events_sent = 0
        session = callback_context.session
        self._pre_invocation_event_count = len(session.events) if session else 0

        if not self.memory_store_id:
            return None

        logger.info("MemoryPlugin: before_invocation — retrieving from store '%s'", self.memory_store_id)

        try:
            query = _extract_text(callback_context.user_content)
            if not query and session:
                for event in reversed(session.events):
                    text = _extract_text(event.content)
                    if text:
                        query = text
                        break

            if not query:
                logger.info("MemoryPlugin: no query text found in messages; skipping memory retrieval")
                return None

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
                "MemoryPlugin: retrieved %d memory record(s) from store '%s'",
                len(records),
                self.memory_store_id,
            )
            if records:
                callback_context.state["memory"] = records
        except ClientError as e:
            if e.response["Error"]["Code"] == "AccessDeniedException":
                logger.warning("Access denied retrieving memory from store '%s': %s", self.memory_store_id, e.response["Error"]["Message"])
            else:
                logger.exception("Failed to retrieve memory from store '%s'", self.memory_store_id)
        except Exception:
            logger.exception("Failed to retrieve memory from store '%s'", self.memory_store_id)
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        """Save updated conversation context to AgentCore Memory after invocation."""
        if not self.memory_store_id:
            self._emit_telemetry()
            return None

        logger.info("MemoryPlugin: after_invocation — saving to store '%s'", self.memory_store_id)

        try:
            session = callback_context.session
            events = session.events if session else []
            if not events:
                logger.info("MemoryPlugin: no messages to save to memory store")
                return None

            # Only save events added during this invocation
            new_events = events[self._pre_invocation_event_count:]
            if not new_events:
                logger.info("MemoryPlugin: no new messages to save to memory store")
                return None

            now = datetime.now(timezone.utc)
            session_id = session.id if session else ""
            actor_id = _sanitize_actor_id(callback_context.user_id or _DEFAULT_ACTOR_ID)
            for event in new_events:
                author = (event.author or "").lower()
                # Map ADK event authors to AgentCore Memory roles
                if author == "user":
                    ac_role = "USER"
                elif author and author != "user":
                    ac_role = "ASSISTANT"
                else:
                    ac_role = "OTHER"

                text = _extract_text(event.content)
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
                "MemoryPlugin: created %d event(s) in memory store '%s'",
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
        return None

    def _emit_telemetry(self) -> None:
        """Emit a structured log line with memory usage counters for cost tracking."""
        logger.info(
            "LOOM_MEMORY_TELEMETRY: retrievals=%d, events_sent=%d",
            self.retrievals,
            self.events_sent,
        )
