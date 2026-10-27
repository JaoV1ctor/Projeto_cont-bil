"""Gravação de metadados observados no catálogo. Não acessa a origem dos documentos."""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg

Outcome = Literal["new", "updated", "unchanged"]


@dataclass(frozen=True)
class ObservedFile:
    relative_path: str  # separador '/', relativo à raiz da fonte
    size_bytes: int
    modified_at: datetime  # data de modificação informada pelo sistema de arquivos


def path_key(relative_path: str, policy: str) -> str:
    """Chave de identidade do documento na fonte (SPEC §7.2)."""
    if policy == "exact":
        return relative_path
    raise ValueError(f"política de normalização não suportada: {policy!r}")


def split_name(relative_path: str) -> tuple[str, str | None]:
    """Nome do arquivo e extensão em minúsculas sem ponto; arquivo oculto sem ponto extra não tem extensão."""
    name = relative_path.rsplit("/", 1)[-1]
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or not ext:
        return name, None
    return name, ext.lower()


def record_observation(
    conn: psycopg.Connection, source_id: UUID, run_id: UUID, observed: ObservedFile
) -> Outcome:
    """Registra um arquivo visto na execução; idempotente por (fonte, chave de caminho).

    Executa na transação do chamador. Não altera campos de classificação manual.
    """
    run = conn.execute(
        "SELECT r.status, s.normalization_policy FROM index_runs r "
        "JOIN document_sources s ON s.id = r.source_id "
        "WHERE r.id = %s AND r.source_id = %s FOR SHARE OF r",
        (run_id, source_id),
    ).fetchone()
    if run is None:
        raise ValueError("execução não pertence à fonte informada")
    status, policy = run
    if status != "running":
        raise ValueError(f"execução não está em andamento: {status}")

    key = path_key(observed.relative_path, policy)
    name, extension = split_name(observed.relative_path)
    current = conn.execute(
        "SELECT size_bytes, source_modified_at, relative_path FROM documents "
        "WHERE source_id = %s AND path_key = %s FOR UPDATE",
        (source_id, key),
    ).fetchone()

    if current is None:
        conn.execute(
            "INSERT INTO documents (source_id, relative_path, path_key, name, extension, size_bytes, "
            "source_modified_at, last_seen_run_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (source_id, observed.relative_path, key, name, extension, observed.size_bytes,
             observed.modified_at, run_id),
        )
        return "new"

    changed = current != (observed.size_bytes, observed.modified_at, observed.relative_path)
    conn.execute(
        "UPDATE documents SET relative_path = %s, name = %s, extension = %s, size_bytes = %s, "
        "source_modified_at = %s, last_seen_at = now(), last_seen_run_id = %s, "
        "availability = 'available', updated_at = CASE WHEN %s THEN now() ELSE updated_at END "
        "WHERE source_id = %s AND path_key = %s",
        (observed.relative_path, name, extension, observed.size_bytes, observed.modified_at,
         run_id, changed, source_id, key),
    )
    return "updated" if changed else "unchanged"
