"""Database setup and session management for Loom backend."""
import logging
import os
from sqlalchemy import create_engine, event, inspect, text, DDL
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

logger = logging.getLogger(__name__)

# Get LOOM_DATABASE_URL from environment, default to SQLite.
# Use absolute path to avoid data loss when CWD differs between invocations.
_default_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loom.db")
DATABASE_URL = os.getenv("LOOM_DATABASE_URL", f"sqlite:///{_default_db_path}")

# Create SQLAlchemy engine
# PostgreSQL connections (including via RDS Proxy) use pool_pre_ping to detect
# dropped connections and pool_recycle to avoid stale connections across proxy
# idle timeouts. SQLite uses check_same_thread=False for multi-threaded access.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )

# Enable foreign key constraints for SQLite
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function for FastAPI routes.

    Yields a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_add_columns(eng) -> None:
    """Add missing columns to existing tables.

    SQLAlchemy's create_all() does not alter existing tables, so this
    helper inspects the live schema and issues ALTER TABLE statements
    for any columns that are defined in the ORM but absent from the DB.
    """
    insp = inspect(eng)
    migrations: list[tuple[str, str, str]] = [
        ("invocations", "prompt_text", "TEXT"),
        ("invocations", "thinking_text", "TEXT"),
        ("invocations", "response_text", "TEXT"),
        ("agents", "source", "VARCHAR"),
        ("agents", "deployment_status", "VARCHAR"),
        ("agents", "execution_role_arn", "VARCHAR"),
        ("agents", "code_uri", "VARCHAR"),
        ("agents", "config_hash", "VARCHAR"),
        ("agents", "deployed_at", "DATETIME"),
        ("agents", "endpoint_name", "VARCHAR"),
        ("agents", "endpoint_arn", "VARCHAR"),
        ("agents", "endpoint_status", "VARCHAR"),
        ("agents", "protocol", "VARCHAR"),
        ("agents", "network_mode", "VARCHAR"),
        ("agents", "tags", "TEXT"),
        ("memories", "tags", "TEXT"),
        ("managed_roles", "tags", "TEXT"),
        ("authorizer_configs", "tags", "TEXT"),
        ("a2a_agents", "agentcore_session_id", "VARCHAR"),
        ("invocations", "input_tokens", "INTEGER"),
        ("invocations", "output_tokens", "INTEGER"),
        ("invocations", "estimated_cost", "REAL"),
        ("invocations", "compute_cost", "REAL"),
        ("invocations", "compute_cpu_cost", "REAL"),
        ("invocations", "compute_memory_cost", "REAL"),
        ("invocations", "idle_timeout_cost", "REAL"),
        ("invocations", "idle_cpu_cost", "REAL"),
        ("invocations", "idle_memory_cost", "REAL"),
        ("invocations", "memory_retrievals", "INTEGER"),
        ("invocations", "memory_events_sent", "INTEGER"),
        ("invocations", "memory_estimated_cost", "REAL"),
        ("invocations", "stm_cost", "REAL"),
        ("invocations", "ltm_cost", "REAL"),
        ("invocations", "cost_source", "VARCHAR"),
        ("invocations", "request_id", "VARCHAR"),
        ("invocation_sessions", "user_id", "VARCHAR"),
        ("invocation_sessions", "hidden_at", "DATETIME"),
        ("agents", "description", "TEXT"),
        ("mcp_servers", "registry_record_id", "VARCHAR"),
        ("mcp_servers", "registry_status", "VARCHAR"),
        ("mcp_servers", "api_key_header_name", "VARCHAR"),
        ("mcp_servers", "has_admin_api_key", "VARCHAR"),
        ("a2a_agents", "registry_record_id", "VARCHAR"),
        ("a2a_agents", "registry_status", "VARCHAR"),
        ("agents", "registry_record_id", "VARCHAR"),
        ("agents", "registry_status", "VARCHAR"),
        ("agents", "allowed_model_ids", "TEXT"),
        ("agents", "harness_id", "VARCHAR"),
        ("authorizer_configs", "allowed_audience", "TEXT"),
        ("authorizer_configs", "user_client_id", "VARCHAR"),
        ("authorizer_configs", "user_client_secret_arn", "VARCHAR"),
        ("authorizer_configs", "user_redirect_uri", "VARCHAR"),
        ("identity_providers", "name", "VARCHAR"),
        ("identity_providers", "provider_type", "VARCHAR"),
        ("identity_providers", "issuer_url", "VARCHAR"),
        ("identity_providers", "client_id", "VARCHAR"),
        ("identity_providers", "client_secret_arn", "VARCHAR"),
        ("identity_providers", "scopes", "VARCHAR"),
        ("identity_providers", "audience", "VARCHAR"),
        ("identity_providers", "group_claim_path", "VARCHAR"),
        ("identity_providers", "group_mappings", "TEXT"),
        ("identity_providers", "status", "VARCHAR"),
        ("identity_providers", "jwks_uri", "VARCHAR"),
        ("identity_providers", "authorization_endpoint", "VARCHAR"),
        ("identity_providers", "token_endpoint", "VARCHAR"),
        ("identity_providers", "discovery_scopes", "TEXT"),
        ("identity_providers", "client_type", "VARCHAR"),
        ("mcp_servers", "supports_elicitation", "VARCHAR"),
        ("mcp_servers", "runtime_endpoint_url", "VARCHAR"),
        ("mcp_servers", "delegation_mode", "VARCHAR DEFAULT 'm2m'"),
        ("a2a_agents", "delegation_mode", "VARCHAR DEFAULT 'm2m'"),
        ("mcp_servers", "obo_grant_type", "VARCHAR"),
        ("a2a_agents", "obo_grant_type", "VARCHAR"),
        ("mcp_servers", "oauth2_audience", "VARCHAR"),
        ("managed_roles", "role_type", "VARCHAR DEFAULT 'agent'"),
        ("agents", "code_interpreter_id", "VARCHAR"),
        ("agents", "vpc_subnet_ids", "TEXT"),
        ("agents", "vpc_security_group_ids", "TEXT"),
        ("agents", "vpc_config_id", "INTEGER"),
        ("agents", "status_reason", "TEXT"),
    ]

    is_postgres = eng.dialect.name == "postgresql"

    for table, column, col_type in migrations:
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column not in existing:
            if is_postgres:
                pg_type = col_type
                if pg_type == "DATETIME":
                    pg_type = "TIMESTAMP"
                elif pg_type == "REAL":
                    pg_type = "DOUBLE PRECISION"
                logger.info("Migrating: ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s", table, column, pg_type)
                with eng.begin() as conn:
                    conn.execute(DDL(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_type}"))
            else:
                logger.info("Migrating: ALTER TABLE %s ADD COLUMN %s %s", table, column, col_type)
                with eng.begin() as conn:
                    conn.execute(DDL(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def _backfill_session_users(eng) -> None:
    """Best-effort backfill of user_id on invocation_sessions.

    Matches sessions to users via audit_actions records where
    action_type='session_detail' and resource_name=session_id.
    Only updates rows where user_id is currently NULL.
    """
    insp = inspect(eng)
    if not insp.has_table("invocation_sessions") or not insp.has_table("audit_action"):
        return
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                UPDATE invocation_sessions
                SET user_id = (
                    SELECT a.user_id
                    FROM audit_action a
                    WHERE a.action_category = 'navigation'
                      AND a.action_type = 'session_detail'
                      AND a.resource_name = invocation_sessions.session_id
                    ORDER BY a.id ASC
                    LIMIT 1
                )
                WHERE user_id IS NULL
                  AND EXISTS (
                    SELECT 1 FROM audit_action a
                    WHERE a.action_category = 'navigation'
                      AND a.action_type = 'session_detail'
                      AND a.resource_name = invocation_sessions.session_id
                  )
            """))
            logger.info("Backfilled session user_id from audit_actions")
    except Exception as e:
        logger.warning("Session user backfill skipped: %s", e)


def _seed_default_tags(eng) -> None:
    """Seed default tag policies if they do not already exist."""
    from app.models.tag_policy import TagPolicy

    session = sessionmaker(bind=eng)()
    try:
        defaults = [
            {"key": "loom:application", "default_value": None, "required": True, "show_on_card": True},
            {"key": "loom:group", "default_value": None, "required": True, "show_on_card": True},
            {"key": "loom:owner", "default_value": None, "required": True, "show_on_card": True},
        ]
        # Remove legacy tags replaced by loom:* prefixed versions
        legacy_keys = ["application", "team", "owner", "deployed-by"]
        session.query(TagPolicy).filter(TagPolicy.key.in_(legacy_keys)).delete(synchronize_session="fetch")

        for tag_def in defaults:
            existing = session.query(TagPolicy).filter(TagPolicy.key == tag_def["key"]).first()
            if not existing:
                session.add(TagPolicy(**tag_def))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _seed_demo_tag_profiles(eng) -> None:
    """Seed tag profiles for demo-user-1 through demo-user-9."""
    from app.models.tag_profile import TagProfile

    session = sessionmaker(bind=eng)()
    try:
        # Remove any stale demo-admin-# profiles (not needed)
        admin_profile_names = [f"demo-admin-{i}" for i in range(1, 10)]
        session.query(TagProfile).filter(TagProfile.name.in_(admin_profile_names)).delete(synchronize_session="fetch")

        for i in range(1, 10):
            username = f"demo-user-{i}"
            expected_tags = {
                "loom:application": "demo",
                "loom:group": "demo",
                "loom:owner": username,
            }
            existing = session.query(TagProfile).filter(TagProfile.name == username).first()
            if not existing:
                profile = TagProfile(name=username)
                profile.set_tags(expected_tags)
                session.add(profile)
            elif existing.get_tags() != expected_tags:
                existing.set_tags(expected_tags)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """
    Initialize the database by creating all tables.

    Called during application startup.
    """
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns(engine)
    _backfill_session_users(engine)
    _seed_default_tags(engine)
    _seed_demo_tag_profiles(engine)
