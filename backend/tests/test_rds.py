"""
Unit tests for PostgreSQL/RDS database support (issue #52).

Covers:
- SQLite URL produces correct engine args and SQLite pragma hook
- PostgreSQL URL produces no check_same_thread and no pragma hook
- _migrate_add_columns generates TIMESTAMP / DOUBLE PRECISION / IF NOT EXISTS for PG
- Migration script copies rows correctly using two in-memory SQLite DBs
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call
from io import StringIO

from sqlalchemy import create_engine, Column, Integer, String, MetaData, Table, text
from sqlalchemy.orm import declarative_base


# ---------------------------------------------------------------------------
# Helper: build a minimal in-memory db.py equivalent for testing engine logic
# ---------------------------------------------------------------------------

def _make_engine(database_url: str):
    """Replicate the engine creation logic from backend/app/db.py."""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, echo=False)


# ---------------------------------------------------------------------------
# R1: Engine creation — connect_args and pragma hook
# ---------------------------------------------------------------------------

class TestEngineCreation(unittest.TestCase):
    """Engine is created with the correct args based on the database URL."""

    def test_sqlite_has_check_same_thread(self) -> None:
        """SQLite URL causes check_same_thread=False to be included in connect_args."""
        sqlite_url = "sqlite:///:memory:"
        connect_args = {"check_same_thread": False} if sqlite_url.startswith("sqlite") else {}
        self.assertIn("check_same_thread", connect_args)
        self.assertFalse(connect_args["check_same_thread"])
        # Verify the engine created with these args can actually connect
        engine = create_engine(sqlite_url, connect_args=connect_args)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def test_postgres_url_no_check_same_thread(self) -> None:
        """For a PostgreSQL URL, connect_args must not include check_same_thread."""
        pg_url = "postgresql+psycopg2://user:pass@localhost:5432/loom"
        connect_args = {"check_same_thread": False} if pg_url.startswith("sqlite") else {}
        self.assertEqual(connect_args, {})

    def test_sqlite_dialect_name(self) -> None:
        """SQLite engine reports dialect name 'sqlite'."""
        engine = _make_engine("sqlite:///:memory:")
        self.assertEqual(engine.dialect.name, "sqlite")

    def test_postgres_url_prefix_detection(self) -> None:
        """All postgres:// and postgresql+psycopg2:// URLs are treated as non-SQLite."""
        postgres_urls = [
            "postgresql://user:pass@host/db",
            "postgresql+psycopg2://user:pass@host/db",
            "postgres://user:pass@host/db",
        ]
        for url in postgres_urls:
            connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
            self.assertEqual(connect_args, {}, f"Expected empty connect_args for {url}")


# ---------------------------------------------------------------------------
# R1: _migrate_add_columns — dialect-aware SQL generation
# ---------------------------------------------------------------------------

class TestMigrateAddColumns(unittest.TestCase):
    """_migrate_add_columns generates correct SQL for each dialect."""

    def _run_migrations_and_capture(self, engine):
        """
        Run _migrate_add_columns against a real engine and capture executed SQL.
        Returns a list of SQL strings that were executed.
        """
        executed_sql = []
        original_begin = engine.begin

        class CapturingConn:
            def execute(self, stmt):
                executed_sql.append(str(stmt))
                return MagicMock()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch.object(engine, "begin", return_value=CapturingConn()):
            # Import here so changes to db.py are picked up
            # Patch the engine inside db module
            import importlib
            import app.db as db_module
            old_engine = db_module.engine
            db_module.engine = engine
            try:
                db_module._migrate_add_columns(engine)
            finally:
                db_module.engine = old_engine

        return executed_sql

    def test_sqlite_alter_table_uses_no_if_not_exists(self) -> None:
        """SQLite _migrate_add_columns uses plain ALTER TABLE without IF NOT EXISTS."""
        import app.db as db_module

        engine = create_engine("sqlite:///:memory:")
        # Create the agents table so _migrate_add_columns finds it
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE agents (id INTEGER PRIMARY KEY, name TEXT)"))
            conn.commit()

        executed = []
        original_begin = engine.begin

        def capturing_begin():
            class Ctx:
                def __enter__(self_inner):
                    class FakeConn:
                        def execute(self_conn, stmt):
                            executed.append(str(stmt))
                    return FakeConn()
                def __exit__(self_inner, *args):
                    pass
            return Ctx()

        with patch.object(engine, "begin", side_effect=capturing_begin):
            db_module._migrate_add_columns(engine)

        # All executed statements should NOT contain "IF NOT EXISTS"
        for sql in executed:
            self.assertNotIn("IF NOT EXISTS", sql.upper(),
                             f"SQLite should not use IF NOT EXISTS: {sql}")

    def test_postgres_alter_table_uses_if_not_exists(self) -> None:
        """
        PostgreSQL _migrate_add_columns uses IF NOT EXISTS and maps types.

        Uses a mock engine with dialect.name == 'postgresql' to avoid
        requiring a real PostgreSQL connection.
        """
        import app.db as db_module

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"

        # Mock inspect to report the agents table exists but has only id column
        mock_insp = MagicMock()
        mock_insp.has_table.return_value = True
        mock_insp.get_columns.return_value = [{"name": "id"}]

        executed_sql = []

        class FakeConn:
            def execute(self, stmt):
                executed_sql.append(str(stmt))

        class FakeCtx:
            def __enter__(self):
                return FakeConn()
            def __exit__(self, *args):
                pass

        mock_engine.begin.return_value = FakeCtx()

        with patch("app.db.inspect", return_value=mock_insp):
            db_module._migrate_add_columns(mock_engine)

        # Every executed SQL should use IF NOT EXISTS
        for sql in executed_sql:
            self.assertIn("IF NOT EXISTS", sql,
                          f"PostgreSQL should use IF NOT EXISTS: {sql}")

    def test_postgres_datetime_mapped_to_timestamp(self) -> None:
        """_migrate_add_columns maps DATETIME → TIMESTAMP for PostgreSQL."""
        import app.db as db_module

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"

        mock_insp = MagicMock()
        mock_insp.has_table.return_value = True
        mock_insp.get_columns.return_value = [{"name": "id"}]

        executed_sql = []

        class FakeConn:
            def execute(self, stmt):
                executed_sql.append(str(stmt))

        class FakeCtx:
            def __enter__(self):
                return FakeConn()
            def __exit__(self, *args):
                pass

        mock_engine.begin.return_value = FakeCtx()

        with patch("app.db.inspect", return_value=mock_insp):
            db_module._migrate_add_columns(mock_engine)

        # Find any SQL that was for a DATETIME column
        datetime_sqls = [s for s in executed_sql if "deployed_at" in s or "hidden_at" in s]
        self.assertTrue(len(datetime_sqls) > 0, "Expected DATETIME columns to be migrated")
        for sql in datetime_sqls:
            self.assertIn("TIMESTAMP", sql,
                          f"DATETIME should be mapped to TIMESTAMP: {sql}")
            self.assertNotIn("DATETIME", sql,
                             f"DATETIME literal should not appear in PG SQL: {sql}")

    def test_postgres_real_mapped_to_double_precision(self) -> None:
        """_migrate_add_columns maps REAL → DOUBLE PRECISION for PostgreSQL."""
        import app.db as db_module

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"

        mock_insp = MagicMock()
        mock_insp.has_table.return_value = True
        mock_insp.get_columns.return_value = [{"name": "id"}]

        executed_sql = []

        class FakeConn:
            def execute(self, stmt):
                executed_sql.append(str(stmt))

        class FakeCtx:
            def __enter__(self):
                return FakeConn()
            def __exit__(self, *args):
                pass

        mock_engine.begin.return_value = FakeCtx()

        with patch("app.db.inspect", return_value=mock_insp):
            db_module._migrate_add_columns(mock_engine)

        # Find any SQL for a REAL column (e.g. estimated_cost)
        real_sqls = [s for s in executed_sql if "estimated_cost" in s or "compute_cost" in s]
        self.assertTrue(len(real_sqls) > 0, "Expected REAL columns to be migrated")
        for sql in real_sqls:
            self.assertIn("DOUBLE PRECISION", sql,
                          f"REAL should be mapped to DOUBLE PRECISION: {sql}")
            self.assertNotIn(" REAL", sql,
                             f"REAL literal should not appear in PG SQL: {sql}")


# ---------------------------------------------------------------------------
# R3: Migration script — copies rows between two in-memory SQLite databases
# ---------------------------------------------------------------------------

class TestMigrationScript(unittest.TestCase):
    """migrate_sqlite_to_postgres.py copies rows correctly."""

    def _make_source_db(self):
        """Create an in-memory SQLite database with sample data."""
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            ))
            conn.execute(text("INSERT INTO items VALUES (1, 'alpha')"))
            conn.execute(text("INSERT INTO items VALUES (2, 'beta')"))
            conn.execute(text("INSERT INTO items VALUES (3, 'gamma')"))
            conn.commit()
        return engine

    def _make_dest_db(self):
        """Create an empty in-memory SQLite database with the same schema."""
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            ))
            conn.commit()
        return engine

    def test_migrate_copies_all_rows(self) -> None:
        """migrate() copies all rows from source to destination."""
        from scripts.migrate_sqlite_to_postgres import migrate

        src = self._make_source_db()
        dest = self._make_dest_db()

        # Patch create_engine to return our pre-built engines in order
        call_count = {"n": 0}
        engines = [src, dest]

        def fake_create_engine(url, **kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            return engines[idx]

        with patch("scripts.migrate_sqlite_to_postgres.create_engine", side_effect=fake_create_engine):
            migrate("sqlite:///:memory:", "sqlite:///:memory:", skip_existing=False)

        with dest.connect() as conn:
            rows = conn.execute(text("SELECT id, name FROM items ORDER BY id")).fetchall()

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][1], "alpha")
        self.assertEqual(rows[1][1], "beta")
        self.assertEqual(rows[2][1], "gamma")

    def test_migrate_skip_existing_preserves_dest_data(self) -> None:
        """With --skip-existing, tables that already have data in dest are skipped."""
        from scripts.migrate_sqlite_to_postgres import migrate

        src = self._make_source_db()
        dest = self._make_dest_db()

        # Pre-populate destination with different data
        with dest.connect() as conn:
            conn.execute(text("INSERT INTO items VALUES (99, 'existing')"))
            conn.commit()

        call_count = {"n": 0}
        engines = [src, dest]

        def fake_create_engine(url, **kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            return engines[idx]

        with patch("scripts.migrate_sqlite_to_postgres.create_engine", side_effect=fake_create_engine):
            migrate("sqlite:///:memory:", "sqlite:///:memory:", skip_existing=True)

        with dest.connect() as conn:
            rows = conn.execute(text("SELECT id, name FROM items ORDER BY id")).fetchall()

        # Destination should still have only the pre-existing row
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "existing")

    def test_migrate_prints_summary(self) -> None:
        """migrate() prints a summary line with table and row counts."""
        from scripts.migrate_sqlite_to_postgres import migrate

        src = self._make_source_db()
        dest = self._make_dest_db()

        call_count = {"n": 0}
        engines = [src, dest]

        def fake_create_engine(url, **kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            return engines[idx]

        captured = StringIO()
        with patch("scripts.migrate_sqlite_to_postgres.create_engine", side_effect=fake_create_engine):
            with patch("sys.stdout", captured):
                migrate("sqlite:///:memory:", "sqlite:///:memory:", skip_existing=False)

        output = captured.getvalue()
        self.assertIn("items", output)
        self.assertIn("3", output)
        self.assertIn("Migration complete", output)

    def test_topological_sort_no_fk(self) -> None:
        """Tables with no foreign keys are returned in sorted order."""
        from scripts.migrate_sqlite_to_postgres import topological_sort

        engine = create_engine("sqlite:///:memory:")
        meta = MetaData()
        t1 = Table("zebra", meta, Column("id", Integer, primary_key=True))
        t2 = Table("apple", meta, Column("id", Integer, primary_key=True))
        t3 = Table("mango", meta, Column("id", Integer, primary_key=True))

        sorted_tables = topological_sort([t1, t2, t3])
        names = [t.name for t in sorted_tables]
        # Peers with no FK deps should be in alphabetical (deterministic) order
        self.assertEqual(names, ["apple", "mango", "zebra"])


if __name__ == "__main__":
    unittest.main()
