#!/usr/bin/env python3
"""Reset PostgreSQL sequences after data migration from SQLite.

When migrating data with explicit IDs, PostgreSQL sequences are not
updated automatically. This script resets each sequence to the current
max ID in its table so that new inserts do not collide.
"""
import os
import sys
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.sql import literal_column, table as sql_table, column as sql_column

DATABASE_URL = os.environ.get("LOOM_DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: LOOM_DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)
if DATABASE_URL.startswith("sqlite"):
    print("ERROR: This script is only needed for PostgreSQL databases", file=sys.stderr)
    sys.exit(1)

engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    result = conn.execute(text("""
        SELECT table_name
        FROM information_schema.columns
        WHERE column_name = 'id'
          AND table_schema = 'public'
          AND column_default LIKE 'nextval%%'
        ORDER BY table_name
    """))
    tables = [row[0] for row in result]

    if not tables:
        print("No sequences found to reset.")
        sys.exit(0)

    for table in tables:
        if not table.replace("_", "").isalnum():
            print(f"ERROR: Unexpected table name from information_schema: {table!r}", file=sys.stderr)
            sys.exit(1)
        tbl = sql_table(table, sql_column("id"))
        row = conn.execute(select(func.coalesce(func.max(tbl.c.id), 1))).scalar()
        conn.execute(select(func.setval(func.pg_get_serial_sequence(table, "id"), row)))
        print(f"  {table}: sequence reset to {row}")

print("Done.")
