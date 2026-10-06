"""The local-dev auth bypass must stay unreachable from a deployment.

``get_current_user`` returns every scope, unauthenticated, when neither
Cognito nor an external IdP is configured and two further conditions hold: the
``LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV`` opt-in, and a loopback client. That
combination is a deliberate development convenience, but the no-IdP
precondition is also the state of a fresh deployment that intends to use an
external IdP and has not registered it yet — so the two remaining gates are
all that stand between such a deployment and an open admin panel.

Neither gate was robust on its own. The opt-in is a boolean someone can leave
in a task definition, and the loopback check reads ``request.client``, which
uvicorn derives from ``X-Forwarded-For`` whenever ``FORWARDED_ALLOW_IPS`` is
widened past loopback. These tests cover the two defences added for that:
refusing to start in a deployment, and refusing the bypass for any request
carrying proxy forwarding headers.
"""
import os
import unittest
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.dependencies.auth import (
    LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV,
    _bypass_allowed_for_request,
    assert_local_dev_bypass_not_deployed,
    get_current_user,
)


@pytest.fixture(autouse=True)
def _default_auth_bypass():
    """Override the suite-wide auto-bypass fixture.

    It forces ``_is_loopback_request`` to return True for every request, which
    is right for the bulk of the suite but would defeat the point here: this
    module is testing the bypass preconditions themselves and needs to see the
    real implementation.
    """
    yield


def _request(client: tuple[str, int] | None, headers: dict[str, str] | None = None) -> Request:
    """Build a bare ASGI request with a chosen client address and headers."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": client,
    }
    return Request(scope)


class TestForwardedHeadersCannotForgeLoopback(unittest.TestCase):
    """A spoofed X-Forwarded-For must not make a remote caller look local."""

    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_genuine_loopback_request_is_allowed(self) -> None:
        self.assertTrue(_bypass_allowed_for_request(_request(("127.0.0.1", 5000))))

    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_loopback_client_carrying_forwarded_for_is_refused(self) -> None:
        """The exact spoof: uvicorn has already rewritten client to 127.0.0.1
        from a forged X-Forwarded-For, which is what happens when
        FORWARDED_ALLOW_IPS is widened past loopback. The header survives that
        rewrite and is the tell."""
        request = _request(("127.0.0.1", 5000), {"X-Forwarded-For": "127.0.0.1"})
        self.assertFalse(_bypass_allowed_for_request(request))

    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_every_forwarding_header_is_enough_to_refuse(self) -> None:
        for header in (
            "X-Forwarded-For",
            "X-Forwarded-Host",
            "X-Forwarded-Proto",
            "X-Real-IP",
            "Forwarded",
        ):
            with self.subTest(header=header):
                request = _request(("127.0.0.1", 5000), {header: "127.0.0.1"})
                self.assertFalse(_bypass_allowed_for_request(request))

    @patch.dict(os.environ, {}, clear=True)
    def test_loopback_alone_is_not_enough_without_the_opt_in(self) -> None:
        self.assertFalse(_bypass_allowed_for_request(_request(("127.0.0.1", 5000))))

    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_non_loopback_client_is_refused(self) -> None:
        self.assertFalse(_bypass_allowed_for_request(_request(("10.0.1.55", 44321))))

    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_missing_client_is_refused(self) -> None:
        self.assertFalse(_bypass_allowed_for_request(_request(None)))


class TestEndToEndSpoofIsRejected(unittest.TestCase):
    """The same spoof through a real dependency resolution, not just the helper."""

    def setUp(self) -> None:
        app = FastAPI()

        @app.get("/whoami")
        def whoami(user=__import__("fastapi").Depends(get_current_user)):  # noqa: B008
            return {"username": user.username, "scopes": sorted(user.scopes)}

        self.app = app

    @patch("app.dependencies.auth._get_active_idp_cached", return_value=None)
    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_spoofed_forwarded_for_gets_401_not_super_admin(self, _mock_idp) -> None:
        client = TestClient(self.app, client=("127.0.0.1", 5000))
        response = client.get("/whoami", headers={"X-Forwarded-For": "127.0.0.1"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "No identity provider configured")

    @patch("app.dependencies.auth._get_active_idp_cached", return_value=None)
    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_clean_loopback_request_still_gets_the_dev_bypass(self, _mock_idp) -> None:
        """The convenience has to keep working, or it will be worked around."""
        client = TestClient(self.app, client=("127.0.0.1", 5000))
        response = client.get("/whoami")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "local-dev")


class TestStartupRefusesBypassInADeployment(unittest.TestCase):
    """A deployed process must not boot with the bypass enabled."""

    @patch.dict(os.environ, {}, clear=True)
    def test_no_opt_in_is_always_fine(self) -> None:
        assert_local_dev_bypass_not_deployed()

    @patch.dict(os.environ, {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true"}, clear=True)
    def test_opt_in_on_a_developer_machine_is_fine(self) -> None:
        """No container-runtime signals and no widened proxy trust: this is the
        supported local-dev case and must not be broken."""
        assert_local_dev_bypass_not_deployed()

    @patch.dict(
        os.environ,
        {
            LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true",
            "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc",
        },
        clear=True,
    )
    def test_refuses_to_start_under_ecs(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            assert_local_dev_bypass_not_deployed()
        self.assertIn("ECS_CONTAINER_METADATA_URI_V4", str(ctx.exception))

    @patch.dict(
        os.environ,
        {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true", "AWS_EXECUTION_ENV": "AWS_ECS_FARGATE"},
        clear=True,
    )
    def test_refuses_to_start_under_fargate(self) -> None:
        with self.assertRaises(RuntimeError):
            assert_local_dev_bypass_not_deployed()

    @patch.dict(
        os.environ,
        {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true", "FORWARDED_ALLOW_IPS": "*"},
        clear=True,
    )
    def test_refuses_to_start_with_widened_proxy_trust(self) -> None:
        """The combination that made the loopback check forgeable."""
        with self.assertRaises(RuntimeError) as ctx:
            assert_local_dev_bypass_not_deployed()
        self.assertIn("FORWARDED_ALLOW_IPS", str(ctx.exception))

    @patch.dict(
        os.environ,
        {LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV: "true", "FORWARDED_ALLOW_IPS": "127.0.0.1"},
        clear=True,
    )
    def test_loopback_only_proxy_trust_is_still_fine(self) -> None:
        """uvicorn's own default — proxy headers are only honoured from a
        loopback peer, so request.client stays trustworthy."""
        assert_local_dev_bypass_not_deployed()


if __name__ == "__main__":
    unittest.main()
