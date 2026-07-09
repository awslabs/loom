#!/usr/bin/env python3
"""Drop and recreate the public schema, wiping all data and tables.

The application will recreate all tables on next startup via init_db().
"""
import os
import sys
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("LOOM_DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: LOOM_DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)
if DATABASE_URL.startswith("sqlite"):
    print("ERROR: This script is only intended for PostgreSQL databases", file=sys.stderr)
    sys.exit(1)

print(f"Target: {DATABASE_URL}")
confirm = input("This will permanently delete all data. Type 'yes' to continue: ")
if confirm.strip().lower() != "yes":
    print("Aborted.")
    sys.exit(0)

engine = create_engine(DATABASE_URL)
with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))

print("Done. All tables dropped — restart the server to recreate the schema.")
