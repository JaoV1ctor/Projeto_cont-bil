"""Regras de transação comuns às funções de autenticação (S0-07, S0-08)."""
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

Clock = Callable[[], datetime]


def require_idle(conn: psycopg.Connection) -> None:
    if conn.autocommit:
        raise ValueError("conexão de autenticação não pode estar em autocommit")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("conexão de autenticação deve estar sem transação aberta")


def current_time(clock: Clock) -> datetime:
    now = clock()
    if now.tzinfo is None:
        raise ValueError("relógio deve retornar datetime com fuso")
    return now


def read_committed(conn: psycopg.Connection) -> None:
    """Primeiro comando da transação: fixa READ COMMITTED sobre qualquer padrão da conexão.

    Em REPEATABLE READ/SERIALIZABLE, a leitura após esperar uma trava usaria snapshot antigo
    ou falharia com erro de serialização.
    """
    conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    isolation = conn.execute("SHOW transaction_isolation").fetchone()[0]
    if isolation != "read committed":
        raise RuntimeError(f"isolamento inesperado na autenticação: {isolation}")


def lock_users(conn: psycopg.Connection, user_ids) -> dict[UUID, tuple[str, bool]]:
    """Trava linhas de users em ordem de id (mesma ordem em qualquer transação: sem deadlock).

    Retorna {id: (role, active)} só para os ids existentes.
    """
    rows = conn.execute(
        "SELECT id, role, active FROM users WHERE id = ANY(%s) ORDER BY id FOR NO KEY UPDATE",
        (sorted(set(user_ids)),),
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}
