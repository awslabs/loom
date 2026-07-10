"""
Credential provider management via AgentCore APIs.

This module provides functions to create and delete OAuth2 credential providers
through the AgentCore control plane for agent integrations.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_BASE_DELAY = 2.0  # seconds


def create_oauth2_credential_provider(
    name: str,
    client_id: str,
    client_secret: str,
    auth_server_url: str,
    region: str,
    tags: dict[str, str] | None = None,
    delegation_mode: str = "m2m",
    obo_grant_type: str | None = None,
) -> dict[str, Any]:
    """
    Create an OAuth2 credential provider via the AgentCore control plane.

    Retries with exponential backoff on transient failures (e.g.
    ConflictException from Secrets Manager).

    Args:
        name: Name for the credential provider
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        auth_server_url: OAuth2 authorization server URL
        region: AWS region name
        tags: Optional dict of tags to apply to the credential provider
        delegation_mode: "m2m" (default, client_credentials) or "obo" for
            on-behalf-of token exchange.
        obo_grant_type: When delegation_mode is "obo", specifies the grant type:
            "JWT_AUTHORIZATION_GRANT" (RFC 7523, for Microsoft Entra ID) or
            "TOKEN_EXCHANGE" (RFC 8693, for Okta and others).
            Defaults to "TOKEN_EXCHANGE" if not specified.

    Returns:
        Dictionary with provider details from the API response,
        including callback_url for OAuth2 flow completion

    Raises:
        Exception: If creation fails after all retries.
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)

    custom_config: dict[str, Any] = {
        'clientId': client_id,
        'clientSecret': client_secret,
        'oauthDiscovery': {
            'discoveryUrl': auth_server_url,
        },
    }
    if delegation_mode == "obo":
        grant_type = obo_grant_type or "TOKEN_EXCHANGE"
        obo_config: dict[str, Any] = {'grantType': grant_type}
        if grant_type == "TOKEN_EXCHANGE":
            obo_config['tokenExchangeGrantTypeConfig'] = {
                'actorTokenContent': 'NONE',
            }
            custom_config['clientAuthenticationMethod'] = 'CLIENT_SECRET_BASIC'
        if grant_type == "JWT_AUTHORIZATION_GRANT":
            custom_config['clientAuthenticationMethod'] = 'CLIENT_SECRET_POST'
        custom_config['onBehalfOfTokenExchangeConfig'] = obo_config

    kwargs: dict[str, Any] = {
        'name': name,
        'credentialProviderVendor': 'CustomOauth2',
        'oauth2ProviderConfigInput': {
            'customOauth2ProviderConfig': custom_config,
        },
    }
    if tags:
        kwargs['tags'] = tags

    logger.info(
        "Creating credential provider '%s': vendor=%s, delegation_mode=%s, obo_grant_type=%s, config_keys=%s",
        name, 'CustomOauth2', delegation_mode, obo_grant_type,
        list(custom_config.keys()),
    )

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.create_oauth2_credential_provider(**kwargs)
            return response
        except client.exceptions.ValidationException as e:
            if "already exists" in str(e):
                logger.info(
                    "Credential provider '%s' already exists, updating instead",
                    name,
                )
                update_kwargs = {k: v for k, v in kwargs.items() if k != 'tags'}
                response = client.update_oauth2_credential_provider(**update_kwargs)
                return response
            raise
        except Exception as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Credential provider '%s' creation failed (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    name, attempt + 1, _MAX_RETRIES + 1, delay, e,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Credential provider '%s' creation failed after %d attempts: %s",
                    name, _MAX_RETRIES + 1, e,
                )

    raise last_exc  # type: ignore[misc]


def delete_credential_provider(provider_name: str, region: str) -> None:
    """
    Delete a credential provider.

    Args:
        provider_name: Name of the credential provider to delete
        region: AWS region name
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)
    client.delete_oauth2_credential_provider(name=provider_name)


def create_api_key_credential_provider(name: str, api_key: str, region: str) -> dict[str, Any]:
    """
    Create an API key credential provider via the AgentCore control plane.

    Used by AgentCore Harness's `liteLlmModelConfig.apiKeyArn` — the harness
    resolves the key itself at invocation time via
    bedrock-agentcore:GetResourceApiKey, so this is a distinct resource from
    Secrets Manager (which is used for non-harness LLM provider API keys).

    Args:
        name: Name for the credential provider
        api_key: The raw API key value
        region: AWS region name

    Returns:
        Dictionary with provider details from the API response, including
        `credentialProviderArn`.
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)

    try:
        return client.create_api_key_credential_provider(name=name, apiKey=api_key)
    except client.exceptions.ValidationException as e:
        if "already exists" in str(e):
            logger.info(
                "API key credential provider '%s' already exists, updating instead",
                name,
            )
            return client.update_api_key_credential_provider(name=name, apiKey=api_key)
        raise


def delete_api_key_credential_provider(provider_name: str, region: str) -> None:
    """
    Delete an API key credential provider.

    Args:
        provider_name: Name of the credential provider to delete
        region: AWS region name
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)
    client.delete_api_key_credential_provider(name=provider_name)
