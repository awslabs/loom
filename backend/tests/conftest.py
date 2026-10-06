"""Shared fixtures, and the suite's isolation boundary against local state.

Most tests exercise business logic through scope-gated routers and don't care
about auth semantics — they rely on the local-dev bypass in
app.dependencies.auth being active. That bypass requires an explicit opt-in
(LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV) plus a loopback client rather than
activating automatically, and ``_default_auth_bypass`` supplies both so the
rest of the suite doesn't need to. test_auth.py and test_scopes.py override
that fixture with a no-op since they exercise the bypass mechanics directly.

The rest of this module exists because the suite used to depend on the
machine it ran on: an empty dev database, a reachable network, and nobody
triggering an agent delete. It ran green for months and then 335 of 893 tests
failed at once — not from a regression, but because an external IdP had been
registered in the dev database. Each boundary below is one way that
dependency got in. See issue #77.
"""
import ipaddress
import os
import socket
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Database: point the suite at a throwaway file, not the developer's loom.db
# ---------------------------------------------------------------------------
# This has to happen at import time, before anything pulls in app.db, because
# that module resolves LOOM_DATABASE_URL and builds its engine as a side
# effect of being imported — a fixture would run long after the engine exists.
#
# Overriding the get_db dependency isn't sufficient on its own: 18 call sites
# across app/ construct a SessionLocal() directly instead of taking the
# dependency, so dependency_overrides[get_db] never reaches them and they read
# whatever database app.db resolved at import. app/dependencies/auth.py is one
# of those sites, which is what made every un-overridden router request fail
# closed with 401 once a real IdP existed locally.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="loom-test-db-")
_TEST_DB_PATH = os.path.join(_TEST_DB_DIR, "test.db")
os.environ["LOOM_DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

import app.models  # noqa: E402,F401  — registers every mapper before create_all
from app.db import init_db  # noqa: E402  — must follow the env var set above

# Give the throwaway database a real schema, so the direct-SessionLocal paths
# above read an empty table rather than erroring on a missing one. Tests that
# need their own data still build their own engine and override get_db.
init_db()


@pytest.fixture(autouse=True)
def _default_auth_bypass(monkeypatch):
    monkeypatch.setenv("LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "true")
    monkeypatch.setattr("app.dependencies.auth._is_loopback_request", lambda request: True)
    yield


@pytest.fixture(autouse=True)
def _reset_idp_cache():
    """Clear auth's module-level active-IdP cache around every test.

    The cache is shared mutable state that outlives the test that populated
    it, so without this a test registering an IdP leaks an authenticated auth
    state into whatever runs next. Deliberately does *not* force the lookup to
    return None: the database isolation above is the single mechanism keeping
    local state out, and a second fixture quietly papering over it is how the
    original problem stayed invisible for so long.
    """
    import app.dependencies.auth as auth

    auth.invalidate_idp_cache()
    yield
    auth.invalidate_idp_cache()


# Modules whose polling/backoff loops would otherwise burn real wall-clock.
# _delete_agent_background alone slept up to 150 seconds per DELETE, inside
# the TestClient request, because FastAPI runs BackgroundTasks there.
_POLLING_MODULES = (
    "app.routers.agents",
    "app.services.registry",
    "app.services.cloudwatch",
    "app.services.credential",
    "app.services.evaluations",
)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """Take the wall-clock waits out of the app's polling loops.

    Only the sleeping is removed — the loops still run, and so keep the
    break/purge semantics the delete and span-wait tests assert against. A
    test that wants to observe backoff can still patch ``<module>.time.sleep``
    itself and will see its own mock, since this only replaces the module's
    ``time`` reference and delegates every other attribute to the real module.
    """
    import importlib
    import time as _time

    class _NoSleepTime:
        sleep = staticmethod(lambda _seconds: None)

        def __getattr__(self, name):
            return getattr(_time, name)

    for module_name in _POLLING_MODULES:
        module = importlib.import_module(module_name)
        if hasattr(module, "time"):
            monkeypatch.setattr(module, "time", _NoSleepTime())
    yield


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """Deny outbound network, so a new test can't silently add egress.

    Resolving a numeric literal is still allowed: the SSRF tests check their
    guard by handing it addresses like 169.254.169.254 or 127.0.0.1, and
    getaddrinfo parses those without touching DNS. Only hostname lookups and
    connection attempts — the operations that actually leave the machine — are
    refused.

    socket.socket itself is deliberately left alone. asyncio's selector event
    loop builds its self-pipe with socketpair(), so denying it breaks every
    TestClient request instead of catching real egress.
    """
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise RuntimeError(
                f"Test attempted to resolve hostname {host!r}. The suite is "
                "offline by design — mock the call or stub socket.getaddrinfo."
            ) from None
        return real_getaddrinfo(host, *args, **kwargs)

    def denied_connection(address, *args, **kwargs):
        raise RuntimeError(
            f"Test attempted to open a connection to {address!r}. The suite is "
            "offline by design — mock the client instead."
        )

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", denied_connection)
    yield
