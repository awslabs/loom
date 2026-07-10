"""Tests for the LiteLLM master-key resolution and virtual key vending service."""
import unittest
from unittest.mock import MagicMock, patch

from app.services.litellm import (
    get_agent_base_url,
    get_effective_config,
    get_litellm_proxy_config,
    has_master_key,
    is_enabled,
    revoke_virtual_key,
    vend_virtual_key,
)


def _settings(enabled: bool = True, agent_base_url: str = "", discovery_base_url: str = ""):
    """Return a side_effect function for app.services.litellm._setting that
    resolves the given values by SiteSetting key, independent of ORM/DB
    query-chain mocking."""
    values = {
        "litellm_enabled": "true" if enabled else "false",
        "litellm_proxy_base_url": agent_base_url,
        "litellm_discovery_base_url": discovery_base_url,
    }

    def _side_effect(db, key):
        return values.get(key, "")

    return _side_effect


class TestGetLitellmProxyConfig(unittest.TestCase):
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_settings_override_wins(self, mock_setting, mock_get_secret):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master-from-secrets"

        result = get_litellm_proxy_config(MagicMock())

        self.assertEqual(result, ("https://proxy.example.com", "sk-master-from-secrets"))
        mock_get_secret.assert_called_once()

    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_discovery_url_overrides_agent_url(self, mock_setting, mock_get_secret):
        mock_setting.side_effect = _settings(
            enabled=True, agent_base_url="https://proxy.example.com", discovery_base_url="http://localhost:4000",
        )
        mock_get_secret.return_value = "sk-master"

        result = get_litellm_proxy_config(MagicMock())

        self.assertEqual(result, ("http://localhost:4000", "sk-master"))

    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_disabled_returns_none_even_with_agent_url_set(self, mock_setting, mock_get_secret):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="https://proxy.example.com")

        self.assertIsNone(get_litellm_proxy_config(MagicMock()))
        mock_get_secret.assert_not_called()

    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_settings_override_secret_read_failure_returns_none(self, mock_setting, mock_get_secret):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.side_effect = Exception("not found")

        self.assertIsNone(get_litellm_proxy_config(MagicMock()))

    @patch("app.services.litellm._setting")
    @patch.dict(
        "os.environ",
        {"LOOM_LITELLM_PROXY_BASE_URL": "http://litellm.internal:4000", "LOOM_LITELLM_PROXY_API_KEY": "sk-env"},
    )
    def test_falls_back_to_env_vars_when_no_setting_row(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")

        result = get_litellm_proxy_config(MagicMock())

        self.assertEqual(result, ("http://litellm.internal:4000", "sk-env"))

    @patch("app.services.litellm._setting")
    @patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""}, clear=False)
    def test_returns_none_when_nothing_configured(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        self.assertIsNone(get_litellm_proxy_config(MagicMock()))

    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_has_master_key_true(self, mock_setting, mock_get_secret):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        self.assertTrue(has_master_key(MagicMock()))

    @patch("app.services.litellm._setting")
    def test_has_master_key_false(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""}):
            self.assertFalse(has_master_key(MagicMock()))


class TestVendVirtualKey(unittest.TestCase):
    @patch("httpx.post")
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_success_returns_key(self, mock_setting, mock_get_secret, mock_post):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        mock_response = MagicMock()
        mock_response.json.return_value = {"key": "sk-virtual-abc123"}
        mock_post.return_value = mock_response

        result = vend_virtual_key(42, "my-agent", ["gpt-4o"], MagicMock())

        self.assertEqual(result, "sk-virtual-abc123")
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs.args[0], "https://proxy.example.com/key/generate")
        self.assertEqual(call_kwargs.kwargs["headers"]["Authorization"], "Bearer sk-master")
        self.assertEqual(call_kwargs.kwargs["json"]["models"], ["gpt-4o"])
        self.assertEqual(call_kwargs.kwargs["json"]["key_alias"], "loom-agent-42")

    @patch("app.services.litellm._setting")
    def test_no_proxy_configured_returns_none(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""}):
            self.assertIsNone(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()))

    @patch("httpx.post")
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_request_failure_returns_none(self, mock_setting, mock_get_secret, mock_post):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        mock_post.side_effect = Exception("connection refused")

        self.assertIsNone(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()))

    @patch("httpx.post")
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_missing_key_field_returns_none(self, mock_setting, mock_get_secret, mock_post):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        mock_response = MagicMock()
        mock_response.json.return_value = {"unexpected": "shape"}
        mock_post.return_value = mock_response

        self.assertIsNone(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()))


class TestRevokeVirtualKey(unittest.TestCase):
    @patch("httpx.post")
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_success_posts_key_delete(self, mock_setting, mock_get_secret, mock_post):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        mock_post.return_value = MagicMock()

        revoke_virtual_key("loom-agent-42", MagicMock())

        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs.args[0], "https://proxy.example.com/key/delete")
        self.assertEqual(call_kwargs.kwargs["json"], {"key_aliases": ["loom-agent-42"]})

    @patch("app.services.litellm._setting")
    def test_no_proxy_configured_does_not_raise(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""}):
            revoke_virtual_key("loom-agent-1", MagicMock())  # should not raise

    @patch("httpx.post")
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_request_failure_does_not_raise(self, mock_setting, mock_get_secret, mock_post):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        mock_post.side_effect = Exception("timeout")

        revoke_virtual_key("loom-agent-1", MagicMock())  # should not raise

    @patch("httpx.post")
    @patch("app.services.secrets.get_secret")
    @patch("app.services.litellm._setting")
    def test_404_treated_as_nothing_to_revoke_not_a_failure(self, mock_setting, mock_get_secret, mock_post):
        """A first-ever deploy has no prior key under this alias — LiteLLM's
        404 here is the expected case, not an error worth raise_for_status()."""
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://proxy.example.com")
        mock_get_secret.return_value = "sk-master"
        response = MagicMock()
        response.status_code = 404
        mock_post.return_value = response

        revoke_virtual_key("loom-agent-1", MagicMock())

        response.raise_for_status.assert_not_called()


class TestEnvVarSeeding(unittest.TestCase):
    """Env vars (LOOM_LITELLM_PROXY_BASE_URL / LOOM_LITELLM_DISCOVERY_BASE_URL
    / LOOM_LITELLM_PROXY_API_KEY) seed defaults at startup — a Settings-page
    save always wins once an agent_base_url has been saved there."""

    @patch("app.services.litellm._setting")
    @patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com"})
    def test_is_enabled_true_from_env_when_no_settings_row(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        self.assertTrue(is_enabled(MagicMock()))

    @patch("app.services.litellm._setting")
    @patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""})
    def test_is_enabled_false_when_nothing_configured(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        self.assertFalse(is_enabled(MagicMock()))

    @patch("app.services.litellm._setting")
    @patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com"})
    def test_settings_override_disables_even_with_env_var_set(self, mock_setting):
        # A saved (but disabled) Settings override takes precedence over the
        # env var entirely — it doesn't fall through.
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="https://settings-alb.example.com")
        self.assertFalse(is_enabled(MagicMock()))

    @patch("app.services.litellm._setting")
    @patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com"})
    def test_get_agent_base_url_falls_back_to_env(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")
        self.assertEqual(get_agent_base_url(MagicMock()), "https://alb.example.com")

    @patch("app.services.litellm._setting")
    def test_get_agent_base_url_settings_override_wins(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=True, agent_base_url="https://settings-alb.example.com")
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com"}):
            self.assertEqual(get_agent_base_url(MagicMock()), "https://settings-alb.example.com")

    @patch("app.services.litellm._setting")
    @patch.dict(
        "os.environ",
        {
            "LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com",
            "LOOM_LITELLM_DISCOVERY_BASE_URL": "http://localhost:4000",
        },
    )
    def test_get_effective_config_reflects_env_seeded_defaults(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")

        config = get_effective_config(MagicMock())

        self.assertTrue(config["enabled"])
        self.assertEqual(config["agent_base_url"], "https://alb.example.com")
        self.assertEqual(config["discovery_base_url"], "http://localhost:4000")

    @patch("app.services.litellm._setting")
    def test_get_effective_config_reflects_settings_override(self, mock_setting):
        mock_setting.side_effect = _settings(
            enabled=True, agent_base_url="https://settings-alb.example.com", discovery_base_url="",
        )
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com"}):
            config = get_effective_config(MagicMock())

        self.assertTrue(config["enabled"])
        self.assertEqual(config["agent_base_url"], "https://settings-alb.example.com")
        self.assertEqual(config["discovery_base_url"], "")

    @patch("app.services.litellm._setting")
    @patch.dict(
        "os.environ",
        {
            "LOOM_LITELLM_PROXY_BASE_URL": "https://alb.example.com",
            "LOOM_LITELLM_DISCOVERY_BASE_URL": "http://localhost:4000",
            "LOOM_LITELLM_PROXY_API_KEY": "sk-env",
        },
    )
    def test_get_litellm_proxy_config_uses_discovery_env_var(self, mock_setting):
        mock_setting.side_effect = _settings(enabled=False, agent_base_url="")

        result = get_litellm_proxy_config(MagicMock())

        self.assertEqual(result, ("http://localhost:4000", "sk-env"))


if __name__ == "__main__":
    unittest.main()
