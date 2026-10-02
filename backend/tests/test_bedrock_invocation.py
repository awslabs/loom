"""Tests for app.services.bedrock_invocation (#64 R1: dual-endpoint
serverless inference resolution and invocation)."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.bedrock_invocation import (
    BEDROCK_MANTLE,
    BEDROCK_RUNTIME,
    UnsupportedModelEndpointError,
    assert_model_supports_endpoint,
    invoke_model,
    resolve_model_target,
)

RUNTIME_ONLY_ENTRY = {
    "model_id": "us.anthropic.claude-sonnet-4-6",
    "endpoints": [BEDROCK_RUNTIME, BEDROCK_MANTLE],
    "apis": {
        BEDROCK_RUNTIME: ["converse", "invoke", "messages"],
        BEDROCK_MANTLE: ["messages"],
    },
}

MANTLE_ONLY_ENTRY = {
    "model_id": "google.gemma-4-31b",
    "endpoints": [BEDROCK_MANTLE],
    "apis": {BEDROCK_MANTLE: ["chat_completions", "responses"]},
}

LEGACY_ENTRY_NO_METADATA = {
    "model_id": "meta.llama3-3-70b-instruct-v1:0",
    "display_name": "Llama 3.3 70B Instruct",
}

CATALOG = [RUNTIME_ONLY_ENTRY, MANTLE_ONLY_ENTRY, LEGACY_ENTRY_NO_METADATA]


class TestResolveModelTarget(unittest.TestCase):
    def test_defaults_to_first_supported_endpoint_and_preferred_api(self):
        target = resolve_model_target(RUNTIME_ONLY_ENTRY["model_id"], CATALOG, "us-east-1")
        self.assertEqual(target.endpoint, BEDROCK_RUNTIME)
        self.assertEqual(target.api, "converse")
        self.assertEqual(target.invoke_model_id, RUNTIME_ONLY_ENTRY["model_id"])

    def test_mantle_only_model_resolves_to_mantle(self):
        target = resolve_model_target(MANTLE_ONLY_ENTRY["model_id"], CATALOG, "us-east-1")
        self.assertEqual(target.endpoint, BEDROCK_MANTLE)
        self.assertEqual(target.api, "chat_completions")

    def test_preferred_endpoint_honored(self):
        target = resolve_model_target(
            RUNTIME_ONLY_ENTRY["model_id"], CATALOG, "us-east-1", preferred_endpoint=BEDROCK_MANTLE
        )
        self.assertEqual(target.endpoint, BEDROCK_MANTLE)
        self.assertEqual(target.api, "messages")

    def test_unsupported_endpoint_raises(self):
        with self.assertRaises(UnsupportedModelEndpointError):
            resolve_model_target(
                MANTLE_ONLY_ENTRY["model_id"], CATALOG, "us-east-1", preferred_endpoint=BEDROCK_RUNTIME
            )

    def test_unknown_model_raises(self):
        with self.assertRaises(UnsupportedModelEndpointError):
            resolve_model_target("nonexistent.model", CATALOG, "us-east-1")

    def test_legacy_entry_without_metadata_falls_back_to_runtime_converse(self):
        target = resolve_model_target(LEGACY_ENTRY_NO_METADATA["model_id"], CATALOG, "us-east-1")
        self.assertEqual(target.endpoint, BEDROCK_RUNTIME)
        self.assertEqual(target.api, "converse")

    def test_endpoint_model_id_override(self):
        entry = {
            "model_id": "openai.gpt-oss-120b-1:0",
            "endpoints": [BEDROCK_RUNTIME, BEDROCK_MANTLE],
            "apis": {BEDROCK_RUNTIME: ["chat_completions"], BEDROCK_MANTLE: ["responses"]},
            "endpoint_model_ids": {BEDROCK_MANTLE: "openai.gpt-oss-120b"},
        }
        target = resolve_model_target(entry["model_id"], [entry], "us-east-1", preferred_endpoint=BEDROCK_MANTLE)
        self.assertEqual(target.invoke_model_id, "openai.gpt-oss-120b")
        self.assertEqual(target.catalog_model_id, "openai.gpt-oss-120b-1:0")


class TestAssertModelSupportsEndpoint(unittest.TestCase):
    def test_passes_for_supported_endpoint(self):
        assert_model_supports_endpoint(RUNTIME_ONLY_ENTRY["model_id"], CATALOG, BEDROCK_RUNTIME)

    def test_raises_for_mantle_only_model_on_runtime(self):
        with self.assertRaises(UnsupportedModelEndpointError):
            assert_model_supports_endpoint(MANTLE_ONLY_ENTRY["model_id"], CATALOG, BEDROCK_RUNTIME)

    def test_unknown_model_is_not_validated(self):
        # Dynamically-discovered (LiteLLM/live-Bedrock) models aren't in the
        # curated catalog — nothing to validate against, so this must not raise.
        assert_model_supports_endpoint("some.dynamic.model", CATALOG, BEDROCK_RUNTIME)


class TestInvokeModel(unittest.TestCase):
    @patch("boto3.client")
    def test_invoke_runtime_converse(self, mock_boto_client):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "hello there"}]}}
        }
        mock_boto_client.return_value = mock_client

        result = invoke_model(
            RUNTIME_ONLY_ENTRY["model_id"],
            CATALOG,
            [{"role": "user", "content": "hi"}],
            region="us-east-1",
            max_tokens=100,
        )

        self.assertEqual(result["content"], "hello there")
        self.assertEqual(result["endpoint"], BEDROCK_RUNTIME)
        self.assertEqual(result["api"], "converse")
        mock_client.converse.assert_called_once()
        kwargs = mock_client.converse.call_args.kwargs
        self.assertEqual(kwargs["modelId"], RUNTIME_ONLY_ENTRY["model_id"])
        self.assertEqual(kwargs["inferenceConfig"], {"maxTokens": 100})

    @patch("app.services.bedrock_invocation._sign_mantle_request")
    @patch("urllib.request.urlopen")
    def test_invoke_mantle_chat_completions(self, mock_urlopen, mock_sign):
        mock_sign.return_value = {"Authorization": "AWS4-HMAC-SHA256 ..."}
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"choices": [{"message": {"content": "hi from mantle"}}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = invoke_model(
            MANTLE_ONLY_ENTRY["model_id"],
            CATALOG,
            [{"role": "user", "content": "hi"}],
            region="us-east-1",
        )

        self.assertEqual(result["content"], "hi from mantle")
        self.assertEqual(result["endpoint"], BEDROCK_MANTLE)
        self.assertEqual(result["api"], "chat_completions")
        request_sent = mock_urlopen.call_args.args[0]
        self.assertIn("bedrock-mantle.us-east-1.api.aws", request_sent.full_url)


if __name__ == "__main__":
    unittest.main()
