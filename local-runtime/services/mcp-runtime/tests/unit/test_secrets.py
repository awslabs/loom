import unittest

from mcp_runtime.adapters.outbound.env_secrets import resolve_secret_refs
from mcp_runtime.domain.errors import SecretError


class TestSecrets(unittest.TestCase):
    def test_rejects_non_env_name_without_echoing_it(self) -> None:
        with self.assertRaises(SecretError) as raised:
            resolve_secret_refs(
                [{"name": "AZURE_DEVOPS_PAT", "backend": "env", "ref": "token-looking-value"}],
                [{"name": "AZURE_DEVOPS_PAT", "env": "ADO_MCP_AUTH_TOKEN"}],
            )
        self.assertIn("AZURE_DEVOPS_PAT", str(raised.exception))
        self.assertNotIn("token-looking-value", str(raised.exception))
