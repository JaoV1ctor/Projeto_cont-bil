"""Autorização por associação (S0-09; SPEC §§4.1, 8.1; D-020, D-021; T4).

Matriz (SPEC §4.1 e decisões):
- administrador: ler, alterar e gerenciar acessos em qualquer associação existente, inclusive
  inativa (D-020). O acesso global é auditado (`authz.global_access`).
- operador: ler e alterar só em associação autorizada (`user_associations`) e ativa.
- consulta: só ler em associação autorizada e ativa.
- usuário inativo ou inexistente: nada.

Fontes consultadas: só `users` (perfil, ativo), `associations` (situação) e
`user_associations`. Sugestões, classificação e vínculos de documento nunca concedem acesso
(SPEC §8.1). Tudo é lido do banco a cada chamada, sem cache (T4): mudança, inclusive direta
no banco, vale na chamada seguinte, sem revogar sessão.

Concessão e remoção de acesso e mudança de perfil: só administrador ativo, nunca sobre si
mesmo (D-021). Ator e alvo são travados em ordem de id antes de ler o perfil do ator, como no
desbloqueio (S0-08). Toda tentativa dessas funções é auditada (`success` ou `denied`).
"""
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.auth.sessions import revoke_open_sessions_in_transaction, utc_now
from app.auth.transactions import Clock, current_time, lock_users, read_committed, require_idle

Action = Literal["read", "write", "manage_access"]
ACTIONS: frozenset[str] = frozenset({"read", "write", "manage_access"})
ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "administrator": ACTIONS,
    "operator": frozenset({"read", "write"}),
    "viewer": frozenset({"read"}),
}
ROLES = frozenset(ROLE_ACTIONS)


class AuthorizationDenied(Exception):
    """Mudança recusada (já auditada). `reason`: 'actor_not_admin' ou 'self_change'."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _check_action(action: str) -> None:
    if action not in ACTIONS:
        raise ValueError(f"ação desconhecida: {action!r}")


def _audit(conn, *, actor_user_id: UUID, action: str, target_type: str, target_id: UUID | None,
           result: str, details: dict) -> None:
    conn.execute(
        "INSERT INTO audit_events (actor_type, actor_user_id, action, target_type, target_id, "
        "result, details) VALUES ('user', %s, %s, %s, %s, %s, %s)",
        (actor_user_id, action, target_type, target_id, result, Jsonb(details)),
    )


# --- consulta de permissão -----------------------------------------------------------------------

def authorize(conn: psycopg.Connection, user_id: UUID, action: Action, association_id: UUID) -> bool:
    """True se o usuário pode executar `action` na associação. Usa transação própria."""
    _check_action(action)
    require_idle(conn)
    try:
        read_committed(conn)
        row = conn.execute(
            "SELECT u.role, u.active, a.status, EXISTS (SELECT 1 FROM user_associations ua "
            "WHERE ua.user_id = u.id AND ua.association_id = a.id) "
            "FROM users u CROSS JOIN associations a WHERE u.id = %s AND a.id = %s",
            (user_id, association_id),
        ).fetchone()
        allowed = False
        if row is not None:
            role, active, status, linked = row
            if active and action in ROLE_ACTIONS[role]:
                if role == "administrator":
                    allowed = True
                    _audit(conn, actor_user_id=user_id, action="authz.global_access",
                           target_type="association", target_id=association_id, result="success",
                           details={"action": action})
                else:
                    allowed = linked and status == "active"
        conn.commit()
        return allowed
    except BaseException:
        conn.rollback()
        raise


def accessible_association_ids(
    conn: psycopg.Connection, user_id: UUID, action: Action = "read"
) -> frozenset[UUID]:
    """Associações em que `authorize(user_id, action, ...)` é True. Usa transação própria."""
    _check_action(action)
    require_idle(conn)
    try:
        read_committed(conn)
        user = conn.execute("SELECT role, active FROM users WHERE id = %s", (user_id,)).fetchone()
        ids: frozenset[UUID] = frozenset()
        if user is not None and user[1] and action in ROLE_ACTIONS[user[0]]:
            if user[0] == "administrator":
                ids = frozenset(r[0] for r in conn.execute("SELECT id FROM associations"))
                _audit(conn, actor_user_id=user_id, action="authz.global_access",
                       target_type="association", target_id=None, result="success",
                       details={"action": action, "scope": "all", "count": len(ids)})
            else:
                ids = frozenset(r[0] for r in conn.execute(
                    "SELECT a.id FROM user_associations ua "
                    "JOIN associations a ON a.id = ua.association_id "
                    "WHERE ua.user_id = %s AND a.status = 'active'",
                    (user_id,),
                ))
        conn.commit()
        return ids
    except BaseException:
        conn.rollback()
        raise


# --- mudanças de acesso e de perfil (D-021) ------------------------------------------------------

def _authorize_change(conn, action: str, actor_user_id: UUID, target_user_id: UUID,
                      target_type: str, target_id: UUID, details: dict) -> None:
    """Trava ator e alvo; recusa (com auditoria e commit) ator não administrador ou autoalteração."""
    users = lock_users(conn, [actor_user_id, target_user_id])
    if actor_user_id not in users:
        raise ValueError("ator não existe")
    if target_user_id not in users:
        raise ValueError("usuário alvo não existe")
    reason = None
    if users[actor_user_id] != ("administrator", True):
        reason = "actor_not_admin"
    elif actor_user_id == target_user_id:
        reason = "self_change"
    if reason is not None:
        _audit(conn, actor_user_id=actor_user_id, action=action, target_type=target_type,
               target_id=target_id, result="denied", details={**details, "reason": reason})
        conn.commit()
        raise AuthorizationDenied(reason)


def grant_access(conn: psycopg.Connection, *, actor_user_id: UUID, user_id: UUID,
                 association_id: UUID) -> bool:
    """Concede acesso explícito. True se criou o vínculo; False se já existia."""
    require_idle(conn)
    try:
        read_committed(conn)
        details = {"user_id": str(user_id)}
        _authorize_change(conn, "authz.grant_access", actor_user_id, user_id,
                          "association", association_id, details)
        created = conn.execute(
            "INSERT INTO user_associations (user_id, association_id, created_by) "
            "VALUES (%s, %s, %s) ON CONFLICT (user_id, association_id) DO NOTHING",
            (user_id, association_id, actor_user_id),
        ).rowcount == 1
        _audit(conn, actor_user_id=actor_user_id, action="authz.grant_access",
               target_type="association", target_id=association_id, result="success",
               details={**details, "created": created})
        conn.commit()
        return created
    except AuthorizationDenied:
        raise
    except BaseException:
        conn.rollback()
        raise


def revoke_access(conn: psycopg.Connection, *, actor_user_id: UUID, user_id: UUID,
                  association_id: UUID) -> bool:
    """Remove acesso explícito. True se removeu. Efeito na próxima autorização (T4)."""
    require_idle(conn)
    try:
        read_committed(conn)
        details = {"user_id": str(user_id)}
        _authorize_change(conn, "authz.revoke_access", actor_user_id, user_id,
                          "association", association_id, details)
        removed = conn.execute(
            "DELETE FROM user_associations WHERE user_id = %s AND association_id = %s",
            (user_id, association_id),
        ).rowcount == 1
        _audit(conn, actor_user_id=actor_user_id, action="authz.revoke_access",
               target_type="association", target_id=association_id, result="success",
               details={**details, "removed": removed})
        conn.commit()
        return removed
    except AuthorizationDenied:
        raise
    except BaseException:
        conn.rollback()
        raise


def change_role(conn: psycopg.Connection, *, actor_user_id: UUID, user_id: UUID, new_role: str,
                clock: Clock = utc_now) -> bool:
    """Muda o perfil e revoga as sessões abertas do alvo na mesma transação (T5).

    True se o perfil mudou; False se já era `new_role` (nada revogado).
    """
    if new_role not in ROLES:
        raise ValueError(f"perfil desconhecido: {new_role!r}")
    require_idle(conn)
    now = current_time(clock)
    try:
        read_committed(conn)
        _authorize_change(conn, "authz.change_role", actor_user_id, user_id, "user", user_id,
                          {"new_role": new_role})
        old_role = conn.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()[0]
        changed = old_role != new_role
        if changed:
            conn.execute("UPDATE users SET role = %s, updated_at = now() WHERE id = %s",
                         (new_role, user_id))
            revoke_open_sessions_in_transaction(conn, user_id, now, actor_user_id=actor_user_id)
        _audit(conn, actor_user_id=actor_user_id, action="authz.change_role", target_type="user",
               target_id=user_id, result="success",
               details={"old_role": old_role, "new_role": new_role, "changed": changed})
        conn.commit()
        return changed
    except AuthorizationDenied:
        raise
    except BaseException:
        conn.rollback()
        raise
