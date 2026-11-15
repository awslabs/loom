"""SSRF guarding of the backend's calls to the LiteLLM proxy.

Every request the backend makes to the proxy carries the master key, so the
proxy base URL must never reach loopback, link-local or metadata addresses,
must not be able to aim the request at an arbitrary path, and must not let a
redirect forward the key to another host. These tests drive the real
net_guard code with DNS and the HTTP client faked, so they fail if any of the
calls go back to a raw httpx request.
"""
import socket
import unittest
from unittest.mock import MagicMock, patch

from app.services.litellm import (
    check_proxy_base_url_shape,
    revoke_virtual_key,
    vend_virtual_key,
)
from app.services.model_catalog import _fetch_litellm_catalog, _fetch_litellm_proxy_catalog
from app.services.net_guard import SSRFBlockedError


def _resolve_to(ip: str):
    return patch(
        "socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))],
    )


def _env_proxy(base_url: str):
    """Configure the env-var tier (deployer-supplied, never save-validated)."""
    return patch.dict("os.environ", {
        "LOOM_LITELLM_PROXY_BASE_URL": base_url,
        "LOOM_LITELLM_DISCOVERY_BASE_URL": "",
        "LOOM_LITELLM_PROXY_API_KEY": "sk-master",
    })


class _ClientFake:
    """Patches httpx.Client so net_guard's send() is observable."""

    def __init__(self, response: MagicMock) -> None:
        self.patcher = patch("httpx.Client")
        self.response = response
        self.client = MagicMock()

    def __enter__(self) -> MagicMock:
        client_cls = self.patcher.start()
        client_cls.return_value.__enter__.return_value = self.client
        self.client.send.return_value = self.response
        return self.client

    def __exit__(self, *exc: object) -> None:
        self.patcher.stop()


def _ok(json_body: dict) -> MagicMock:
    response = MagicMock(status_code=200, is_redirect=False)
    response.json.return_value = json_body
    return response


@patch("app.services.litellm._setting", return_value="")
class TestRequestTimeGuard(unittest.TestCase):
    def test_vend_refuses_blocked_targets_without_connecting(self, _setting) -> None:
        for ip in ("127.0.0.1", "169.254.169.254", "169.254.170.2", "0.0.0.1", "fd00:ec2::254"):
            with self.subTest(ip=ip), _env_proxy("http://litellm.internal:4000"), \
                    patch("socket.getaddrinfo", return_value=[
                        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)),
                    ]), _ClientFake(_ok({"key": "sk-virtual"})) as client:
                self.assertIsNone(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()))
                client.send.assert_not_called()

    def test_vend_reaches_vpc_internal_proxy_pinned_to_validated_ip(self, _setting) -> None:
        with _env_proxy("http://litellm.internal:4000"), _resolve_to("10.0.0.5"), \
                _ClientFake(_ok({"key": "sk-virtual"})) as client:
            self.assertEqual(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()), "sk-virtual")
        sent = [c.args[0] for c in client.send.call_args_list]
        # revoke (/key/delete) runs first so vending is idempotent, then /key/generate.
        self.assertEqual([r.url.path for r in sent], ["/key/delete", "/key/generate"])
        for request in sent:
            self.assertEqual(request.url.host, "10.0.0.5")
            self.assertEqual(request.headers["host"], "litellm.internal")
            self.assertEqual(request.headers["authorization"], "Bearer sk-master")

    def test_vend_does_not_follow_redirects(self, _setting) -> None:
        redirect = MagicMock(status_code=302, is_redirect=True, headers={"location": "https://evil.example/"})
        redirect.raise_for_status.side_effect = Exception("302")
        with _env_proxy("http://litellm.internal:4000"), _resolve_to("10.0.0.5"), \
                _ClientFake(redirect) as client:
            self.assertIsNone(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()))
        # One send for /key/delete, one for /key/generate — neither follows the 302.
        self.assertEqual(client.send.call_count, 2)
        for call in client.send.call_args_list:
            self.assertEqual(call.args[0].url.host, "10.0.0.5")

    def test_env_tier_url_with_query_cannot_retarget_the_path(self, _setting) -> None:
        """The env tier is never save-validated, so the request-time shape check
        is what stops `http://host/admin?` turning /key/generate into a query."""
        for base in ("http://litellm.internal:4000/admin?", "http://litellm.internal:4000/admin#",
                     "http://user:pw@litellm.internal:4000"):
            with self.subTest(base=base), _env_proxy(base), _resolve_to("10.0.0.5"), \
                    _ClientFake(_ok({"key": "sk-virtual"})) as client:
                self.assertIsNone(vend_virtual_key(1, "agent", ["gpt-4o"], MagicMock()))
                revoke_virtual_key("loom-agent-1", MagicMock())
                client.send.assert_not_called()

    def test_revoke_refuses_blocked_target_without_connecting(self, _setting) -> None:
        with _env_proxy("http://litellm.internal:4000"), _resolve_to("127.0.0.1"), \
                _ClientFake(_ok({})) as client:
            revoke_virtual_key("loom-agent-1", MagicMock())  # must not raise
            client.send.assert_not_called()

    def test_model_discovery_refuses_blocked_target_without_connecting(self, _setting) -> None:
        with patch("app.services.litellm.get_litellm_proxy_config",
                   return_value=("http://litellm.internal:4000", "sk-master")), \
                _resolve_to("169.254.170.2"), _ClientFake(_ok({"data": []})) as client:
            self.assertIsNone(_fetch_litellm_proxy_catalog())
            client.send.assert_not_called()

    def test_model_discovery_reaches_vpc_internal_proxy(self, _setting) -> None:
        body = {"data": [{"model_name": "gpt-4o", "model_info": {"mode": "chat"}}]}
        with patch("app.services.litellm.get_litellm_proxy_config",
                   return_value=("http://litellm.internal:4000", "sk-master")), \
                _resolve_to("10.0.0.5"), _ClientFake(_ok(body)) as client:
            self.assertEqual(list(_fetch_litellm_proxy_catalog() or {}), ["gpt-4o"])
        request = client.send.call_args.args[0]
        self.assertEqual((request.url.host, request.url.path), ("10.0.0.5", "/model/info"))


class TestPricingCatalogGuard(unittest.TestCase):
    """The pricing catalog is a public HTTPS document: strict guard."""

    def test_refuses_http_and_private_targets(self) -> None:
        for url, ip in (("http://pricing.example.com/p.json", "93.184.216.34"),
                        ("https://pricing.internal/p.json", "10.0.0.5"),
                        ("https://pricing.internal/p.json", "100.64.0.10")):
            with self.subTest(url=url, ip=ip), patch.dict("os.environ", {"LOOM_LITELLM_PRICING_URL": url}), \
                    _resolve_to(ip), _ClientFake(_ok({"m": {}})) as client:
                self.assertIsNone(_fetch_litellm_catalog())
                client.send.assert_not_called()

    def test_fetches_public_https_target(self) -> None:
        with patch.dict("os.environ", {"LOOM_LITELLM_PRICING_URL": "https://pricing.example.com/p.json"}), \
                _resolve_to("93.184.216.34"), _ClientFake(_ok({"m": {}})) as client:
            self.assertEqual(_fetch_litellm_catalog(), {"m": {}})
        self.assertEqual(client.send.call_args.args[0].url.host, "93.184.216.34")


class TestShapeCheck(unittest.TestCase):
    def test_allows_bare_urls(self) -> None:
        for url in ("http://litellm.internal:4000", "https://proxy.example.com/litellm/",
                    "http://10.0.0.5"):
            with self.subTest(url=url):
                check_proxy_base_url_shape(url)

    def test_rejects_everything_else(self) -> None:
        for url in ("http://h/?", "http://h/#", "http://h/x?y=1", "http://u@h", "http://u:p@h",
                    "http://h\\@evil", "http://h/a;b", "http://h /", "http://h/\n", "ftp://h",
                    "file:///etc/passwd", "h:4000", "http://", ""):
            with self.subTest(url=url), self.assertRaises(SSRFBlockedError):
                check_proxy_base_url_shape(url)


if __name__ == "__main__":
    unittest.main()
