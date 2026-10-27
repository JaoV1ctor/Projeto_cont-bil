"""Testes de integração com PostgreSQL descartável.

Exige TEST_DATABASE_URL para banco com sufixo `_test` em IP loopback explícito
(regras em tests/db_guard.py). Os testes apagam e recriam o schema desse banco.
"""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from db_guard import UnsafeTestDatabase, connect_checked, validate_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.exit("TEST_DATABASE_URL não definida; ver backend/README.md", returncode=2)
    try:
        validate_url(url)
    except UnsafeTestDatabase as exc:
        pytest.exit(f"TEST_DATABASE_URL recusada: {exc}", returncode=2)
    return url


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    try:
        conn = connect_checked(url, autocommit=True)
    except UnsafeTestDatabase as exc:
        pytest.exit(f"conexão de teste recusada: {exc}", returncode=2)
    with conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def conn(database_url):
    with connect_checked(database_url) as connection:
        connection.execute(
            "TRUNCATE login_lockouts, login_attempts, sessions, audit_events, user_associations, "
            "associations, users, index_errors, documents, index_runs, document_sources"
        )
        connection.commit()
        yield connection
        connection.rollback()
