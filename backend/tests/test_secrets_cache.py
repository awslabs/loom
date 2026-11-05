"""A secret write must be visible to the next read, not the cached old value.

get_secret caches each value for 300 s. store_secret used to leave that entry
alone, so an update was invisible until the TTL ended. Callers also keep the
ARN that store_secret returns and read through it, so the ARN key must drop
too. The fake client below stands in for Secrets Manager; no AWS, no network.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import secrets

REGION = "us-east-1"
NAME = "loom/agents/1/api-key"
OTHER = "loom/agents/2/api-key"


class _ResourceExists(Exception):
    pass


class _InvalidRequest(Exception):
    pass


class _FakeSecretsManager:
    """Just enough of the boto3 secretsmanager client for these paths."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.reads: dict[str, int] = {}
        self.exceptions = SimpleNamespace(
            ResourceExistsException=_ResourceExists,
            InvalidRequestException=_InvalidRequest,
        )

    def _arn(self, name: str) -> str:
        return f"arn:aws:secretsmanager:{REGION}:123456789012:secret:{name}-AbCdEf"

    def _resolve(self, secret_id: str) -> str:
        if secret_id.startswith("arn:"):
            return secret_id.split(":secret:", 1)[1].rsplit("-", 1)[0]
        return secret_id

    def create_secret(self, Name: str, Description: str, SecretString: str) -> dict:
        if Name in self.values:
            raise _ResourceExists(Name)
        self.values[Name] = SecretString
        return {"ARN": self._arn(Name)}

    def put_secret_value(self, SecretId: str, SecretString: str) -> dict:
        name = self._resolve(SecretId)
        self.values[name] = SecretString
        return {"ARN": self._arn(name)}

    def get_secret_value(self, SecretId: str) -> dict:
        name = self._resolve(SecretId)
        self.reads[name] = self.reads.get(name, 0) + 1
        return {"SecretString": self.values[name]}

    def delete_secret(self, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict:
        name = self._resolve(SecretId)
        self.values.pop(name, None)
        # The real DeleteSecret response carries both the ARN and the name.
        return {"ARN": self._arn(name), "Name": name}


class TestSecretsCache(unittest.TestCase):
    def setUp(self) -> None:
        secrets._cache.clear()
        self.client = _FakeSecretsManager()
        p = patch("boto3.client", return_value=self.client)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(secrets._cache.clear)

    def test_read_after_store_returns_new_value(self) -> None:
        secrets.store_secret(NAME, "value-A", REGION)
        self.assertEqual("value-A", secrets.get_secret(NAME, REGION))  # now cached

        secrets.store_secret(NAME, "value-B", REGION)

        self.assertEqual("value-B", secrets.get_secret(NAME, REGION))

    def test_read_by_arn_after_store_by_name_returns_new_value(self) -> None:
        # Callers persist the ARN store_secret returns and read through it.
        arn = secrets.store_secret(NAME, "value-A", REGION)
        self.assertEqual("value-A", secrets.get_secret(arn, REGION))  # cached by ARN

        secrets.store_secret(NAME, "value-B", REGION)

        self.assertEqual("value-B", secrets.get_secret(arn, REGION))

    def test_unrelated_key_stays_cached(self) -> None:
        secrets.store_secret(NAME, "value-A", REGION)
        secrets.store_secret(OTHER, "other-1", REGION)
        secrets.get_secret(OTHER, REGION)
        secrets.get_secret(NAME, REGION)

        secrets.store_secret(NAME, "value-B", REGION)
        reads_before = self.client.reads.get(OTHER, 0)

        self.assertEqual("other-1", secrets.get_secret(OTHER, REGION))
        self.assertEqual("other-1", secrets.get_secret(OTHER, REGION))
        self.assertEqual(reads_before, self.client.reads.get(OTHER, 0))

    def test_delete_by_name_drops_the_name_and_arn_keys(self) -> None:
        arn = secrets.store_secret(NAME, "value-A", REGION)
        secrets.get_secret(NAME, REGION)
        secrets.get_secret(arn, REGION)
        self.assertIn(NAME, secrets._cache)
        self.assertIn(arn, secrets._cache)

        secrets.delete_secret(NAME, REGION)

        self.assertNotIn(NAME, secrets._cache)
        self.assertNotIn(arn, secrets._cache)

    def test_delete_by_arn_also_drops_the_name_key(self) -> None:
        arn = secrets.store_secret(NAME, "value-A", REGION)
        secrets.get_secret(NAME, REGION)
        secrets.get_secret(arn, REGION)

        secrets.delete_secret(arn, REGION)

        self.assertNotIn(NAME, secrets._cache)
        self.assertNotIn(arn, secrets._cache)

    def test_delete_leaves_an_unrelated_key_cached(self) -> None:
        secrets.store_secret(NAME, "value-A", REGION)
        secrets.store_secret(OTHER, "other-1", REGION)
        secrets.get_secret(OTHER, REGION)

        secrets.delete_secret(NAME, REGION)

        self.assertIn(OTHER, secrets._cache)

    def test_reads_stay_cached_without_a_write(self) -> None:
        secrets.store_secret(NAME, "value-A", REGION)
        secrets.get_secret(NAME, REGION)
        secrets.get_secret(NAME, REGION)

        self.assertEqual(1, self.client.reads.get(NAME, 0))

    def test_ttl_expiry_still_refetches(self) -> None:
        secrets.store_secret(NAME, "value-A", REGION)
        with patch("app.services.secrets.time") as clock:
            clock.time.return_value = 1000.0
            self.assertEqual("value-A", secrets.get_secret(NAME, REGION))

            clock.time.return_value = 1000.0 + secrets._CACHE_TTL_SECONDS - 1
            secrets.get_secret(NAME, REGION)
            self.assertEqual(1, self.client.reads.get(NAME, 0))

            self.client.values[NAME] = "value-changed-out-of-band"
            clock.time.return_value = 1000.0 + secrets._CACHE_TTL_SECONDS + 1
            self.assertEqual("value-changed-out-of-band", secrets.get_secret(NAME, REGION))
        self.assertEqual(2, self.client.reads.get(NAME, 0))


if __name__ == "__main__":
    unittest.main()
