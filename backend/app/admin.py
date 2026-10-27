"""Comandos administrativos locais. S0-06: bootstrap do primeiro administrador (T6, T9; D-014).

Uso: DATABASE_URL=... python -m app.admin create-first-admin --name "Nome" --login login

A senha é lida somente do terminal (getpass, com confirmação). Não existe opção de linha de
comando nem variável de ambiente para ela. Nenhuma função registra log.
"""
import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.auth.passwords import (
    PRODUCTION_PARAMETERS,
    HashParameters,
    PasswordPolicyError,
    hash_password,
)
from app.config import database_url
from app.db_locks import FIRST_ADMIN_BOOTSTRAP

ACTION = "user.bootstrap_first_admin"
SERVICE = "bootstrap"


class BootstrapError(Exception):
    """Entrada recusada antes de qualquer gravação. A mensagem nunca contém a senha."""


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    user_id: UUID | None
    event_id: UUID


def _audit(conn, result: str, target_id: UUID | None, details: dict) -> UUID:
    return conn.execute(
        "INSERT INTO audit_events (actor_type, actor_service, action, target_type, target_id, "
        "result, details) VALUES ('service', %s, %s, %s, %s, %s, %s) RETURNING id",
        (SERVICE, ACTION, "user" if target_id else None, target_id, result, Jsonb(details)),
    ).fetchone()[0]


def bootstrap_first_admin(
    conn: psycopg.Connection,
    *,
    name: str,
    login: str,
    password: str,
    params: HashParameters = PRODUCTION_PARAMETERS,
    on_locked: Callable[[], None] | None = None,
) -> BootstrapResult:
    """Cria o primeiro administrador numa única transação, sob advisory lock (T9).

    Isolamento exigido: READ COMMITTED. A transação fixa esse nível no primeiro comando,
    antes de qualquer snapshot, qualquer que seja o padrão da conexão ou do servidor.
    Em REPEATABLE READ ou SERIALIZABLE o snapshot seria tirado antes de esperar o lock, e a
    execução que esperou não veria o administrador criado pela anterior.

    Recusa, com auditoria, quando já existe qualquer usuário `administrator`, ativo ou não.
    `on_locked` existe só para testes de concorrência: é chamado com o lock já adquirido.
    """
    if conn.autocommit:
        raise ValueError("conexão do bootstrap não pode estar em autocommit")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("conexão do bootstrap deve estar sem transação aberta")
    try:
        password_hash = hash_password(password, params)  # fora do lock: hash é lento
    except PasswordPolicyError as exc:
        raise BootstrapError(f"senha recusada: {exc}") from None

    try:  # transação implícita; lock, verificação, INSERT e auditoria até o commit
        # Primeiro comando da transação: vale também sobre BEGIN ISOLATION LEVEL do psycopg.
        conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        isolation = conn.execute("SHOW transaction_isolation").fetchone()[0]
        if isolation != "read committed":
            raise RuntimeError(f"isolamento inesperado no bootstrap: {isolation}")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (FIRST_ADMIN_BOOTSTRAP,))
        if on_locked is not None:
            on_locked()
        exists = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM users WHERE role = 'administrator')"
        ).fetchone()[0]
        if exists:
            event_id = _audit(conn, "denied", None, {"reason": "administrator_exists"})
            conn.commit()
            return BootstrapResult(False, None, event_id)

        conn.execute("SAVEPOINT bootstrap_insert")
        try:
            user_id = conn.execute(
                "INSERT INTO users (name, login, password_hash, role, created_by) "
                "VALUES (%s, %s, %s, 'administrator', NULL) RETURNING id",
                (name, login, password_hash),
            ).fetchone()[0]
        except (errors.CheckViolation, errors.UniqueViolation, errors.NotNullViolation) as exc:
            # Lock continua retido: a recusa é auditada na mesma transação.
            conn.execute("ROLLBACK TO SAVEPOINT bootstrap_insert")
            _audit(conn, "failure", None, {"reason": "invalid_name_or_login"})
            conn.commit()
            raise BootstrapError(f"nome ou login recusado pelo cadastro ({type(exc).__name__})") from None
        event_id = _audit(conn, "success", user_id, {"login": login})
        conn.commit()
        return BootstrapResult(True, user_id, event_id)
    except BaseException:
        conn.rollback()
        raise


def read_password_from_terminal(prompt: Callable[[str], str] = getpass.getpass) -> str:
    """Lê a senha duas vezes do terminal. Recusa entrada que não seja terminal (pipe, arquivo)."""
    if not sys.stdin.isatty():
        raise BootstrapError("a senha deve ser digitada em um terminal interativo")
    first = prompt("Senha do primeiro administrador: ")
    second = prompt("Confirme a senha: ")
    if first != second:
        raise BootstrapError("as senhas não conferem")
    return first


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-first-admin", help="cria o primeiro administrador")
    create.add_argument("--name", required=True)
    create.add_argument("--login", required=True)
    args = parser.parse_args(argv)

    try:
        password = read_password_from_terminal()
        with psycopg.connect(database_url()) as conn:
            result = bootstrap_first_admin(conn, name=args.name, login=args.login, password=password)
    except BootstrapError as exc:
        print(f"recusado: {exc}", file=sys.stderr)
        return 2
    if not result.created:
        print("recusado: já existe administrador", file=sys.stderr)
        return 1
    print(f"primeiro administrador criado: {result.user_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
