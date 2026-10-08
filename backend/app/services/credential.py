"""
Credential provider management via AgentCore APIs.

This module provides functions to create and delete OAuth2 credential providers
through the AgentCore control plane for agent integrations.
"""

import logging
import re
import time

from app.services.redaction import redacted_error
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_BASE_DELAY = 2.0  # seconds

# The apiKeyArn regex AgentCore Harness applies to the provider-name segment
# only allows these characters, so every provider name is built from this set.
_UNSAFE_NAME_CHARS = re.compile(r"[^a-zA-Z0-9.-]")


class CredentialProviderError(RuntimeError):
    """A credential provider call failed. Message is scrubbed of the secret."""


class CredentialProviderNameInUse(Exception):
    """A provider with this name already exists in the account's token vault.

    Raised instead of silently updating it. Credential provider names live in
    one flat per-account namespace shared by every loom:group, so an update
    triggered by a name collision would write the caller's client secret over
    whatever provider already held that name.
    """


def credential_provider_name(
    agent_id: int,
    agent_name: str,
    kind: str,
    resource_name: str | None = None,
) -> str:
    """Build a credential provider name that cannot collide across groups.

    The agent id is what makes this safe. Provider names share a single flat
    namespace per AWS account, while an agent belongs to exactly one
    loom:group, so keying the name on the server-assigned agent id means no
    caller can derive a name that lands on another group's provider. The agent
    name stays in front of it for operator readability only; it is not load
    bearing, and it is not the group name because that would push long names
    past the control plane's limit.

    Because the name is unforgeable in this way, a name collision can only ever
    be the same agent's own leftover from an earlier failed deploy — which is
    why the deploy paths, and only the deploy paths, may pass allow_update.
    """
    segments = [f"loom-{_UNSAFE_NAME_CHARS.sub('-', agent_name or '')}-{agent_id}", kind]
    if resource_name:
        segments.append(_UNSAFE_NAME_CHARS.sub("-", resource_name))
    return "-".join(segments)


def create_oauth2_credential_provider(
    name: str,
    client_id: str,
    client_secret: str,
    auth_server_url: str,
    region: str,
    tags: dict[str, str] | None = None,
    delegation_mode: str = "m2m",
    obo_grant_type: str | None = None,
    allow_update: bool = False,
) -> dict[str, Any]:
    """
    Create an OAuth2 credential provider via the AgentCore control plane.

    Retries with exponential backoff on transient failures (e.g.
    ConflictException from Secrets Manager).

    Args:
        name: Name for the credential provider. Build it with
            credential_provider_name() so it embeds the agent id.
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
        allow_update: Whether to overwrite an existing provider of the same
            name instead of failing. Only safe for callers whose name came
            from credential_provider_name(), where a collision can only be
            the same agent's own leftover.

    Returns:
        Dictionary with provider details from the API response,
        including callback_url for OAuth2 flow completion

    Raises:
        CredentialProviderNameInUse: If the name is taken and allow_update is
            False.
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

    last_exc: str | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.create_oauth2_credential_provider(**kwargs)
            return response
        except client.exceptions.ValidationException as e:
            if "already exists" in str(e):
                if not allow_update:
                    raise CredentialProviderNameInUse(
                        f"A credential provider named '{name}' already exists and "
                        "will not be overwritten"
                    ) from e
                logger.info(
                    "Credential provider '%s' already exists, updating instead",
                    name,
                )
                update_kwargs = {k: v for k, v in kwargs.items() if k != 'tags'}
                response = client.update_oauth2_credential_provider(**update_kwargs)
                return response
            raise
        except Exception as e:
            # kwargs carried clientSecret, and AWS validation errors can echo
            # an offending parameter back, so the message is scrubbed before
            # it is logged or re-raised. Callers across agents.py log this
            # exception on the deploy path.
            last_exc = redacted_error(e, client_secret)
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Credential provider '%s' creation failed (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    name, attempt + 1, _MAX_RETRIES + 1, delay, last_exc,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Credential provider '%s' creation failed after %d attempts: %s",
                    name, _MAX_RETRIES + 1, last_exc,
                )

    raise CredentialProviderError(
        f"Credential provider '{name}' creation failed: {last_exc}"
    ) from None


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


def create_api_key_credential_provider(
    name: str,
    api_key: str,
    region: str,
    allow_update: bool = False,
) -> dict[str, Any]:
    """
    Create an API key credential provider via the AgentCore control plane.

    Used by AgentCore Harness's `liteLlmModelConfig.apiKeyArn` — the harness
    resolves the key itself at invocation time via
    bedrock-agentcore:GetResourceApiKey, so this is a distinct resource from
    Secrets Manager (which is used for non-harness LLM provider API keys).

    Args:
        name: Name for the credential provider. Build it with
            credential_provider_name() so it embeds the agent id.
        api_key: The raw API key value
        region: AWS region name
        allow_update: Whether to overwrite an existing provider of the same
            name instead of failing. See create_oauth2_credential_provider.

    Returns:
        Dictionary with provider details from the API response, including
        `credentialProviderArn`.

    Raises:
        CredentialProviderNameInUse: If the name is taken and allow_update is
            False.
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)

    try:
        return _create_api_key_provider(client, name, api_key, allow_update)
    except client.exceptions.ValidationException:
        raise
    except CredentialProviderNameInUse:
        raise
    except Exception as e:
        raise CredentialProviderError(
            f"API key credential provider '{name}' creation failed: "
            f"{redacted_error(e, api_key)}"
        ) from None


def _create_api_key_provider(client, name: str, api_key: str, allow_update: bool) -> dict[str, Any]:
    try:
        return client.create_api_key_credential_provider(name=name, apiKey=api_key)
    except client.exceptions.ValidationException as e:
        if "already exists" in str(e):
            if not allow_update:
                raise CredentialProviderNameInUse(
                    f"An API key credential provider named '{name}' already exists "
                    "and will not be overwritten"
                ) from e
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
