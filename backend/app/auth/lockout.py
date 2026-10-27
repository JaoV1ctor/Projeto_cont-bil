"""Limite de tentativas por login (S0-08; R4/D-019).

- 5 falhas em 15 min bloqueiam aquele login por 15 min; o bloqueio expira sozinho.
- Contam falhas (`result = 'failure'`) na janela de horário (agora − 15 min, agora] que vêm,
  na ordem transacional (`login_attempts.seq`), depois do último sucesso, da falha que iniciou
  o último bloqueio e do último desbloqueio. Horários iguais não alteram essa ordem.
- Tentativas durante o bloqueio são registradas como `blocked` e não estendem o bloqueio.
- Só usuários existentes têm tentativas registradas (por `user_id`); o texto digitado como
  login nunca é gravado.
- Chamado pelo login com a linha do usuário já travada (`FOR NO KEY UPDATE`): tentativas do
  mesmo usuário são serializadas, e a contagem no limiar não ultrapassa R4.

Nenhuma função registra log nem grava senha.
"""
import ipaddress
from datetime import datetime, timedelta
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.auth.transactions import Clock, current_time, lock_users, read_committed, require_idle

LOCKOUT_THRESHOLD = 5  # R4 (D-019)
LOCKOUT_WINDOW = timedelta(minutes=15)  # R4 (D-019)
LOCKOUT_DURATION = timedelta(minutes=15)  # R4 (D-019)


def normalize_ip(source_ip: str | None) -> str | None:
    """IP de origem validado ou None. Recusa texto que não seja endereço IP."""
    if source_ip is None:
        return None
    try:
        return str(ipaddress.ip_address(source_ip))
    except ValueError:
        raise ValueError("source_ip não é endereço IP válido") from None  # sem ecoar a entrada


def is_locked(conn: psycopg.Connection, user_id: UUID, now: datetime) -> bool:
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM login_lockouts WHERE user_id = %s AND unlocked_at IS NULL "
        "AND locked_at <= %s AND locked_until > %s)",
        (user_id, now, now),
    ).fetchone()[0]


def record_attempt(conn, user_id: UUID, now: datetime, result: str, source_ip: str | None) -> int:
    """Registra a tentativa e retorna sua posição na ordem transacional (`seq`)."""
    return conn.execute(
        "INSERT INTO login_attempts (user_id, attempted_at, result, source_ip) "
        "VALUES (%s, %s, %s, %s) RETURNING seq",
        (user_id, now, result, source_ip),
    ).fetchone()[0]


def _recent_failures(conn, user_id: UUID, now: datetime) -> int:
    return conn.execute(
        """
        SELECT count(*) FROM login_attempts a
        WHERE a.user_id = %(u)s AND a.result = 'failure'
          AND a.attempted_at > %(start)s AND a.attempted_at <= %(now)s
          AND a.seq > coalesce((SELECT max(seq) FROM login_attempts
                                WHERE user_id = %(u)s AND result = 'success'), 0)
          AND a.seq > coalesce((SELECT max(trigger_attempt_seq) FROM login_lockouts
                                WHERE user_id = %(u)s), 0)
          AND a.seq > coalesce((SELECT max(unlocked_after_seq) FROM login_lockouts
                                WHERE user_id = %(u)s), 0)
        """,
        {"u": user_id, "start": now - LOCKOUT_WINDOW, "now": now},
    ).fetchone()[0]


def lock_if_threshold_reached(
    conn, user_id: UUID, now: datetime, attempt_seq: int
) -> datetime | None:
    """Depois de registrar a falha `attempt_seq`: cria bloqueio ao atingir R4."""
    failures = _recent_failures(conn, user_id, now)
    if failures < LOCKOUT_THRESHOLD:
        return None
    locked_until = now + LOCKOUT_DURATION
    conn.execute(
        "INSERT INTO login_lockouts (user_id, locked_at, locked_until, trigger_attempt_seq) "
        "VALUES (%s, %s, %s, %s)",
        (user_id, now, locked_until, attempt_seq),
    )
    conn.execute(
        "INSERT INTO audit_events (actor_type, actor_service, action, target_type, target_id, "
        "result, details) VALUES ('service', 'authentication', 'auth.lockout', 'user', %s, "
        "'success', %s)",
        (user_id, Jsonb({"failures": failures, "locked_until": locked_until.isoformat()})),
    )
    return locked_until


_lock_users = lock_users  # nome mantido: ponto de gancho dos testes de concorrência


def unlock_user(
    conn: psycopg.Connection, user_id: UUID, *, actor_user_id: UUID, clock: Clock
) -> bool:
    """Desbloqueio antecipado por administrador ativo, com auditoria `auth.unlock`.

    Ordem transacional: em READ COMMITTED, trava ator e alvo (`FOR NO KEY UPDATE`, ordem de
    id) antes de ler perfil/ativo do ator. Mudança do ator confirmada antes da trava é vista;
    mudança iniciada depois espera o commit do desbloqueio. O login trava só o alvo.

    Retorna True se havia bloqueio ativo e ele foi encerrado. Ator que não é administrador
    ativo é recusado e auditado como `denied`. Ator inexistente é erro do chamador.
    """
    require_idle(conn)
    now = current_time(clock)
    try:
        read_committed(conn)
        users = _lock_users(conn, [user_id, actor_user_id])
        actor = users.get(actor_user_id)
        if actor is None:
            raise ValueError("ator do desbloqueio não existe")
        allowed = actor == ("administrator", True)
        unlocked = allowed and conn.execute(
            "UPDATE login_lockouts SET unlocked_at = %(now)s, unlocked_by = %(actor)s, "
            "unlocked_after_seq = (SELECT max(seq) FROM login_attempts WHERE user_id = %(u)s) "
            "WHERE user_id = %(u)s AND unlocked_at IS NULL AND locked_at <= %(now)s "
            "AND locked_until > %(now)s",
            {"now": now, "actor": actor_user_id, "u": user_id},
        ).rowcount > 0
        conn.execute(
            "INSERT INTO audit_events (actor_type, actor_user_id, action, target_type, target_id, "
            "result, details) VALUES ('user', %s, 'auth.unlock', 'user', %s, %s, %s)",
            (actor_user_id, user_id, "success" if allowed else "denied",
             Jsonb({"unlocked": unlocked})),
        )
        conn.commit()
        return unlocked
    except BaseException:
        conn.rollback()
        raise
