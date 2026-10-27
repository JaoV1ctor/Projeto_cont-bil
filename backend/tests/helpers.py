from datetime import datetime, timezone
from uuid import UUID

import psycopg

MTIME = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
FICTITIOUS_ROOT = "/lab/servidor-teste"  # raiz fictícia; os testes não acessam o sistema de arquivos


def make_source(conn: psycopg.Connection, name: str = "Fonte laboratório") -> UUID:
    return conn.execute(
        "INSERT INTO document_sources (name, root_path, normalization_policy) "
        "VALUES (%s, %s, 'exact') RETURNING id",
        (name, FICTITIOUS_ROOT),
    ).fetchone()[0]


def start_run(conn: psycopg.Connection, source_id: UUID) -> UUID:
    return conn.execute(
        "INSERT INTO index_runs (source_id) VALUES (%s) RETURNING id", (source_id,)
    ).fetchone()[0]


def finish_run(conn: psycopg.Connection, run_id: UUID, status: str = "completed") -> None:
    conn.execute(
        "UPDATE index_runs SET status = %s, finished_at = now() WHERE id = %s", (status, run_id)
    )
