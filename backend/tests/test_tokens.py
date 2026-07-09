"""Tests for Bedrock CountTokens service."""
import unittest
from unittest.mock import MagicMock, patch
from app.services.tokens import count_input_tokens, count_output_tokens


class TestCountInputTokens(unittest.TestCase):
    """Test suite for count_input_tokens function."""

    @patch("boto3.client")
    def test_count_input_tokens_success(self, mock_boto_client: MagicMock) -> None:
        """Test successful token counting via CountTokens API."""
        mock_runtime = MagicMock()
        mock_boto_client.return_value = mock_runtime
        mock_runtime.count_tokens.return_value = {"inputTokens": 42}

        result = count_input_tokens("us.anthropic.claude-sonnet-4-6", "Hello world", "us-east-1")

        self.assertEqual(result, 42)
        mock_runtime.count_tokens.assert_called_once()
        call_kwargs = mock_runtime.count_tokens.call_args[1]
        self.assertEqual(call_kwargs["modelId"], "us.anthropic.claude-sonnet-4-6")
        self.assertIn("converse", call_kwargs["input"])

    @patch("boto3.client")
    def test_count_input_tokens_fallback_on_error(self, mock_boto_client: MagicMock) -> None:
        """Test fallback to heuristic when API fails."""
        mock_runtime = MagicMock()
        mock_boto_client.return_value = mock_runtime
        mock_runtime.count_tokens.side_effect = Exception("API error")

        prompt = "a" * 100  # 100 chars → 25 tokens heuristic
        result = count_input_tokens("us.anthropic.claude-sonnet-4-6", prompt, "us-east-1")

        self.assertEqual(result, 25)

    @patch("boto3.client")
    def test_count_input_tokens_fallback_on_zero(self, mock_boto_client: MagicMock) -> None:
        """Test fallback when API returns 0 tokens."""
        mock_runtime = MagicMock()
        mock_boto_client.return_value = mock_runtime
        mock_runtime.count_tokens.return_value = {"inputTokens": 0}

        result = count_input_tokens("us.anthropic.claude-sonnet-4-6", "Hello", "us-east-1")

        self.assertEqual(result, max(1, len("Hello") // 4))


class TestCountOutputTokens(unittest.TestCase):
    """Test suite for count_output_tokens function."""

    @patch("boto3.client")
    def test_count_output_tokens_success(self, mock_boto_client: MagicMock) -> None:
        """Test successful output token counting."""
        mock_runtime = MagicMock()
        mock_boto_client.return_value = mock_runtime
        mock_runtime.count_tokens.return_value = {"inputTokens": 88}

        result = count_output_tokens("us.anthropic.claude-sonnet-4-6", "Some response text", "us-east-1")

        self.assertEqual(result, 88)

    @patch("boto3.client")
    def test_count_output_tokens_fallback_on_error(self, mock_boto_client: MagicMock) -> None:
        """Test fallback to heuristic when API fails."""
        mock_runtime = MagicMock()
        mock_boto_client.return_value = mock_runtime
        mock_runtime.count_tokens.side_effect = Exception("API error")

        output = "b" * 200  # 200 chars → 50 tokens heuristic
        result = count_output_tokens("us.anthropic.claude-sonnet-4-6", output, "us-east-1")

        self.assertEqual(result, 50)

    def test_count_output_tokens_empty_text(self) -> None:
        """Test that empty output returns 1 token minimum."""
        result = count_output_tokens("us.anthropic.claude-sonnet-4-6", "", "us-east-1")
        self.assertEqual(result, 1)

    def test_count_output_tokens_none_text(self) -> None:
        """Test that None-ish empty output returns 1 token minimum."""
        result = count_output_tokens("us.anthropic.claude-sonnet-4-6", "", "us-east-1")
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
