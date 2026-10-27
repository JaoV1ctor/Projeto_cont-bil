"""Login, sessões no servidor e auditoria de autenticação (S0-07; T2–T5, T7, T8; R3).

- Token opaco aleatório (32 bytes, base64url) entregue uma única vez; o banco guarda só o
  SHA-256 (T3).
- Expira após 30 min sem uso ou 10 h no total (R3). O relógio é injetável (T8).
- A cada resolução, ativo/perfil vêm do banco (T4). Mudança direta no banco tem efeito na
  próxima resolução, mas não marca a sessão como revogada.
- Revogação explícita só por `logout` e `revoke_user_sessions` (T5).
- Falha de login tem resultado externo único e o mesmo caminho para login inexistente,
  usuário inativo e senha errada: uma busca, uma verificação Argon2id (hash fictício quando
  não há usuário) e um evento de auditoria (T7). Não há promessa de tempo idêntico.
- Rehash só depois de verificação bem-sucedida de usuário ativo (T2; aceite S0-07.8).
- Limite de tentativas (S0-08, R4): ver `app.auth.lockout`. Login bloqueado com senha
  correta falha com o mesmo resultado externo e o mesmo caminho de verificação (T7).
- Ordem com alterações em `users`: o login fixa READ COMMITTED e trava a linha do usuário
  (`FOR NO KEY UPDATE`) antes de verificar a senha, até o commit da sessão. Alteração de
  senha/ativo confirmada antes da trava é lida pelo login (linha atual, não snapshot antigo);
  alteração iniciada depois espera o commit do login.

Cada função usa uma transação própria e exige conexão sem autocommit e ociosa. Nada é
registrado em log; senha e token nunca entram em auditoria, exceção ou repr.
"""
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.auth import lockout
from app.auth.passwords import (
    PRODUCTION_PARAMETERS,
    HashParameters,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.auth.transactions import Clock, current_time, read_committed, require_idle

IDLE_TIMEOUT = timedelta(minutes=30)  # R3 (D-018)
ABSOLUTE_LIFETIME = timedelta(hours=10)  # R3 (D-018)
TOKEN_BYTES = 32  # T3
_MAX_TOKEN_CHARS = 128
_AUTH_SERVICE = "authentication"



def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LoginSuccess:
    token: str = field(repr=False)  # entregue uma vez ao cliente; nunca gravado
    session_id: UUID
    user_id: UUID
    role: str
    expires_at: datetime


@dataclass(frozen=True)
class LoginFailure:
    """Resultado externo único para qualquer falha de login (T7)."""

    message: str = "login ou senha inválidos"


LOGIN_FAILED = LoginFailure()


@dataclass(frozen=True)
class SessionInfo:
    session_id: UUID
    user_id: UUID
    login: str
    role: str
    expires_at: datetime


_require_idle = require_idle
_now = current_time
_read_committed = read_committed


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def _valid_token_shape(token) -> bool:
    return isinstance(token, str) and 0 < len(token) <= _MAX_TOKEN_CHARS and token.isascii()


@lru_cache(maxsize=4)
def _dummy_hash(params: HashParameters) -> str:
    # Verificado quando não há usuário, para manter o mesmo passo de Argon2id (T7).
    return hash_password(secrets.token_urlsafe(24), params)


def _find_user(conn, login) -> tuple | None:
    """Lê e trava a linha atual do usuário até o fim da transação do login."""
    if not isinstance(login, str):
        login = ""
    return conn.execute(
        'SELECT id, password_hash, active, role FROM users '
        'WHERE lower(login COLLATE "C") = lower(%s COLLATE "C") FOR NO KEY UPDATE',
        (login,),
    ).fetchone()


def _audit(conn, *, action: str, result: str, actor_user_id: UUID | None,
           target_user_id: UUID | None, details: dict, actor_service: str = _AUTH_SERVICE) -> None:
    actor_type = "user" if actor_user_id is not None else "service"
    conn.execute(
        "INSERT INTO audit_events (actor_type, actor_user_id, actor_service, action, "
        "target_type, target_id, result, details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (actor_type, actor_user_id, None if actor_user_id is not None else actor_service,
         action, "user" if target_user_id else None, target_user_id, result, Jsonb(details)),
    )


def login(
    conn: psycopg.Connection,
    login: str,
    password: str,
    *,
    clock: Clock = utc_now,
    params: HashParameters = PRODUCTION_PARAMETERS,
    source_ip: str | None = None,
) -> LoginSuccess | LoginFailure:
    """Autentica e cria sessão. Toda tentativa grava um evento `auth.login`.

    Usuário existente também tem a tentativa registrada em `login_attempts` (S0-08).
    `source_ip` é só armazenado; limite por IP fica para S0-10.
    """
    _require_idle(conn)
    now = _now(clock)
    ip = lockout.normalize_ip(source_ip)
    try:
        _read_committed(conn)
        user = _find_user(conn, login)  # trava a linha: tentativas do usuário em série
        stored_hash = user[1] if user else _dummy_hash(params)
        verified = verify_password(stored_hash, password)  # sempre, inclusive bloqueado (T7)

        if user is None:
            _audit(conn, action="auth.login", result="failure", actor_user_id=None,
                   target_user_id=None, details={"reason": "unknown_login"})
            conn.commit()
            return LOGIN_FAILED

        user_id, _, active, role = user
        if lockout.is_locked(conn, user_id, now):
            lockout.record_attempt(conn, user_id, now, "blocked", ip)
            _audit(conn, action="auth.login", result="failure", actor_user_id=None,
                   target_user_id=user_id, details={"reason": "locked"})
            conn.commit()
            return LOGIN_FAILED

        if not active or not verified:
            attempt_seq = lockout.record_attempt(conn, user_id, now, "failure", ip)
            _audit(conn, action="auth.login", result="failure", actor_user_id=None,
                   target_user_id=user_id,
                   details={"reason": "inactive" if not active else "wrong_password"})
            lockout.lock_if_threshold_reached(conn, user_id, now, attempt_seq)
            conn.commit()
            return LOGIN_FAILED

        rehashed = False
        if needs_rehash(stored_hash, params):  # só após verificação bem-sucedida (T2)
            try:
                new_hash = hash_password(password, params)
            except PasswordPolicyError:
                new_hash = None  # senha antiga fora da política atual: mantém o hash
            if new_hash is not None:
                rehashed = conn.execute(
                    "UPDATE users SET password_hash = %s, updated_at = now() "
                    "WHERE id = %s AND password_hash = %s",
                    (new_hash, user_id, stored_hash),
                ).rowcount == 1

        lockout.record_attempt(conn, user_id, now, "success", ip)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        expires_at = now + ABSOLUTE_LIFETIME
        session_id = conn.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, last_used_at, expires_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, _token_hash(token), now, now, expires_at),
        ).fetchone()[0]
        _audit(conn, action="auth.login", result="success", actor_user_id=user_id,
               target_user_id=user_id, details={"session_id": str(session_id), "rehashed": rehashed})
        conn.commit()
        return LoginSuccess(token, session_id, user_id, role, expires_at)
    except BaseException:
        conn.rollback()
        raise


def resolve_session(conn: psycopg.Connection, token: str, *, clock: Clock = utc_now) -> SessionInfo | None:
    """Sessão válida com estado atual do usuário (T4), ou None. Atualiza o último uso."""
    _require_idle(conn)
    if not _valid_token_shape(token):
        return None
    now = _now(clock)
    try:
        row = conn.execute(
            "SELECT s.id, s.user_id, s.last_used_at, s.expires_at, s.revoked_at, u.active, "
            "u.role, u.login FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s FOR UPDATE OF s",
            (_token_hash(token),),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        session_id, user_id, last_used_at, expires_at, revoked_at, active, role, user_login = row
        if (revoked_at is not None or now >= expires_at or now >= last_used_at + IDLE_TIMEOUT
                or not active):
            conn.rollback()
            return None
        conn.execute(
            "UPDATE sessions SET last_used_at = greatest(last_used_at, %s) WHERE id = %s",
            (now, session_id),
        )
        conn.commit()
        return SessionInfo(session_id, user_id, user_login, role, expires_at)
    except BaseException:
        conn.rollback()
        raise


def logout(conn: psycopg.Connection, token: str, *, clock: Clock = utc_now) -> bool:
    """Revoga a sessão do token. True se havia sessão não revogada; grava `auth.logout`."""
    _require_idle(conn)
    if not _valid_token_shape(token):
        return False
    now = _now(clock)
    try:
        row = conn.execute(
            "UPDATE sessions SET revoked_at = greatest(%s, created_at), revoked_reason = 'logout' "
            "WHERE token_hash = %s AND revoked_at IS NULL RETURNING id, user_id",
            (now, _token_hash(token)),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        session_id, user_id = row
        _audit(conn, action="auth.logout", result="success", actor_user_id=user_id,
               target_user_id=user_id, details={"session_id": str(session_id)})
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise


def revoke_user_sessions(
    conn: psycopg.Connection,
    user_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    actor_service: str | None = None,
    clock: Clock = utc_now,
) -> int:
    """Revoga todas as sessões abertas do usuário (T5). Exige ator; grava `auth.revoke_sessions`."""
    _require_idle(conn)
    if (actor_user_id is None) == (actor_service is None):
        raise ValueError("informe exatamente um ator: usuário ou serviço")
    now = _now(clock)
    try:
        revoked = revoke_open_sessions_in_transaction(
            conn, user_id, now, actor_user_id=actor_user_id, actor_service=actor_service)
        conn.commit()
        return revoked
    except BaseException:
        conn.rollback()
        raise


def revoke_open_sessions_in_transaction(
    conn: psycopg.Connection, user_id: UUID, now: datetime, *,
    actor_user_id: UUID | None = None, actor_service: str | None = None,
) -> int:
    """Revoga e audita na transação do chamador (sem commit). Usado por mudanças de perfil."""
    revoked = conn.execute(
        "UPDATE sessions SET revoked_at = greatest(%s, created_at), revoked_reason = 'revoked' "
        "WHERE user_id = %s AND revoked_at IS NULL",
        (now, user_id),
    ).rowcount
    _audit(conn, action="auth.revoke_sessions", result="success", actor_user_id=actor_user_id,
           actor_service=actor_service or _AUTH_SERVICE, target_user_id=user_id,
           details={"revoked": revoked})
    return revoked
