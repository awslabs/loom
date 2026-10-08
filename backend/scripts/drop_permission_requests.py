"""Drop the permission_requests table.

Permission requests existed so an operator could ask Loom to add statements to
an IAM role, and Loom would apply them with PutRolePolicy on approval. Loom no
longer creates or modifies IAM roles or policies, so the feature was removed
along with that capability and the table is dead weight.

This destroys any request history. Run it once, after deploying the release
that removed the feature.

    python -m scripts.drop_permission_requests          # dry run
    python -m scripts.drop_permission_requests --apply

Works against whatever LOOM_DATABASE_URL points at (SQLite locally,
PostgreSQL/RDS in a deployment).
"""
import argparse
import logging
import sys

from sqlalchemy import inspect, text

from app.db import engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

TABLE = "permission_requests"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="actually drop the table; without this the script only reports",
    )
    args = parser.parse_args()

    if TABLE not in inspect(engine).get_table_names():
        logger.info("Table %r is not present; nothing to do.", TABLE)
        return 0

    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()  # nosec B608

    if not args.apply:
        logger.info(
            "Would drop table %r, destroying %d row(s). Re-run with --apply.",
            TABLE, rows,
        )
        return 0

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {TABLE}"))  # nosec B608
    logger.info("Dropped table %r (%d row(s) destroyed).", TABLE, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
