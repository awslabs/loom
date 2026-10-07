"""Credential provider names must not be overwritable across groups.

Credential provider names live in one flat namespace per AWS account, shared by
every loom:group. Two things combined to make that a cross-group write:

1. Names were derived from caller-controlled strings only —
   `loom-{agent name}-mcp-{server name}`, `loom-{agent name}-litellm-key`, or,
   from `POST /credential-providers`, the raw `request.name`. Any group could
   therefore name another group's provider.
2. On `ValidationException: ... already exists`, the service logged "updating
   instead" and called `update_*_credential_provider` with the caller's own
   `clientSecret` / `apiKey`.

So an operator in group A could create an agent whose derived provider name
collided with group B's and silently replace the client secret group B's agents
authenticate with.

The fix is both halves: names are keyed on the server-assigned agent id so they
cannot be aimed at another group's provider, and the update-on-collision path
is off unless a caller explicitly opts in — which only the deploy paths do, and
only because the id in the name means the collision must be their own leftover.
"""
import unittest
from unittest.mock import MagicMock, patch

from app.services.credential import (
    CredentialProviderNameInUse,
    create_api_key_credential_provider,
    create_oauth2_credential_provider,
    credential_provider_name,
)


class _AlreadyExists(Exception):
    """Stands in for botocore's generated ValidationException."""


def _fake_client() -> MagicMock:
    """A bedrock-agentcore-control client whose creates always collide."""
    client = MagicMock()
    client.exceptions.ValidationException = _AlreadyExists
    client.create_oauth2_credential_provider.side_effect = _AlreadyExists(
        "A credential provider with name loom-victim-mcp-github already exists"
    )
    client.create_api_key_credential_provider.side_effect = _AlreadyExists(
        "A credential provider with name loom-victim-litellm-key already exists"
    )
    return client


class TestNameCollisionFailsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _fake_client()
        patcher = patch("boto3.client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create_oauth2(self, **overrides):
        kwargs = dict(
            name="loom-victim-mcp-github",
            client_id="attacker-client",
            client_secret="ATTACKER-SECRET",  # nosec B106
            auth_server_url="https://attacker.example.com/.well-known/openid-configuration",
            region="us-east-1",
        )
        kwargs.update(overrides)
        return create_oauth2_credential_provider(**kwargs)

    def test_oauth2_collision_raises_instead_of_updating(self) -> None:
        with self.assertRaises(CredentialProviderNameInUse):
            self._create_oauth2()
        self.client.update_oauth2_credential_provider.assert_not_called()

    def test_oauth2_collision_does_not_leak_the_secret_into_an_update(self) -> None:
        """The whole point: the caller's secret must not reach the update call."""
        with self.assertRaises(CredentialProviderNameInUse):
            self._create_oauth2()
        self.assertEqual(self.client.update_oauth2_credential_provider.call_count, 0)

    def test_api_key_collision_raises_instead_of_updating(self) -> None:
        with self.assertRaises(CredentialProviderNameInUse):
            create_api_key_credential_provider(
                name="loom-victim-litellm-key",
                api_key="ATTACKER-KEY",
                region="us-east-1",
            )
        self.client.update_api_key_credential_provider.assert_not_called()

    def test_other_validation_errors_still_propagate(self) -> None:
        """Only "already exists" is special-cased; nothing else is swallowed."""
        self.client.create_oauth2_credential_provider.side_effect = _AlreadyExists(
            "clientId must not be blank"
        )
        with self.assertRaises(_AlreadyExists):
            self._create_oauth2()
        self.client.update_oauth2_credential_provider.assert_not_called()

    # -- positive controls: the deploy paths' opt-in still works --

    def test_oauth2_allow_update_still_reconciles(self) -> None:
        self.client.update_oauth2_credential_provider.return_value = {"ok": True}
        result = self._create_oauth2(allow_update=True)
        self.assertEqual(result, {"ok": True})
        self.client.update_oauth2_credential_provider.assert_called_once()

    def test_api_key_allow_update_still_reconciles(self) -> None:
        self.client.update_api_key_credential_provider.return_value = {"ok": True}
        result = create_api_key_credential_provider(
            name="loom-victim-litellm-key",
            api_key="OWN-KEY",
            region="us-east-1",
            allow_update=True,
        )
        self.assertEqual(result, {"ok": True})
        self.client.update_api_key_credential_provider.assert_called_once()

    def test_allow_update_does_not_forward_tags(self) -> None:
        """update_* rejects tags; the create kwargs must be filtered."""
        self.client.update_oauth2_credential_provider.return_value = {"ok": True}
        self._create_oauth2(allow_update=True, tags={"loom:group": "mcp"})
        _, kwargs = self.client.update_oauth2_credential_provider.call_args
        self.assertNotIn("tags", kwargs)


class TestNamesAreKeyedOnTheAgentId(unittest.TestCase):
    """Namespacing is what makes allow_update safe for the deploy paths."""

    def test_same_names_in_different_agents_do_not_collide(self) -> None:
        """The reported path: group B names its agent and MCP server to match."""
        victim = credential_provider_name(1, "payments", "mcp", "github")
        attacker = credential_provider_name(2, "payments", "mcp", "github")
        self.assertNotEqual(victim, attacker)

    def test_agent_id_is_present(self) -> None:
        self.assertEqual(
            credential_provider_name(42, "payments", "mcp", "github"),
            "loom-payments-42-mcp-github",
        )

    def test_kinds_are_separated(self) -> None:
        """An MCP server and an A2A agent of the same name stay distinct."""
        self.assertNotEqual(
            credential_provider_name(1, "a", "mcp", "shared"),
            credential_provider_name(1, "a", "a2a", "shared"),
        )

    def test_unsafe_characters_are_sanitized(self) -> None:
        """apiKeyArn's harness-side regex only allows [a-zA-Z0-9.-]."""
        name = credential_provider_name(3, "my_agent name", "mcp", "srv//one")
        self.assertEqual(name, "loom-my-agent-name-3-mcp-srv--one")

    def test_sanitizing_cannot_merge_two_agents(self) -> None:
        """`a_b` and `a-b` both sanitize to `a-b`; the id keeps them apart."""
        self.assertNotEqual(
            credential_provider_name(1, "a_b", "mcp", "s"),
            credential_provider_name(2, "a-b", "mcp", "s"),
        )


if __name__ == "__main__":
    unittest.main()
