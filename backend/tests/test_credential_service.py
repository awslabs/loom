"""Unit tests for app/services/credential.py's API key credential provider functions."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.credential import (
    create_api_key_credential_provider,
    delete_api_key_credential_provider,
)


class TestCreateApiKeyCredentialProvider(unittest.TestCase):
    @patch("boto3.client")
    def test_creates_new_provider(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_api_key_credential_provider.return_value = {
            "name": "my-key",
            "credentialProviderArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:token-vault/default/apikeycredentialprovider/my-key",
        }

        result = create_api_key_credential_provider("my-key", "sk-secret", "us-east-1")

        mock_client.create_api_key_credential_provider.assert_called_once_with(
            name="my-key", apiKey="sk-secret",
        )
        self.assertEqual(
            result["credentialProviderArn"],
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:token-vault/default/apikeycredentialprovider/my-key",
        )

    @patch("boto3.client")
    def test_updates_existing_provider_on_conflict(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        class _ValidationException(Exception):
            pass

        mock_client.exceptions.ValidationException = _ValidationException
        mock_client.create_api_key_credential_provider.side_effect = _ValidationException(
            "Provider already exists"
        )
        mock_client.update_api_key_credential_provider.return_value = {
            "name": "my-key",
            "credentialProviderArn": "arn:cp-updated",
        }

        result = create_api_key_credential_provider("my-key", "sk-new-secret", "us-east-1")

        mock_client.update_api_key_credential_provider.assert_called_once_with(
            name="my-key", apiKey="sk-new-secret",
        )
        self.assertEqual(result["credentialProviderArn"], "arn:cp-updated")

    @patch("boto3.client")
    def test_reraises_other_validation_errors(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        class _ValidationException(Exception):
            pass

        mock_client.exceptions.ValidationException = _ValidationException
        mock_client.create_api_key_credential_provider.side_effect = _ValidationException(
            "Invalid name"
        )

        with self.assertRaises(_ValidationException):
            create_api_key_credential_provider("bad name", "sk-secret", "us-east-1")


class TestDeleteApiKeyCredentialProvider(unittest.TestCase):
    @patch("boto3.client")
    def test_deletes_provider(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        delete_api_key_credential_provider("my-key", "us-east-1")

        mock_client.delete_api_key_credential_provider.assert_called_once_with(name="my-key")


if __name__ == "__main__":
    unittest.main()
