"""Indexador de metadados: processo separado da API (D-006). Somente laboratório até P-04.

Uso: DATABASE_URL=... INDEXER_ALLOWED_ROOTS=/caminho/da/copia python -m app.indexer --source NOME

Grava em lotes. Marca documentos como não localizados somente após varredura completa e sem
erros (SPEC §7.2). Falha, cancelamento ou erro de acesso preservam a disponibilidade anterior.
"""
import argparse
import os
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from uuid import UUID

import psycopg
from psycopg import errors

from app.catalog import ObservedFile, record_observation
from app.config import database_url, indexer_allowed_roots
from app.source_reader import ErrorEntry, FileEntry, SkippedEntry, SourceReader, SourceUnavailable

DEFAULT_BATCH_SIZE = 200


class IndexerBusy(Exception):
    """Já existe execução em andamento para a fonte."""


@dataclass(frozen=True)
class Counts:
    found: int = 0
    new: int = 0
    updated: int = 0
    not_found: int = 0
    ignored: int = 0
    errors: int = 0


@dataclass(frozen=True)
class RunSummary:
    run_id: UUID
    status: str
    counts: Counts
    interruption_reason: str | None


def _locate(root: str, allowed_roots: Sequence[str]) -> tuple[str, str]:
    """Raiz permitida que contém a fonte e o caminho relativo da fonte dentro dela.

    Comparação só textual, sem resolver links: o leitor abre cada componente sem segui-los,
    então não há janela entre validar e abrir (SPEC §5.5).
    """
    if not os.path.isabs(root):
        raise PermissionError("raiz da fonte deve ser caminho absoluto")
    root = os.path.normpath(root)
    for allowed in allowed_roots:
        if not os.path.isabs(allowed):
            continue
        allowed = os.path.normpath(allowed)
        if os.path.commonpath([root, allowed]) == allowed:
            relative = os.path.relpath(root, allowed)
            return allowed, "" if relative == "." else relative
    raise PermissionError("raiz da fonte fora de INDEXER_ALLOWED_ROOTS")


def _printable(relative_path: str) -> str:
    # Nome com bytes fora de UTF-8 (surrogateescape) vira escape legível para o registro de erro.
    return relative_path.encode("utf-8", "backslashreplace").decode("utf-8")


def _add_error(conn: psycopg.Connection, run_id: UUID, path: str | None, code: str, message: str):
    conn.execute(
        "INSERT INTO index_errors (run_id, relative_path, code, message) VALUES (%s, %s, %s, %s)",
        (run_id, None if path is None else _printable(path), code, message),
    )


def _save_progress(conn, run_id: UUID, counts: Counts, last_position: str | None) -> None:
    conn.execute(
        "UPDATE index_runs SET found_count = %s, new_count = %s, updated_count = %s, "
        "not_found_count = %s, ignored_count = %s, error_count = %s, "
        "last_position = COALESCE(%s, last_position) WHERE id = %s",
        (counts.found, counts.new, counts.updated, counts.not_found, counts.ignored,
         counts.errors, None if last_position is None else _printable(last_position), run_id),
    )


def _observe(conn, source_id: UUID, run_id: UUID, entry: FileEntry) -> str | None:
    """Grava um arquivo isolado em savepoint; nome que o catálogo recusa vira erro, não aborta o lote."""
    conn.execute("SAVEPOINT observation")
    try:
        outcome = record_observation(
            conn, source_id, run_id,
            ObservedFile(entry.relative_path, entry.size_bytes, entry.modified_at),
        )
    except (errors.CheckViolation, UnicodeEncodeError):
        conn.execute("ROLLBACK TO SAVEPOINT observation")
        return None
    conn.execute("RELEASE SAVEPOINT observation")
    return outcome


def run_index(
    conn: psycopg.Connection,
    source_id: UUID,
    *,
    allowed_roots: Sequence[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    should_cancel: Callable[[], bool] | None = None,
) -> RunSummary:
    """Varre a fonte inteira e registra execução, contagens e erros.

    `conn` sem autocommit e dedicada ao indexador: o método confirma transações por lote.
    """
    if conn.autocommit:
        raise ValueError("conexão do indexador não pode estar em autocommit")
    if batch_size < 1:
        raise ValueError("batch_size deve ser positivo")

    row = conn.execute(
        "SELECT root_path, active FROM document_sources WHERE id = %s", (source_id,)
    ).fetchone()
    if row is None:
        raise ValueError("fonte não encontrada")
    root, active = row
    if not active:
        raise ValueError("fonte inativa")
    allowed, relative = _locate(root, allowed_roots)
    reader = SourceReader(allowed, relative)

    try:
        run_id = conn.execute(
            "INSERT INTO index_runs (source_id) VALUES (%s) RETURNING id", (source_id,)
        ).fetchone()[0]
        conn.commit()
    except errors.UniqueViolation:
        conn.rollback()
        raise IndexerBusy("já existe execução em andamento para esta fonte") from None

    counts = committed = Counts()
    last_position = None
    pending = 0
    status: str | None = None  # None = árvore percorrida até o fim
    reason: str | None = None
    try:
        for entry in reader.walk():
            if should_cancel is not None and should_cancel():
                status, reason = "cancelled", "cancelamento solicitado"
                break
            if isinstance(entry, FileEntry):
                outcome = _observe(conn, source_id, run_id, entry)
                counts = replace(counts, found=counts.found + 1)
                if outcome is None:
                    _add_error(conn, run_id, entry.relative_path, "invalid_name",
                               "nome ou caminho recusado pelo catálogo")
                    counts = replace(counts, errors=counts.errors + 1)
                elif outcome == "new":
                    counts = replace(counts, new=counts.new + 1)
                elif outcome == "updated":
                    counts = replace(counts, updated=counts.updated + 1)
            elif isinstance(entry, SkippedEntry):
                counts = replace(counts, ignored=counts.ignored + 1)
            elif isinstance(entry, ErrorEntry):
                # Caminho vazio = falha ao listar a própria raiz; registrado como erro da fonte.
                _add_error(conn, run_id, entry.relative_path or None, entry.code, entry.message)
                counts = replace(counts, errors=counts.errors + 1)
            last_position = entry.relative_path
            pending += 1
            if pending >= batch_size:
                _save_progress(conn, run_id, counts, last_position)
                conn.commit()
                committed, pending = counts, 0
        conn.execute("UPDATE document_sources SET status = 'available', updated_at = now() "
                     "WHERE id = %s", (source_id,))
    except SourceUnavailable as exc:
        conn.rollback()
        _add_error(conn, run_id, None, "source_unavailable", exc.message)
        conn.execute("UPDATE document_sources SET status = 'unavailable', updated_at = now() "
                     "WHERE id = %s", (source_id,))
        counts = replace(committed, errors=committed.errors + 1)
        status, reason = "failed", "fonte indisponível"
    except BaseException as exc:
        # Lote não confirmado é descartado; contagens voltam ao último lote gravado.
        conn.rollback()
        cancelled = isinstance(exc, KeyboardInterrupt)
        _finish(conn, source_id, run_id, committed,
                "cancelled" if cancelled else "failed",
                "interrompido" if cancelled else f"falha: {type(exc).__name__}", None)
        raise

    return _finish(conn, source_id, run_id, counts, status, reason, last_position)


def _finish(conn, source_id, run_id, counts: Counts, status, reason, last_position) -> RunSummary:
    if status is None:
        if counts.errors:
            status = "completed_with_errors"
        else:
            status = "completed"
            not_found = conn.execute(
                "UPDATE documents SET availability = 'not_found', updated_at = now() "
                "WHERE source_id = %s AND availability = 'available' "
                "AND last_seen_run_id IS DISTINCT FROM %s",
                (source_id, run_id),
            ).rowcount
            counts = replace(counts, not_found=not_found)
            conn.execute(
                "UPDATE document_sources SET last_complete_run_at = now(), updated_at = now() "
                "WHERE id = %s", (source_id,),
            )
    _save_progress(conn, run_id, counts, last_position)
    conn.execute(
        "UPDATE index_runs SET status = %s, finished_at = now(), interruption_reason = %s "
        "WHERE id = %s",
        (status, reason, run_id),
    )
    conn.commit()
    return RunSummary(run_id, status, counts, reason)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.indexer", description=__doc__.split("\n")[0])
    parser.add_argument("--source", required=True, help="nome da fonte em document_sources")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)

    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())

    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "SELECT id FROM document_sources WHERE name = %s", (args.source,)
        ).fetchone()
        if row is None:
            print("fonte não encontrada", file=sys.stderr)
            return 2
        conn.commit()
        try:
            summary = run_index(conn, row[0], allowed_roots=indexer_allowed_roots(),
                                batch_size=args.batch_size, should_cancel=cancel.is_set)
        except (IndexerBusy, PermissionError, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 2
    print(f"execução {summary.run_id}: {summary.status} {asdict(summary.counts)}")
    return 0 if summary.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
