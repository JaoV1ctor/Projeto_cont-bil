import psycopg
from alembic import command

from conftest import alembic_config

TABLES = {"document_sources", "index_runs", "documents", "index_errors"}
ACCESS_TABLES = {"users", "associations", "user_associations"}
AUDIT_TABLES = {"audit_events"}
SESSION_TABLES = {"sessions"}
LOCKOUT_TABLES = {"login_attempts", "login_lockouts"}


def _tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def test_migration_downgrade_and_upgrade(database_url):
    cfg = alembic_config(database_url)
    assert TABLES <= _tables(database_url)

    command.downgrade(cfg, "base")
    all_tables = TABLES | ACCESS_TABLES | AUDIT_TABLES | SESSION_TABLES | LOCKOUT_TABLES
    assert not all_tables & _tables(database_url)

    command.upgrade(cfg, "head")
    assert all_tables <= _tables(database_url)


def test_migration_0002_reverts_only_index_errors(database_url):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0001")
    assert _tables(database_url) & TABLES == TABLES - {"index_errors"}
    assert not ACCESS_TABLES & _tables(database_url)

    command.upgrade(cfg, "head")
    assert TABLES <= _tables(database_url)


def test_migration_0003_reverts_only_access_tables(database_url):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0002")
    tables = _tables(database_url)
    assert TABLES <= tables
    assert not ACCESS_TABLES & tables

    command.upgrade(cfg, "head")
    assert TABLES | ACCESS_TABLES <= _tables(database_url)


def _functions(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def test_migration_0004_reverts_only_audit_events(database_url):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0003")
    tables = _tables(database_url)
    assert TABLES | ACCESS_TABLES <= tables
    assert not AUDIT_TABLES & tables
    assert "audit_events_append_only" not in _functions(database_url)

    command.upgrade(cfg, "head")
    assert AUDIT_TABLES <= _tables(database_url)
    assert "audit_events_append_only" in _functions(database_url)


def test_migration_0005_reverts_only_sessions(database_url):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0004")
    tables = _tables(database_url)
    assert TABLES | ACCESS_TABLES | AUDIT_TABLES <= tables
    assert not SESSION_TABLES & tables

    command.upgrade(cfg, "head")
    assert SESSION_TABLES <= _tables(database_url)


def test_migration_0006_reverts_only_lockout_tables(database_url):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0005")
    tables = _tables(database_url)
    assert TABLES | ACCESS_TABLES | AUDIT_TABLES | SESSION_TABLES <= tables
    assert not LOCKOUT_TABLES & tables

    command.upgrade(cfg, "head")
    assert LOCKOUT_TABLES <= _tables(database_url)
