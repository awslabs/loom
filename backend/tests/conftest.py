"""Shared pytest fixtures for the backend test suite.

Most tests exercise business logic through scope-gated routers and don't
care about auth semantics — they rely on the local-dev bypass in
app.dependencies.auth being active. That bypass now requires an explicit
opt-in (LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV) plus a loopback client,
instead of activating automatically. This fixture supplies both by default
so the rest of the suite doesn't need to change. test_auth.py and
test_scopes.py override this fixture with a no-op since they exercise the
bypass mechanics directly and need to control auth state precisely.

Auth state must also not depend on the developer's local database — see
_no_active_external_idp.
"""
import pytest


@pytest.fixture(autouse=True)
def _default_auth_bypass(monkeypatch):
    monkeypatch.setenv("LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "true")
    monkeypatch.setattr("app.dependencies.auth._is_loopback_request", lambda request: True)
    yield


@pytest.fixture(autouse=True)
def _no_active_external_idp(monkeypatch):
    """Keep auth's active-IdP lookup off the developer's local database.

    ``get_current_user`` only reaches the local-dev bypass when neither
    Cognito nor an external IdP is configured, and ``_get_active_idp`` reads
    whatever database ``LOOM_DATABASE_URL`` resolves to — by default the dev
    ``loom.db`` sitting next to the app. So registering a real IdP there
    (pointing an agent at Okta, say) made the whole suite fail closed with
    401 while nothing about the code under test had changed.

    Deliberately a separate fixture from ``_default_auth_bypass``: that one is
    overridden by name in test_auth.py/test_scopes.py, which control auth
    state themselves but are no more entitled to read local dev state than
    any other module. A test that wants an active IdP patches this lookup
    itself. The module-level cache is cleared on both sides so a real IdP
    can't leak in or out through it.
    """
    import app.dependencies.auth as auth

    auth.invalidate_idp_cache()
    monkeypatch.setattr(auth, "_get_active_idp_cached", lambda: None)
    yield
    auth.invalidate_idp_cache()


@pytest.fixture(autouse=True)
def _no_agent_delete_poll_sleep(monkeypatch):
    """Take the wall-clock waits out of the agent-deletion poll loop.

    ``_delete_agent_background`` polls for the runtime to disappear with
    ``time.sleep(5)``, up to 30 attempts, and FastAPI runs ``BackgroundTasks``
    inside the TestClient request — so every ``DELETE /api/agents/{id}`` in
    the suite blocks for 5 to 150 real seconds. Nothing patched this because
    auth was rejecting those requests before the background task could run,
    so the cost never showed up.

    Only the sleeping is removed; the loop still runs and so keeps its
    break/purge semantics, which is what the delete tests assert against.
    Scoped to this module's ``time`` reference rather than the global one, so
    a test that genuinely cares about sleeping elsewhere is unaffected.
    """
    import time as _time

    import app.routers.agents as agents

    class _NoSleepTime:
        sleep = staticmethod(lambda _seconds: None)

        def __getattr__(self, name):
            return getattr(_time, name)

    monkeypatch.setattr(agents, "time", _NoSleepTime())
    yield
