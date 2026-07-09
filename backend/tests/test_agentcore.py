"""
Unit tests for Bedrock AgentCore Runtime API wrapper.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
from app.services.agentcore import (
    describe_runtime,
    list_runtime_endpoints,
    invoke_agent
)


class TestDescribeRuntime(unittest.TestCase):
    """Test suite for describe_runtime function."""

    @patch('boto3.client')
    def test_describe_runtime_success(self, mock_boto_client: MagicMock) -> None:
        """Test successful runtime description."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime-abc123'
        expected_response = {
            'agentRuntimeId': 'test-runtime-abc123',
            'agentRuntimeName': 'Test Runtime',
            'status': 'READY',
            'createdAt': '2026-02-11T10:00:00Z'
        }

        mock_agentcore_client.get_agent_runtime.return_value = expected_response

        result = describe_runtime(arn, 'us-east-1')

        self.assertEqual(result, expected_response)
        mock_agentcore_client.get_agent_runtime.assert_called_once_with(
            agentRuntimeId='test-runtime-abc123'
        )

    @patch('boto3.client')
    def test_describe_runtime_extracts_id_from_arn(self, mock_boto_client: MagicMock) -> None:
        """Test that runtime ID is correctly extracted from ARN."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        arn = 'arn:aws:bedrock-agentcore:eu-west-1:987654321098:runtime/my-agent-xyz789'
        mock_agentcore_client.get_agent_runtime.return_value = {'agentRuntimeId': 'my-agent-xyz789'}

        describe_runtime(arn, 'eu-west-1')

        mock_agentcore_client.get_agent_runtime.assert_called_once_with(
            agentRuntimeId='my-agent-xyz789'
        )

    @patch('boto3.client')
    def test_describe_runtime_raises_on_not_found(self, mock_boto_client: MagicMock) -> None:
        """Test that exceptions are propagated when runtime is not found."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/nonexistent'
        mock_agentcore_client.get_agent_runtime.side_effect = Exception("Runtime not found")

        with self.assertRaises(Exception) as context:
            describe_runtime(arn, 'us-east-1')

        self.assertIn("Runtime not found", str(context.exception))


class TestListRuntimeEndpoints(unittest.TestCase):
    """Test suite for list_runtime_endpoints function."""

    @patch('boto3.client')
    def test_list_runtime_endpoints_success(self, mock_boto_client: MagicMock) -> None:
        """Test successful endpoint listing."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.list_agent_runtime_endpoints.return_value = {
            'runtimeEndpoints': [
                {'name': 'DEFAULT', 'id': 'ep-1', 'status': 'READY'},
                {'name': 'PROD', 'id': 'ep-2', 'status': 'READY'}
            ]
        }

        result = list_runtime_endpoints('test-runtime-123', 'us-east-1')

        self.assertEqual(result, ['DEFAULT', 'PROD'])

    @patch('boto3.client')
    def test_list_runtime_endpoints_empty_response(self, mock_boto_client: MagicMock) -> None:
        """Test handling of empty endpoint list."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.list_agent_runtime_endpoints.return_value = {'runtimeEndpoints': []}

        result = list_runtime_endpoints('test-runtime-123', 'us-east-1')

        self.assertEqual(result, ['DEFAULT'])

    @patch('boto3.client')
    def test_list_runtime_endpoints_no_endpoints_key(self, mock_boto_client: MagicMock) -> None:
        """Test handling of response without runtimeEndpoints key."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.list_agent_runtime_endpoints.return_value = {}

        result = list_runtime_endpoints('test-runtime-123', 'us-east-1')

        self.assertEqual(result, ['DEFAULT'])

    @patch('boto3.client')
    def test_list_runtime_endpoints_fallback_on_error(self, mock_boto_client: MagicMock) -> None:
        """Test fallback to DEFAULT when API call fails."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.list_agent_runtime_endpoints.side_effect = Exception("API error")

        result = list_runtime_endpoints('test-runtime-123', 'us-east-1')

        self.assertEqual(result, ['DEFAULT'])

    @patch('boto3.client')
    def test_list_runtime_endpoints_handles_missing_name(self, mock_boto_client: MagicMock) -> None:
        """Test handling of endpoints without name field."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.list_agent_runtime_endpoints.return_value = {
            'runtimeEndpoints': [
                {'name': 'PROD', 'id': 'ep-1'},
                {'id': 'ep-2', 'status': 'READY'}  # Missing 'name'
            ]
        }

        result = list_runtime_endpoints('test-runtime-123', 'us-east-1')

        # Should only include endpoint with valid name field
        self.assertEqual(result, ['PROD'])


class TestInvokeAgent(unittest.TestCase):
    """Test suite for invoke_agent function."""

    @patch('boto3.client')
    def test_invoke_agent_parses_sse_tokens(self, mock_boto_client: MagicMock) -> None:
        """Test agent invocation parsing SSE-formatted StreamingBody."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        # Agent response is SSE-formatted: data: "token"\n per line
        mock_streaming_body = MagicMock()
        mock_streaming_body.iter_lines.return_value = [
            b'data: "Hello "',
            b'',
            b'data: "world"',
            b'',
            b'data: "!"',
        ]

        mock_agentcore_client.invoke_agent_runtime.return_value = {
            'response': mock_streaming_body,
            'statusCode': 200,
        }

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime'
        chunks = list(invoke_agent(arn, 'DEFAULT', 'session-123', 'test prompt', 'us-east-1'))

        self.assertEqual(chunks, [
            {"type": "text", "content": "Hello "},
            {"type": "text", "content": "world"},
            {"type": "text", "content": "!"},
        ])

    @patch('boto3.client')
    def test_invoke_agent_skips_empty_lines(self, mock_boto_client: MagicMock) -> None:
        """Test that blank lines and empty data payloads are skipped."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_streaming_body = MagicMock()
        mock_streaming_body.iter_lines.return_value = [
            b'',
            b'data: ""',
            b'data: "Content"',
            b'',
        ]

        mock_agentcore_client.invoke_agent_runtime.return_value = {
            'response': mock_streaming_body,
            'statusCode': 200,
        }

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime'
        chunks = list(invoke_agent(arn, 'DEFAULT', 'session-789', 'prompt', 'us-east-1'))

        self.assertEqual(chunks, [{"type": "text", "content": "Content"}])

    @patch('boto3.client')
    def test_invoke_agent_no_response_key(self, mock_boto_client: MagicMock) -> None:
        """Test handling when response key is missing."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.invoke_agent_runtime.return_value = {
            'statusCode': 200,
        }

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime'
        chunks = list(invoke_agent(arn, 'DEFAULT', 'session-456', 'prompt', 'us-east-1'))

        self.assertEqual(chunks, [])

    @patch('boto3.client')
    def test_invoke_agent_raw_text_fallback(self, mock_boto_client: MagicMock) -> None:
        """Test that non-JSON data payloads are yielded as raw text."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_streaming_body = MagicMock()
        mock_streaming_body.iter_lines.return_value = [
            b'data: not-json-text',
        ]

        mock_agentcore_client.invoke_agent_runtime.return_value = {
            'response': mock_streaming_body,
            'statusCode': 200,
        }

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime'
        chunks = list(invoke_agent(arn, 'DEFAULT', 'session-raw', 'prompt', 'us-east-1'))

        self.assertEqual(chunks, [{"type": "text", "content": "not-json-text"}])

    @patch('boto3.client')
    def test_invoke_agent_sends_correct_parameters(self, mock_boto_client: MagicMock) -> None:
        """Test that invoke_agent sends correct parameters to AWS API."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_streaming_body = MagicMock()
        mock_streaming_body.iter_lines.return_value = []
        mock_agentcore_client.invoke_agent_runtime.return_value = {
            'response': mock_streaming_body,
            'statusCode': 200,
        }

        arn = 'arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my-agent'
        qualifier = 'PROD'
        session_id = 'unique-session-id'
        prompt = 'Test prompt text'
        region = 'us-west-2'

        list(invoke_agent(arn, qualifier, session_id, prompt, region))

        mock_agentcore_client.invoke_agent_runtime.assert_called_once()
        call_kwargs = mock_agentcore_client.invoke_agent_runtime.call_args[1]

        self.assertEqual(call_kwargs['agentRuntimeArn'], arn)
        self.assertEqual(call_kwargs['qualifier'], qualifier)
        self.assertEqual(call_kwargs['runtimeSessionId'], session_id)
        self.assertEqual(call_kwargs['contentType'], 'application/json')
        self.assertEqual(call_kwargs['accept'], 'application/json')

        # Check payload is correctly formatted JSON bytes
        payload = json.loads(call_kwargs['payload'])
        self.assertEqual(payload['prompt'], prompt)
        self.assertIsInstance(call_kwargs['payload'], bytes)

    @patch('boto3.client')
    def test_invoke_agent_yields_structured_for_dict_payloads(self, mock_boto_client: MagicMock) -> None:
        """Test that dict payloads are yielded as structured type."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_streaming_body = MagicMock()
        mock_streaming_body.iter_lines.return_value = [
            b'data: {"thinking": "reasoning about the question"}',
            b'data: "answer text"',
        ]

        mock_agentcore_client.invoke_agent_runtime.return_value = {
            'response': mock_streaming_body,
            'statusCode': 200,
        }

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime'
        chunks = list(invoke_agent(arn, 'DEFAULT', 'session-struct', 'prompt', 'us-east-1'))

        self.assertEqual(chunks, [
            {"type": "structured", "content": {"thinking": "reasoning about the question"}},
            {"type": "text", "content": "answer text"},
        ])

    @patch('boto3.client')
    def test_invoke_agent_propagates_api_errors(self, mock_boto_client: MagicMock) -> None:
        """Test that API errors are propagated to the caller."""
        mock_agentcore_client = MagicMock()
        mock_boto_client.return_value = mock_agentcore_client

        mock_agentcore_client.invoke_agent_runtime.side_effect = Exception("Agent not available")

        arn = 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test'

        with self.assertRaises(Exception) as context:
            list(invoke_agent(arn, 'DEFAULT', 'session', 'prompt', 'us-east-1'))

        self.assertIn("Agent not available", str(context.exception))


if __name__ == '__main__':
    unittest.main()
