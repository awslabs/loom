#!/usr/bin/env python3
"""Sign in to Loom's active external IdP (Okta or Entra ID) from the command line.

Writes the resulting access token to a gitignored file so local tooling (and
coding assistants) can call the Loom API as a real user, without anyone
copying a token out of the browser and without the token ever being printed.

How it works (Authorization Code + PKCE, the same flow the Loom UI uses):

1. Read the active IdP's endpoints, client id and scopes from the target
   Loom's unauthenticated ``/api/auth/config`` — nothing to configure here.
2. Open the IdP sign-in page in a browser with ``prompt=login`` (so a different
   test persona can be used each time). MFA / conditional access apply as usual.
3. Receive the authorization code on a one-shot loopback listener
   (``http://localhost:<port>/oauth/callback`` — the same path the Loom UI uses).
4. Exchange it: confidential clients go through Loom's ``/api/auth/token``
   (the client secret never leaves the backend); public clients exchange
   directly with the IdP using the PKCE verifier.
5. Write only the access token — the bearer the Loom UI sends — to
   ``tmp/.tokens/<name>.jwt`` (mode 0600). The refresh token is discarded.
6. Confirm the token with ``/api/auth/me`` and print only non-secret details
   (username, groups as Loom maps them, expiry).

One-time IdP setup: register ``http://localhost:<port>/oauth/callback`` (default
port 8765) as a redirect URI on the existing Loom app registration — in Okta, the
app's sign-in redirect URIs; in Entra ID, a "Mobile and desktop applications"
platform (an SPA-platform redirect can't be redeemed outside a browser). Because
the path matches the UI's, ``--port 5173`` reuses an already-registered
``http://localhost:5173/oauth/callback`` with no IdP change — as long as the Vite
dev server isn't running on that port.

Usage:
    python scripts/loom_login.py [--loom-url http://localhost:8000] [--name okta-admin] [--port 8765]

Then, e.g.:
    curl -H "Authorization: Bearer $(cat tmp/.tokens/okta-admin.jwt)" http://localhost:8000/api/auth/me
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_DIR = REPO_ROOT / "tmp" / ".tokens"
CALLBACK_PATH = "/oauth/callback"  # same path as the Loom UI's redirect URI
LOGIN_TIMEOUT_SECONDS = 300


class LoginError(RuntimeError):
    """A sign-in step failed; the message is safe to print (contains no tokens)."""


def _http_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
               timeout: float = 15.0) -> dict[str, Any]:
    """Send a request and parse a JSON response. Never echoes response bodies on error."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — URLs are scheme-checked by callers
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # The body of a failed token exchange can echo request parameters, so
        # only the status and the OAuth error code (if any) are surfaced.
        code = ""
        try:
            code = json.loads(e.read().decode("utf-8")).get("error", "")
        except (ValueError, AttributeError):
            pass
        raise LoginError(f"{url} returned HTTP {e.code}{f' ({code})' if code else ''}") from None
    except urllib.error.URLError as e:
        raise LoginError(f"Could not reach {url}: {e.reason}") from None


def _require_https(url: str | None, label: str) -> str:
    if not url or urllib.parse.urlparse(url).scheme != "https":
        raise LoginError(f"The IdP {label} must be an https URL (got {url!r})")
    return url


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_claims(token: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying it (display only; Loom verifies it)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}


def _claim_path(claims: dict[str, Any], path: str) -> Any:
    value: Any = claims
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


class _CallbackHandler(BaseHTTPRequestHandler):
    """Accepts exactly one redirect to CALLBACK_PATH and records its query string."""

    result: dict[str, str] = {}
    done = threading.Event()

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        type(self).result = params
        ok = "code" in params and "error" not in params
        message = "Signed in to Loom. You can close this tab." if ok else (
            f"Sign-in failed: {html.escape(params.get('error', 'no authorization code returned'))}"
        )
        body = f"<html><body style='font-family:sans-serif'><p>{message}</p></body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        type(self).done.set()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — silence request logging (URL holds the code)
        return


def _await_code(port: int, expected_state: str) -> str:
    _CallbackHandler.result = {}
    _CallbackHandler.done = threading.Event()
    try:
        server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as e:
        raise LoginError(f"Can't listen on localhost:{port} ({e.strerror}); pass --port to use another") from None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not _CallbackHandler.done.wait(LOGIN_TIMEOUT_SECONDS):
            raise LoginError(f"Timed out after {LOGIN_TIMEOUT_SECONDS}s waiting for the IdP redirect")
    finally:
        server.shutdown()
        server.server_close()
    params = _CallbackHandler.result
    if "error" in params:
        raise LoginError(f"IdP returned an error: {params.get('error')} {params.get('error_description', '')}".strip())
    if not secrets.compare_digest(params.get("state", ""), expected_state):
        raise LoginError("State mismatch on the redirect; refusing the authorization code")
    code = params.get("code")
    if not code:
        raise LoginError("The redirect carried no authorization code")
    return code


def _safe_name(raw: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.")
    return name or "loom-user"


def _write_token(name: str, token: str) -> Path:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)
    path = TOKEN_DIR / f"{name}.jwt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(path, 0o600)
    return path


def login(loom_url: str, port: int, name: str | None, open_browser: bool) -> Path:
    loom_url = loom_url.rstrip("/")
    cfg = _http_json(f"{loom_url}/api/auth/config")
    provider = cfg.get("provider_type", "")
    if provider in ("", "cognito"):
        raise LoginError(
            f"{loom_url} has no active external IdP (provider_type={provider or 'none'}); "
            "activate Okta or Entra ID in Loom first"
        )
    authorize_url = _require_https(cfg.get("authorization_endpoint"), "authorization endpoint")
    client_type = cfg.get("client_type") or ("confidential" if cfg.get("has_client_secret") else "public")
    redirect_uri = f"http://localhost:{port}{CALLBACK_PATH}"

    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64url(secrets.token_bytes(24))
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": redirect_uri,
        "scope": cfg.get("scopes") or "openid profile email",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "login",
    })
    sign_in_url = f"{authorize_url}?{query}"

    print(f"Signing in with {provider} ({client_type} client) for {loom_url}")
    print(f"Redirect URI (must be registered on the IdP app): {redirect_uri}")
    if not open_browser or not webbrowser.open(sign_in_url):
        print(f"Open this URL to sign in:\n  {sign_in_url}")
    code = _await_code(port, state)

    if client_type == "confidential":
        tokens = _http_json(
            f"{loom_url}/api/auth/token",
            data=json.dumps({"code": code, "code_verifier": verifier, "redirect_uri": redirect_uri}).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    else:
        token_url = _require_https(cfg.get("token_endpoint"), "token endpoint")
        tokens = _http_json(
            token_url,
            data=urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "client_id": cfg.get("client_id", ""),
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            }).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
    access_token = tokens.get("access_token")
    if not access_token:
        raise LoginError("The token response had no access_token")
    tokens.clear()  # drop the refresh and id tokens; only the access token is kept

    me = _http_json(f"{loom_url}/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    claims = _jwt_claims(access_token)
    username = me.get("username") or claims.get("preferred_username") or claims.get("sub", "")
    path = _write_token(_safe_name(name or f"{provider}-{username}"), access_token)

    exp = claims.get("exp")
    expires = ""
    if isinstance(exp, (int, float)):
        when = datetime.fromtimestamp(exp, tz=timezone.utc).astimezone()
        expires = f"{when:%Y-%m-%d %H:%M %Z} (in {max(0, int((exp - time.time()) // 60))} min)"
    idp_groups = _claim_path(claims, cfg.get("group_claim_path") or "groups")
    print("\nSigned in. Token saved (not shown):")
    print(f"  file:         {path.relative_to(REPO_ROOT)}  (mode 0600)")
    print(f"  loom user:    {username}")
    print(f"  loom groups:  {', '.join(me.get('groups') or []) or '(none)'}")
    if idp_groups is not None:
        print(f"  idp groups:   {', '.join(idp_groups) if isinstance(idp_groups, list) else idp_groups}")
    if expires:
        print(f"  expires:      {expires}")
    print(f'\nUse it with:  curl -H "Authorization: Bearer $(cat {path.relative_to(REPO_ROOT)})" {loom_url}/api/auth/me')
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign in to Loom's active Okta / Entra ID IdP and save an access token.")
    parser.add_argument("--loom-url", default=os.getenv("LOOM_URL", f"http://localhost:{os.getenv('LOOM_BACKEND_PORT', '8000')}"),
                        help="Loom backend base URL (default: http://localhost:$LOOM_BACKEND_PORT)")
    parser.add_argument("--port", type=int, default=int(os.getenv("LOOM_LOGIN_PORT", "8765")),
                        help="Loopback port for the IdP redirect (default 8765; 5173 reuses the UI's local redirect URI when Vite isn't running)")
    parser.add_argument("--name", help="Token file name under tmp/.tokens/ (default: <idp>-<username>)")
    parser.add_argument("--no-browser", action="store_true", help="Print the sign-in URL instead of opening a browser")
    args = parser.parse_args()
    try:
        login(args.loom_url, args.port, args.name, open_browser=not args.no_browser)
    except LoginError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
