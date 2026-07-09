"""Bedrock token counting via the CountTokens API.

Uses the ``bedrock-runtime`` client's ``count_tokens`` method to get
accurate token counts for a given model. Falls back to a character-based
heuristic (4 chars/token) if the API call fails.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Models known to support the CountTokens API
_SUPPORTED_PROVIDERS = ("anthropic", "meta")


def _supports_count_tokens(model_id: str) -> bool:
    """Check if a model supports the CountTokens API based on its provider."""
    model_lower = model_id.lower()
    return any(provider in model_lower for provider in _SUPPORTED_PROVIDERS)


def count_input_tokens(
    model_id: str,
    prompt: str,
    region: str = "us-east-1",
) -> int:
    """Count the number of input tokens for a prompt using the Bedrock CountTokens API.

    Args:
        model_id: Bedrock model ID (e.g., ``us.anthropic.claude-sonnet-4-6``).
        prompt: The user prompt text.
        region: AWS region name.

    Returns:
        Token count for the prompt. Falls back to ``len(prompt) // 4`` on error.
    """
    if _supports_count_tokens(model_id):
        try:
            import boto3

            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.count_tokens(
                modelId=model_id,
                input={
                    "converse": {
                        "messages": [
                            {
                                "role": "user",
                                "content": [{"text": prompt}],
                            }
                        ],
                    }
                },
            )
            token_count = response.get("inputTokens", 0)
            if token_count > 0:
                logger.info("Input tokens via CountTokens API: %d (model=%s)", token_count, model_id)
                return token_count
        except Exception as e:
            logger.warning("CountTokens API failed for input (model=%s): %s", model_id, e)

    fallback = max(1, len(prompt) // 4)
    logger.info("Input tokens via heuristic (4 chars/token): %d (model=%s)", fallback, model_id)
    return fallback


def count_output_tokens(
    model_id: str,
    output_text: str,
    region: str = "us-east-1",
) -> int:
    """Count the number of tokens in agent output using the Bedrock CountTokens API.

    Passes the output text as a user message to ``count_tokens`` since the API
    returns ``inputTokens`` for whatever content is provided.

    Args:
        model_id: Bedrock model ID.
        output_text: The agent's response text.
        region: AWS region name.

    Returns:
        Token count for the output. Falls back to ``len(output_text) // 4`` on error.
    """
    if not output_text:
        return 1

    if _supports_count_tokens(model_id):
        try:
            import boto3

            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.count_tokens(
                modelId=model_id,
                input={
                    "converse": {
                        "messages": [
                            {
                                "role": "user",
                                "content": [{"text": output_text}],
                            }
                        ],
                    }
                },
            )
            token_count = response.get("inputTokens", 0)
            if token_count > 0:
                logger.info("Output tokens via CountTokens API: %d (model=%s)", token_count, model_id)
                return token_count
        except Exception as e:
            logger.warning("CountTokens API failed for output (model=%s): %s", model_id, e)

    fallback = max(1, len(output_text) // 4)
    logger.info("Output tokens via heuristic (4 chars/token): %d (model=%s)", fallback, model_id)
    return fallback
