"""An AWS error must not carry a secret into the logs.

AWS validation errors commonly echo the offending parameter back —
`Value 'xxx' at 'clientSecret' failed to satisfy constraint ...` is a shape
that appears across services. So an exception raised by a call whose *request
body* held a secret can contain that secret, and any caller that logs the
exception writes it to CloudWatch.

An AST sweep of `app/` found 20 such sites: `logger.*(..., e)` inside an
`except` whose `try` had just passed a secret to `store_secret`,
`create_oauth2_credential_provider`, `create_api_key_credential_provider` or
similar. Rather than thread the secret value into 20 log statements — and get
it right again for the 21st — the scrub happens where the secret is sent:
`services/secrets.py` and `services/credential.py` re-raise a sanitized error,
so everything downstream is safe whatever it logs.

Whether AWS echoes these particular values is unverified. That is not a thing
to establish from a production log.
"""
import logging
import unittest
from unittest.mock import MagicMock, patch

from app.services.credential import (
    CredentialProviderError,
    create_api_key_credential_provider,
    create_oauth2_credential_provider,
)
from app.services.redaction import redact, redacted_error
from app.services.secrets import SecretWriteError, store_secret

SECRET = "SUPER-SECRET-CLIENT-VALUE"  # nosec B105 — the fake secret this module is about


class TestRedact(unittest.TestCase):
    def test_replaces_the_value(self) -> None:
        self.assertEqual("a <redacted> b", redact(f"a {SECRET} b", SECRET))

    def test_handles_none_and_empty(self) -> None:
        self.assertEqual("unchanged", redact("unchanged", None, ""))

    def test_leaves_short_values_alone(self) -> None:
        """A 3-character "secret" is more likely an incidental substring;
        replacing it would mangle the diagnostic without protecting anything."""
        self.assertEqual("the cat sat", redact("the cat sat", "cat"))

    def test_redacts_every_occurrence(self) -> None:
        out = redacted_error(Exception(f"{SECRET} and again {SECRET}"), SECRET)
        self.assertNotIn(SECRET, out)
        self.assertEqual(2, out.count("<redacted>"))


class _AwsEchoesTheValue(Exception):
    """Stands in for an AWS validation error that quotes the parameter."""


class TestStoreSecretScrubsItsError(unittest.TestCase):
    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.client = MagicMock()
        self.client.exceptions.ResourceExistsException = _AwsEchoesTheValue
        self.client.exceptions.InvalidRequestException = _AwsEchoesTheValue
        self.client.create_secret.side_effect = Exception(
            f"ValidationException: Value '{SECRET}' at 'secretString' failed to satisfy constraint"
        )
        p = patch("boto3.client", return_value=self.client)
        p.start()
        self.addCleanup(p.stop)

    def test_the_secret_is_not_in_the_message(self) -> None:
        with self.assertRaises(SecretWriteError) as ctx:
            store_secret("loom/mcp/1/oauth2-client-secret", SECRET, "us-east-1")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_the_original_exception_is_not_chained(self) -> None:
        """`raise ... from e` would keep the unscrubbed message reachable via
        __cause__, and exc_info=True would render it."""
        with self.assertRaises(SecretWriteError) as ctx:
            store_secret("loom/mcp/1/oauth2-client-secret", SECRET, "us-east-1")
        self.assertIsNone(ctx.exception.__cause__)
        self.assertNotIn(SECRET, repr(ctx.exception.__cause__))

    def test_the_secret_name_is_kept_for_diagnosis(self) -> None:
        """Scrubbing must not make the error useless."""
        with self.assertRaises(SecretWriteError) as ctx:
            store_secret("loom/mcp/1/oauth2-client-secret", SECRET, "us-east-1")
        msg = str(ctx.exception)
        self.assertIn("loom/mcp/1/oauth2-client-secret", msg)
        self.assertIn("ValidationException", msg)


class TestCredentialProviderScrubsItsError(unittest.TestCase):
    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.client = MagicMock()
        self.client.exceptions.ValidationException = _AwsEchoesTheValue
        p = patch("boto3.client", return_value=self.client)
        p.start()
        self.addCleanup(p.stop)
        sleep = patch("time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_oauth2_client_secret_is_scrubbed(self) -> None:
        self.client.create_oauth2_credential_provider.side_effect = Exception(
            f"ValidationException: Value '{SECRET}' at 'clientSecret' failed to satisfy constraint"
        )
        with self.assertRaises(CredentialProviderError) as ctx:
            create_oauth2_credential_provider(
                "loom-a-1-mcp-b", "cid", SECRET,
                "https://idp.example.com/.well-known/openid-configuration", "us-east-1",
            )
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIn("loom-a-1-mcp-b", str(ctx.exception))

    def test_api_key_is_scrubbed(self) -> None:
        self.client.create_api_key_credential_provider.side_effect = Exception(
            f"ValidationException: Value '{SECRET}' at 'apiKey' failed to satisfy constraint"
        )
        with self.assertRaises(CredentialProviderError) as ctx:
            create_api_key_credential_provider("loom-a-1-litellm-key", SECRET, "us-east-1")
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)

    def test_nothing_logged_during_the_retries_contains_the_secret(self) -> None:
        """The retry loop logs the error once per attempt, so the scrub has to
        happen before the first log, not only at the final raise."""
        self.client.create_oauth2_credential_provider.side_effect = Exception(
            f"ValidationException: Value '{SECRET}' at 'clientSecret' failed to satisfy constraint"
        )
        logging.disable(logging.NOTSET)
        with self.assertLogs("app.services.credential", level="WARNING") as logs:
            with self.assertRaises(CredentialProviderError):
                create_oauth2_credential_provider(
                    "loom-a-1-mcp-b", "cid", SECRET,
                    "https://idp.example.com/.well-known/openid-configuration", "us-east-1",
                )
        joined = "\n".join(logs.output)
        self.assertNotIn(SECRET, joined)
        self.assertIn("<redacted>", joined)


if __name__ == "__main__":
    unittest.main()
