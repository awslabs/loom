"""Move plaintext OAuth2 client secrets out of the database into Secrets Manager.

`McpServer.oauth2_client_secret` and `A2aAgent.oauth2_client_secret` were the
only secrets in Loom kept in the database rather than Secrets Manager. That
made a database dump or RDS snapshot directly credential-bearing, and left
secret reads with no CloudTrail trail.

Both are now stored in Secrets Manager keyed on the row id. The application
migrates a row lazily the first time its secret is used, so a deployment
upgrades without anyone re-entering anything — but lazy migration only moves
the secrets that happen to get used, and the plaintext copy survives until
then. Run this to move all of them at once and clear the columns.

    python -m scripts.migrate_oauth2_secrets          # report only
    python -m scripts.migrate_oauth2_secrets --apply

Safe to re-run: a row whose column is already empty is skipped. The secret is
written to Secrets Manager and read back before the column is cleared, so an
interrupted run cannot lose a value.
"""
import argparse
import logging
import sys

from app.db import SessionLocal
from app.models.a2a import A2aAgent
from app.models.mcp import McpServer
from app.services.mcp import secret_name_for
from app.services.secrets import get_secret, store_secret

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the migration")
    parser.add_argument("--region", default=None, help="AWS region (defaults to AWS_REGION)")
    args = parser.parse_args()

    import os
    region = args.region or os.getenv("AWS_REGION", "us-east-1")

    db = SessionLocal()
    moved = failed = skipped = 0
    try:
        for model, label in ((McpServer, "MCP server"), (A2aAgent, "A2A agent")):
            for row in db.query(model).all():
                if not row.oauth2_client_secret:
                    skipped += 1
                    continue
                name = secret_name_for(row)
                if not args.apply:
                    logger.info("Would move %s %s's client secret to %s", label, row.id, name)
                    moved += 1
                    continue
                try:
                    store_secret(
                        name, row.oauth2_client_secret, region,
                        description=f"OAuth2 client secret for {label} {row.name}",
                    )
                    # Read back before clearing: an interrupted run must not
                    # lose the only copy of a credential.
                    if get_secret(name, region) != row.oauth2_client_secret:
                        raise RuntimeError("read-back mismatch")
                except Exception as e:
                    logger.error("FAILED %s %s (%s): %s", label, row.id, name, e)
                    failed += 1
                    continue
                row.oauth2_client_secret = None
                row.has_oauth2_secret = "true"  # nosec B105 — boolean flag, not a password
                moved += 1
                logger.info("Moved %s %s's client secret to %s", label, row.id, name)
        if args.apply:
            db.commit()
    finally:
        db.close()

    verb = "Moved" if args.apply else "Would move"
    logger.info("%s %d secret(s); %d row(s) had none; %d failed.", verb, moved, skipped, failed)
    if not args.apply and moved:
        logger.info("Re-run with --apply to perform the migration.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
