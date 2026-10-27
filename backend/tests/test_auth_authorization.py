"""S0-09: autorização por associação (D-020, D-021; T4). Dados fictícios."""
import itertools
import threading
import time
import uuid
from datetime import datetime, timezone

import pytest

import app.auth.authorization as authorization
from app.auth.authorization import (
    ACTIONS,
    AuthorizationDenied,
    accessible_association_ids,
    authorize,
    change_role,
    grant_access,
    revoke_access,
)
from app.auth.passwords import HashParameters, hash_password
from app.auth.sessions import LoginSuccess, login, resolve_session
from db_guard import connect_checked

FAST = HashParameters(time_cost=1, memory_cost_kib=1024, parallelism=1)
SECRET = "senha-ficticia-autorizacao-26"
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
CLOCK = lambda: NOW  # noqa: E731

ROLES = ("administrator", "operator", "viewer")
ASSOCIATION_STATES = ("authorized", "unauthorized", "inactive_authorized", "inactive_unauthorized")
USER_STATES = ("active", "inactive")


def _user(conn, login, role="operator", active=True):
    user_id = conn.execute(
        "INSERT INTO users (name, login, password_hash, role, active) "
        "VALUES ('Usuário Exemplo', %s, %s, %s, %s) RETURNING id",
        (login, hash_password(SECRET, FAST), role, active),
    ).fetchone()[0]
    conn.commit()
    return user_id


def _association(conn, name="Associação Exemplo Aurora", status="active"):
    assoc_id = conn.execute(
        "INSERT INTO associations (name, status) VALUES (%s, %s) RETURNING id", (name, status)
    ).fetchone()[0]
    conn.commit()
    return assoc_id


def _link(conn, user_id, assoc_id):
    conn.execute("INSERT INTO user_associations (user_id, association_id) VALUES (%s, %s)",
                 (user_id, assoc_id))
    conn.commit()


def _events(conn, action):
    rows = conn.execute(
        "SELECT actor_user_id, target_type, target_id, result, details FROM audit_events "
        "WHERE action = %s ORDER BY occurred_at, id", (action,),
    ).fetchall()
    conn.commit()
    return rows


def _expected(role, action, assoc_state, user_state) -> bool:
    """Matriz esperada, escrita de forma independente do código (SPEC §4.1, D-020)."""
    if user_state == "inactive":
        return False
    if role == "administrator":
        return True  # qualquer associação existente, inclusive inativa
    authorized_and_active = assoc_state == "authorized"
    if role == "operator":
        return action in ("read", "write") and authorized_and_active
    return action == "read" and authorized_and_active  # viewer


# --- matriz completa (aceite 1) ------------------------------------------------------------------

@pytest.mark.parametrize("user_state", USER_STATES)
@pytest.mark.parametrize("role", ROLES)
def test_authorization_matrix_and_accessible_ids_agree(conn, role, user_state):
    user_id = _user(conn, "usuario.alvo", role, active=user_state == "active")
    other = _user(conn, "outro.usuario")
    associations = {}
    for state in ASSOCIATION_STATES:
        assoc = _association(conn, f"Associação {state}",
                             "inactive" if state.startswith("inactive") else "active")
        associations[state] = assoc
        if state in ("authorized", "inactive_authorized"):
            _link(conn, user_id, assoc)
        else:
            _link(conn, other, assoc)  # vínculo de outro usuário não concede nada

    for action, state in itertools.product(sorted(ACTIONS), ASSOCIATION_STATES):
        expected = _expected(role, action, state, user_state)
        got = authorize(conn, user_id, action, associations[state])
        assert got is expected, (role, user_state, action, state)

    for action in sorted(ACTIONS):
        ids = accessible_association_ids(conn, user_id, action)
        expected_ids = {associations[s] for s in ASSOCIATION_STATES
                        if _expected(role, action, s, user_state)}
        assert ids == expected_ids, (role, user_state, action)
        assert ids == {a for a in associations.values() if authorize(conn, user_id, action, a)}


def test_matrix_covers_every_combination():
    combos = list(itertools.product(ROLES, ACTIONS, ASSOCIATION_STATES, USER_STATES))
    assert len(combos) == 3 * 3 * 4 * 2
    granted = [c for c in combos if _expected(c[0], c[1], c[2], c[3])]
    assert len(granted) == 12 + 2 + 1  # admin ativo 12; operador 2; consulta 1


def test_unknown_user_association_or_action(conn):
    user_id = _user(conn, "admin.exemplo", "administrator")
    assoc = _association(conn)
    assert authorize(conn, uuid.uuid4(), "read", assoc) is False
    assert authorize(conn, user_id, "read", uuid.uuid4()) is False
    assert accessible_association_ids(conn, uuid.uuid4()) == frozenset()
    with pytest.raises(ValueError, match="ação desconhecida"):
        authorize(conn, user_id, "delete", assoc)
    with pytest.raises(ValueError, match="ação desconhecida"):
        accessible_association_ids(conn, user_id, "delete")


# --- efeito imediato, sem revogar sessão (aceite 2; T4) ------------------------------------------

def test_revoked_access_takes_effect_on_next_call_without_revoking_session(conn):
    admin = _user(conn, "admin.exemplo", "administrator")
    user = _user(conn, "operador.exemplo")
    assoc = _association(conn)
    grant_access(conn, actor_user_id=admin, user_id=user, association_id=assoc)
    session = login(conn, "operador.exemplo", SECRET, clock=CLOCK, params=FAST)
    assert isinstance(session, LoginSuccess)
    assert authorize(conn, user, "read", assoc) is True

    assert revoke_access(conn, actor_user_id=admin, user_id=user, association_id=assoc) is True

    assert authorize(conn, user, "read", assoc) is False
    assert accessible_association_ids(conn, user) == frozenset()
    assert resolve_session(conn, session.token, clock=CLOCK) is not None  # sessão segue válida


@pytest.mark.parametrize("direct_change", [
    "DELETE FROM user_associations WHERE user_id = %(u)s",
    "UPDATE associations SET status = 'inactive' WHERE id = %(a)s",
    "UPDATE users SET active = false WHERE id = %(u)s",
    "UPDATE users SET role = 'viewer' WHERE id = %(u)s",
])
def test_direct_database_changes_take_effect_on_next_call(conn, direct_change):
    user = _user(conn, "operador.exemplo")
    assoc = _association(conn)
    _link(conn, user, assoc)
    assert authorize(conn, user, "write", assoc) is True

    conn.execute(direct_change, {"u": user, "a": assoc})
    conn.commit()

    assert authorize(conn, user, "write", assoc) is False
    assert assoc not in accessible_association_ids(conn, user, "write")


# --- auditoria do acesso global do administrador (aceite 3) --------------------------------------

def test_admin_global_access_is_audited(conn):
    admin = _user(conn, "admin.exemplo", "administrator")
    assoc = _association(conn, status="inactive")

    assert authorize(conn, admin, "write", assoc) is True
    ids = accessible_association_ids(conn, admin, "read")

    events = _events(conn, "authz.global_access")
    assert events[0] == (admin, "association", assoc, "success", {"action": "write"})
    assert events[1] == (admin, "association", None, "success",
                         {"action": "read", "scope": "all", "count": len(ids)})


def test_non_admin_access_does_not_create_global_access_events(conn):
    user = _user(conn, "operador.exemplo")
    assoc = _association(conn)
    _link(conn, user, assoc)
    authorize(conn, user, "read", assoc)
    accessible_association_ids(conn, user)
    assert _events(conn, "authz.global_access") == []


# --- R6 / D-021: sem autoalteração (aceite 4) ----------------------------------------------------

def test_admin_cannot_grant_or_revoke_own_access_or_change_own_role(conn):
    admin = _user(conn, "admin.exemplo", "administrator")
    assoc = _association(conn)

    for call in (
        lambda: grant_access(conn, actor_user_id=admin, user_id=admin, association_id=assoc),
        lambda: revoke_access(conn, actor_user_id=admin, user_id=admin, association_id=assoc),
        lambda: change_role(conn, actor_user_id=admin, user_id=admin, new_role="viewer",
                            clock=CLOCK),
    ):
        with pytest.raises(AuthorizationDenied) as info:
            call()
        assert info.value.reason == "self_change"

    assert conn.execute("SELECT role FROM users WHERE id = %s", (admin,)).fetchone()[0] == \
        "administrator"
    conn.commit()
    for action in ("authz.grant_access", "authz.revoke_access", "authz.change_role"):
        [event] = _events(conn, action)
        assert (event[0], event[3], event[4]["reason"]) == (admin, "denied", "self_change")


def test_another_admin_can_make_the_same_changes(conn):
    admin_a = _user(conn, "admin.a", "administrator")
    admin_b = _user(conn, "admin.b", "administrator")
    assoc = _association(conn)

    assert grant_access(conn, actor_user_id=admin_b, user_id=admin_a, association_id=assoc)
    assert revoke_access(conn, actor_user_id=admin_b, user_id=admin_a, association_id=assoc)
    assert change_role(conn, actor_user_id=admin_b, user_id=admin_a, new_role="operator",
                       clock=CLOCK) is True

    assert conn.execute("SELECT role FROM users WHERE id = %s", (admin_a,)).fetchone()[0] == "operator"
    conn.commit()
    results = [e[3] for a in ("authz.grant_access", "authz.revoke_access", "authz.change_role")
               for e in _events(conn, a)]
    assert results == ["success", "success", "success"]


@pytest.mark.parametrize("actor", ["operator", "viewer", "inactive_admin"])
def test_non_admin_actor_is_denied_and_audited(conn, actor):
    actor_id = _user(conn, "ator.exemplo",
                     "administrator" if actor == "inactive_admin" else actor,
                     active=actor != "inactive_admin")
    target = _user(conn, "alvo.exemplo")
    assoc = _association(conn)

    with pytest.raises(AuthorizationDenied) as info:
        grant_access(conn, actor_user_id=actor_id, user_id=target, association_id=assoc)
    assert info.value.reason == "actor_not_admin"
    with pytest.raises(AuthorizationDenied):
        change_role(conn, actor_user_id=actor_id, user_id=target, new_role="administrator",
                    clock=CLOCK)

    assert authorize(conn, target, "read", assoc) is False
    assert [e[3] for e in _events(conn, "authz.grant_access")] == ["denied"]
    assert conn.execute("SELECT role FROM users WHERE id = %s", (target,)).fetchone()[0] == "operator"
    conn.commit()


def test_operator_cannot_grant_itself_access(conn):
    operator = _user(conn, "operador.exemplo")
    assoc = _association(conn)
    with pytest.raises(AuthorizationDenied) as info:
        grant_access(conn, actor_user_id=operator, user_id=operator, association_id=assoc)
    assert info.value.reason == "actor_not_admin"
    assert authorize(conn, operator, "read", assoc) is False


def test_grant_is_idempotent_and_records_creator(conn):
    admin = _user(conn, "admin.exemplo", "administrator")
    user = _user(conn, "operador.exemplo")
    assoc = _association(conn)
    assert grant_access(conn, actor_user_id=admin, user_id=user, association_id=assoc) is True
    assert grant_access(conn, actor_user_id=admin, user_id=user, association_id=assoc) is False
    rows = conn.execute("SELECT created_by FROM user_associations WHERE user_id = %s",
                        (user,)).fetchall()
    conn.commit()
    assert rows == [(admin,)]
    assert [e[4]["created"] for e in _events(conn, "authz.grant_access")] == [True, False]


def test_change_role_revokes_open_sessions_in_same_transaction(conn):
    admin = _user(conn, "admin.exemplo", "administrator")
    user = _user(conn, "operador.exemplo")
    session = login(conn, "operador.exemplo", SECRET, clock=CLOCK, params=FAST)

    assert change_role(conn, actor_user_id=admin, user_id=user, new_role="viewer", clock=CLOCK)

    assert resolve_session(conn, session.token, clock=CLOCK) is None
    [revoke_event] = _events(conn, "auth.revoke_sessions")
    assert (revoke_event[0], revoke_event[4]) == (admin, {"revoked": 1})
    assert change_role(conn, actor_user_id=admin, user_id=user, new_role="viewer",
                       clock=CLOCK) is False  # sem mudança, nada revogado


def test_unknown_actor_target_or_role_raises(conn):
    admin = _user(conn, "admin.exemplo", "administrator")
    assoc = _association(conn)
    with pytest.raises(ValueError, match="ator"):
        grant_access(conn, actor_user_id=uuid.uuid4(), user_id=admin, association_id=assoc)
    with pytest.raises(ValueError, match="alvo"):
        grant_access(conn, actor_user_id=admin, user_id=uuid.uuid4(), association_id=assoc)
    with pytest.raises(ValueError, match="perfil"):
        change_role(conn, actor_user_id=admin, user_id=admin, new_role="root", clock=CLOCK)
    assert _events(conn, "authz.grant_access") == []


# --- dados de documento não concedem acesso (aceite 5) -------------------------------------------

def test_documents_in_catalog_do_not_grant_access(conn):
    user = _user(conn, "consulta.exemplo", "viewer")
    assoc = _association(conn)
    source = conn.execute(
        "INSERT INTO document_sources (name, root_path, normalization_policy) "
        "VALUES ('Fonte', '/lab/servidor-teste', 'exact') RETURNING id"
    ).fetchone()[0]
    run = conn.execute("INSERT INTO index_runs (source_id) VALUES (%s) RETURNING id",
                       (source,)).fetchone()[0]
    conn.execute(
        "INSERT INTO documents (source_id, relative_path, path_key, name, extension, size_bytes, "
        "source_modified_at, last_seen_run_id) VALUES (%s, 'ASSOCIAÇÕES/Associação Exemplo Aurora/"
        "Estatuto.pdf', 'k', 'Estatuto.pdf', 'pdf', 1, now(), %s)", (source, run),
    )
    conn.commit()
    # documents ainda não tem vínculo com associação; sugestões e mapeamentos não existem.
    assert authorize(conn, user, "read", assoc) is False
    assert accessible_association_ids(conn, user) == frozenset()


def test_authorization_source_reads_only_allowed_tables():
    """Apoio à revisão de código: SQL de authorize/accessible_association_ids."""
    import inspect
    import re

    for fn in (authorization.authorize, authorization.accessible_association_ids):
        source = inspect.getsource(fn)
        tables = set(re.findall(r"(?:FROM|JOIN)\s+([a-z_]+)", source))
        assert tables <= {"users", "associations", "user_associations"}, (fn.__name__, tables)


# --- concorrência: mudança do ator durante a concessão -------------------------------------------

def _waiting(observer, pid):
    count = observer.execute(
        "SELECT count(*) FROM pg_locks WHERE pid = %s AND NOT granted", (pid,)).fetchone()[0]
    observer.commit()
    return count > 0


def test_actor_demoted_while_grant_waits_is_denied(conn, database_url):
    admin = _user(conn, "admin.exemplo", "administrator")
    user = _user(conn, "operador.exemplo")
    assoc = _association(conn)
    outcome, ready = {}, threading.Event()

    with connect_checked(database_url) as changer:
        changer.rollback()
        changer.execute("UPDATE users SET role = 'viewer' WHERE id = %s", (admin,))

        def run():
            with connect_checked(database_url) as c:
                c.rollback()
                outcome["pid"] = c.info.backend_pid
                ready.set()
                try:
                    grant_access(c, actor_user_id=admin, user_id=user, association_id=assoc)
                    outcome["result"] = "granted"
                except AuthorizationDenied as exc:
                    outcome["result"] = exc.reason

        thread = threading.Thread(target=run)
        thread.start()
        assert ready.wait(10)
        deadline, waited = time.monotonic() + 5, False
        while time.monotonic() < deadline and not waited:
            waited = _waiting(conn, outcome["pid"])
            time.sleep(0.02)
        changer.commit()
    thread.join(30)

    assert outcome["result"] == "actor_not_admin"
    assert authorize(conn, user, "read", assoc) is False
    assert waited, "concessão não esperou a mudança do ator"
