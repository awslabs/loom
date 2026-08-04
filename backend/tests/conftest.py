"""Shared pytest fixtures for the backend test suite.

Most tests exercise business logic through scope-gated routers and don't
care about auth semantics — they rely on the local-dev bypass in
app.dependencies.auth being active. That bypass now requires an explicit
opt-in (LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV) plus a loopback client,
instead of activating automatically. This fixture supplies both by default
so the rest of the suite doesn't need to change. test_auth.py and
test_scopes.py override this fixture with a no-op since they exercise the
bypass mechanics directly and need to control auth state precisely.
"""
import pytest


@pytest.fixture(autouse=True)
def _default_auth_bypass(monkeypatch):
    monkeypatch.setenv("LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "true")
    monkeypatch.setattr("app.dependencies.auth._is_loopback_request", lambda request: True)
    yield
