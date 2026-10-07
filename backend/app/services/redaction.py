"""Scrubbing secret values out of error messages before they are logged.

AWS APIs frequently echo an offending parameter back in a validation error —
the `Value 'xxx' at 'clientSecret' failed to satisfy constraint ...` form is
common across services. So an exception raised by a call whose *request body*
carried a secret can itself contain that secret, and every caller that logs
the exception then writes it to CloudWatch.

A sweep of this codebase found 20 such sites: `logger.*(..., e)` inside an
`except` whose `try` had just passed a secret to `store_secret`,
`create_oauth2_credential_provider`, `create_api_key_credential_provider` or
similar. Fixing them individually would mean threading the secret value into
20 log statements and getting it right again every time someone adds a 21st.

So the scrub happens at the source instead: the module that *sends* the secret
is the one that knows what to remove, and it re-raises a sanitized error.
Everything downstream is then safe by construction, whatever it logs.

Whether AWS actually echoes these particular values is unverified — it is not
something to find out from a production log.
"""
from __future__ import annotations

REDACTED = "<redacted>"

# Below this length a "secret" is more likely to be a common substring that
# appears in the message for unrelated reasons, and replacing it would mangle
# the diagnostic without protecting anything meaningful.
_MIN_REDACTABLE = 6


def redact(text: str, *secrets: str | None) -> str:
    """Replace each secret value in `text`."""
    for value in secrets:
        if value and len(value) >= _MIN_REDACTABLE:
            text = text.replace(value, REDACTED)
    return text


def redacted_error(exc: BaseException, *secrets: str | None) -> str:
    """`str(exc)` with the given secret values removed.

    Use when re-raising, not when logging: raising a new exception whose
    message is this, with `from None`, is what keeps the original — and its
    traceback, which `exc_info=True` would render — from carrying the value
    onward.
    """
    return redact(str(exc), *secrets)
