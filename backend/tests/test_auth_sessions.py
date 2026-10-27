"""S0-07: login, sessões, revogação e auditoria de autenticação. Dados e senhas fictícios."""
import hashlib
import logging
import traceback
from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher
from psycopg import errors

import app.auth.sessions as sessions
from app.auth.passwords import PRODUCTION_PARAMETERS, HashParameters, hash_password
from app.auth.sessions import (
    ABSOLUTE_LIFETIME,
    IDLE_TIMEOUT,
    LOGIN_FAILED,
    LoginFailure,
    LoginSuccess,
    login,
    logout,
    resolve_session,
    revoke_user_sessions,
)

FAST = HashParameters(time_cost=1, memory_cost_kib=1024, parallelism=1)
OLDER = HashParameters(time_cost=1, memory_cost_kib=2048, parallelism=1)  # "parâmetros antigos"
SECRET = "senha-ficticia-sessao-2026"
START = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


class FakeClock:
    """Relógio injetável (T8): avança só quando o teste manda."""

    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return FakeClock()


def _user(conn, login="operador.exemplo", password=SECRET, role="operator", active=True,
          params=FAST):
    user_id = conn.execute(
        "INSERT INTO users (name, login, password_hash, role, active) "
        "VALUES ('Usuário Exemplo', %s, %s, %s, %s) RETURNING id",
        (login, hash_password(password, params), role, active),
    ).fetchone()[0]
    conn.commit()
    return user_id


def _login(conn, clock, login_name="operador.exemplo", password=SECRET, params=FAST):
    return login(conn, login_name, password, clock=clock, params=params)


def _events(conn, action=None):
    rows = conn.execute(
        "SELECT actor_type, actor_user_id, actor_service, action, target_type, target_id, result, "
        "details, occurred_at FROM audit_events ORDER BY occurred_at, id"
    ).fetchall()
    conn.commit()
    return [r for r in rows if action is None or r[3] == action]


def _session_row(conn, session_id):
    row = conn.execute(
        "SELECT revoked_at, revoked_reason, last_used_at FROM sessions WHERE id = %s", (session_id,)
    ).fetchone()
    conn.commit()
    return row


def _password_hash(conn, user_id):
    value = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()[0]
    conn.commit()
    return value


# --- login e sessão ------------------------------------------------------------------------------

def test_login_creates_session_storing_only_token_hash(conn, clock):
    user_id = _user(conn)
    result = _login(conn, clock)

    assert isinstance(result, LoginSuccess)
    assert (result.user_id, result.role, result.expires_at) == (
        user_id, "operator", START + ABSOLUTE_LIFETIME)
    assert len(result.token) >= 43
    stored = conn.execute(
        "SELECT token_hash, created_at, last_used_at, expires_at, revoked_at FROM sessions"
    ).fetchone()
    conn.commit()
    assert bytes(stored[0]) == hashlib.sha256(result.token.encode()).digest()
    assert stored[1:] == (START, START, START + ABSOLUTE_LIFETIME, None)


def test_tokens_are_unique_per_login(conn, clock):
    _user(conn)
    tokens = {_login(conn, clock).token for _ in range(5)}
    assert len(tokens) == 5


def test_login_is_case_insensitive_on_login(conn, clock):
    _user(conn, login="Operador.Exemplo")
    assert isinstance(_login(conn, clock, "OPERADOR.EXEMPLO"), LoginSuccess)


def test_resolve_returns_current_user_state(conn, clock):
    user_id = _user(conn)
    token = _login(conn, clock).token

    info = resolve_session(conn, token, clock=clock)

    assert (info.user_id, info.login, info.role) == (user_id, "operador.exemplo", "operator")


@pytest.mark.parametrize("bad", [None, "", "x" * 500, "não-ascii-ç", 123, b"bytes"])
def test_resolve_rejects_malformed_or_unknown_tokens(conn, clock, bad):
    _user(conn)
    _login(conn, clock)
    assert resolve_session(conn, bad, clock=clock) is None


def test_resolve_rejects_tampered_token(conn, clock):
    _user(conn)
    token = _login(conn, clock).token
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert resolve_session(conn, tampered, clock=clock) is None
    assert resolve_session(conn, token, clock=clock) is not None


# --- expiração (R3) com relógio injetado (T8) ----------------------------------------------------

def test_idle_timeout_boundary(conn, clock):
    _user(conn)
    token = _login(conn, clock).token

    clock.advance(seconds=IDLE_TIMEOUT.total_seconds() - 1)
    assert resolve_session(conn, token, clock=clock) is not None  # renova o último uso
    clock.advance(seconds=IDLE_TIMEOUT.total_seconds() - 1)
    assert resolve_session(conn, token, clock=clock) is not None
    clock.advance(minutes=30)
    assert resolve_session(conn, token, clock=clock) is None


def test_idle_timeout_exactly_30_minutes_expires(conn, clock):
    _user(conn)
    token = _login(conn, clock).token
    clock.advance(minutes=30)
    assert resolve_session(conn, token, clock=clock) is None


def test_absolute_lifetime_expires_even_with_activity(conn, clock):
    _user(conn)
    token = _login(conn, clock).token
    for _ in range(int(ABSOLUTE_LIFETIME / timedelta(minutes=20)) - 1):
        clock.advance(minutes=20)
        assert resolve_session(conn, token, clock=clock) is not None
    clock.now = START + ABSOLUTE_LIFETIME - timedelta(seconds=1)
    assert resolve_session(conn, token, clock=clock) is not None
    clock.now = START + ABSOLUTE_LIFETIME
    assert resolve_session(conn, token, clock=clock) is None


def test_r3_values():
    assert (IDLE_TIMEOUT, ABSOLUTE_LIFETIME) == (timedelta(minutes=30), timedelta(hours=10))


def test_naive_clock_rejected(conn):
    _user(conn)
    with pytest.raises(ValueError, match="fuso"):
        login(conn, "operador.exemplo", SECRET, clock=lambda: datetime(2026, 1, 1), params=FAST)


# --- logout e revogação (T5) ---------------------------------------------------------------------

def test_logout_revokes_only_that_session(conn, clock):
    _user(conn)
    first, second = _login(conn, clock), _login(conn, clock)

    assert logout(conn, first.token, clock=clock) is True
    assert resolve_session(conn, first.token, clock=clock) is None
    assert resolve_session(conn, second.token, clock=clock) is not None
    assert _session_row(conn, first.session_id)[:2] == (START, "logout")
    assert logout(conn, first.token, clock=clock) is False  # já revogada
    assert logout(conn, "token-inexistente", clock=clock) is False


def test_revoke_user_sessions_revokes_all_of_that_user(conn, clock):
    user_id = _user(conn)
    other_id = _user(conn, login="outro.usuario")
    mine = [_login(conn, clock) for _ in range(3)]
    other = _login(conn, clock, "outro.usuario")
    admin_id = _user(conn, login="admin.exemplo", role="administrator")

    assert revoke_user_sessions(conn, user_id, actor_user_id=admin_id, clock=clock) == 3
    assert all(resolve_session(conn, s.token, clock=clock) is None for s in mine)
    assert resolve_session(conn, other.token, clock=clock) is not None
    assert {_session_row(conn, s.session_id)[1] for s in mine} == {"revoked"}
    assert revoke_user_sessions(conn, user_id, actor_service="bootstrap", clock=clock) == 0
    assert other_id


@pytest.mark.parametrize("actors", [{}, {"actor_user_id": "x", "actor_service": "y"}])
def test_revoke_requires_exactly_one_actor(conn, clock, actors):
    user_id = _user(conn)
    with pytest.raises(ValueError, match="exatamente um ator"):
        revoke_user_sessions(conn, user_id, clock=clock, **actors)


# --- estado atual do usuário sem revogação (T4; aceite 5) ----------------------------------------

def test_direct_deactivation_stops_resolution_without_revoking(conn, clock):
    user_id = _user(conn)
    result = _login(conn, clock)
    conn.execute("UPDATE users SET active = false WHERE id = %s", (user_id,))
    conn.commit()

    assert resolve_session(conn, result.token, clock=clock) is None
    assert _session_row(conn, result.session_id)[:2] == (None, None)  # não revogada

    conn.execute("UPDATE users SET active = true WHERE id = %s", (user_id,))
    conn.commit()
    assert resolve_session(conn, result.token, clock=clock) is not None


def test_direct_role_change_is_seen_on_next_resolution_without_revoking(conn, clock):
    user_id = _user(conn)
    result = _login(conn, clock)
    assert resolve_session(conn, result.token, clock=clock).role == "operator"

    conn.execute("UPDATE users SET role = 'viewer' WHERE id = %s", (user_id,))
    conn.commit()

    assert resolve_session(conn, result.token, clock=clock).role == "viewer"
    assert _session_row(conn, result.session_id)[:2] == (None, None)


# --- falhas uniformes (T7; aceite 6) -------------------------------------------------------------

class _Spy:
    def __init__(self, real):
        self.real, self.calls = real, []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        return self.real(*args, **kwargs)


@pytest.fixture
def spies(monkeypatch):
    result = {}
    for name in ("_find_user", "verify_password", "_audit", "needs_rehash"):
        spy = _Spy(getattr(sessions, name))
        monkeypatch.setattr(sessions, name, spy)
        result[name] = spy
    return result


FAILURE_CASES = {
    "unknown_login": lambda conn: ("nao.existe", SECRET),
    "inactive": lambda conn: (_user(conn, login="inativo", active=False) and "inativo", SECRET),
    "wrong_password": lambda conn: (_user(conn, login="errado") and "errado", SECRET + "x"),
}


@pytest.mark.parametrize("case", FAILURE_CASES, ids=FAILURE_CASES.keys())
def test_failures_share_result_and_processing_steps(conn, clock, spies, case):
    login_name, password = FAILURE_CASES[case](conn)
    for spy in spies.values():
        spy.calls.clear()

    result = _login(conn, clock, login_name, password)

    assert result is LOGIN_FAILED
    assert result == LoginFailure() and repr(result) == repr(LOGIN_FAILED)
    assert len(spies["_find_user"].calls) == 1
    assert len(spies["verify_password"].calls) == 1  # inclusive com hash fictício
    assert len(spies["_audit"].calls) == 1
    assert spies["needs_rehash"].calls == []
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    [event] = _events(conn, "auth.login")
    assert (event[6], event[7]) == ("failure", {"reason": case})


def test_unknown_login_verifies_against_argon2id_dummy(conn, clock, spies):
    _login(conn, clock, "nao.existe")
    stored_hash = spies["verify_password"].calls[0][0]
    assert stored_hash.startswith("$argon2id$v=19$m=1024,t=1,p=1$")


@pytest.mark.parametrize("bad", [None, 123, "", "joão", "x" * 500])
def test_malformed_login_input_fails_uniformly(conn, clock, bad):
    _user(conn)
    assert login(conn, bad, SECRET, clock=clock, params=FAST) is LOGIN_FAILED
    assert login(conn, "operador.exemplo", bad, clock=clock, params=FAST) is LOGIN_FAILED


# --- rehash só após verificação (T2; aceite 8) ---------------------------------------------------

def test_successful_login_rehashes_old_parameters(conn, clock, spies):
    user_id = _user(conn, params=OLDER)
    old_hash = _password_hash(conn, user_id)

    result = _login(conn, clock, params=FAST)

    assert isinstance(result, LoginSuccess)
    new_hash = _password_hash(conn, user_id)
    assert new_hash != old_hash and new_hash.startswith("$argon2id$v=19$m=1024,t=1,p=1$")
    assert spies["verify_password"].calls and spies["needs_rehash"].calls
    assert _events(conn, "auth.login")[-1][7]["rehashed"] is True
    assert isinstance(_login(conn, clock, params=FAST), LoginSuccess)


def test_current_parameters_are_not_rehashed(conn, clock):
    user_id = _user(conn, params=FAST)
    old_hash = _password_hash(conn, user_id)
    _login(conn, clock, params=FAST)
    assert _password_hash(conn, user_id) == old_hash


@pytest.mark.parametrize("scenario", ["wrong_password", "invalid_hash", "inactive"])
def test_rehash_never_happens_without_successful_verification(conn, clock, spies, scenario):
    user_id = _user(conn, params=OLDER, active=scenario != "inactive")
    if scenario == "invalid_hash":
        conn.execute("UPDATE users SET password_hash = '$argon2id$corrompido' WHERE id = %s",
                     (user_id,))
        conn.commit()
    before = _password_hash(conn, user_id)
    password = SECRET + "x" if scenario == "wrong_password" else SECRET

    assert _login(conn, clock, password=password, params=FAST) is LOGIN_FAILED
    assert _password_hash(conn, user_id) == before
    assert spies["needs_rehash"].calls == []


def test_password_below_current_policy_logs_in_without_rehash(conn, clock):
    legacy = "curta-123"  # aceita antes da política atual; hash criado fora dela
    legacy_hash = PasswordHasher(time_cost=1, memory_cost=2048, parallelism=1).hash(legacy)
    user_id = conn.execute(
        "INSERT INTO users (name, login, password_hash, role) VALUES ('L', 'legado', %s, 'viewer') "
        "RETURNING id", (legacy_hash,),
    ).fetchone()[0]
    conn.commit()

    assert isinstance(_login(conn, clock, "legado", legacy, params=FAST), LoginSuccess)
    assert _password_hash(conn, user_id) == legacy_hash
    assert _events(conn, "auth.login")[-1][7]["rehashed"] is False


# --- auditoria (aceite 7) ------------------------------------------------------------------------

def test_authentication_events_have_actor_action_target_result_and_date(conn, clock):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _login(conn, clock, password="errada-mas-longa-123")
    success = _login(conn, clock)
    logout(conn, success.token, clock=clock)
    _login(conn, clock)
    revoke_user_sessions(conn, user_id, actor_user_id=admin_id, clock=clock)

    events = _events(conn)
    summary = [(e[0], e[1], e[2], e[3], e[4], e[5], e[6]) for e in events]
    assert summary == [
        ("service", None, "authentication", "auth.login", "user", user_id, "failure"),
        ("user", user_id, None, "auth.login", "user", user_id, "success"),
        ("user", user_id, None, "auth.logout", "user", user_id, "success"),
        ("user", user_id, None, "auth.login", "user", user_id, "success"),
        ("user", admin_id, None, "auth.revoke_sessions", "user", user_id, "success"),
    ]
    assert all(e[8] is not None for e in events)
    assert events[-1][7] == {"revoked": 1}


def test_unknown_login_event_has_no_target_and_no_login_text(conn, clock):
    _login(conn, clock, "login-digitado-errado")
    [event] = _events(conn)
    assert (event[4], event[5]) == (None, None)
    assert "login-digitado-errado" not in str(event)


# --- token e senha fora de tabelas, logs, exceções e repr (aceite 2) -----------------------------

def test_token_and_password_never_exposed(conn, clock, caplog):
    caplog.set_level(logging.DEBUG)
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _login(conn, clock, password=SECRET + "-errada")
    result = _login(conn, clock)
    resolve_session(conn, result.token, clock=clock)
    second = _login(conn, clock)
    logout(conn, result.token, clock=clock)
    revoke_user_sessions(conn, user_id, actor_user_id=admin_id, clock=clock)

    dump = "\n".join(
        r[0] for r in conn.execute(
            "SELECT row_to_json(s)::text FROM sessions s "
            "UNION ALL SELECT row_to_json(e)::text FROM audit_events e"
        ).fetchall()
    )
    conn.commit()
    for secret in (SECRET, result.token, second.token):
        assert secret not in dump
        assert secret not in caplog.text
    assert result.token not in repr(result) and second.token not in str(second)

    conn.execute("SELECT 1")  # transação aberta: funções recusam com exceção
    with pytest.raises(ValueError) as info:
        login(conn, "operador.exemplo", SECRET, clock=clock, params=FAST)
    rendered = "".join(traceback.format_exception(info.value))
    assert SECRET not in rendered
    conn.rollback()


def test_requires_idle_non_autocommit_connection(conn, clock, database_url):
    from db_guard import connect_checked

    _user(conn)
    conn.execute("SELECT 1")
    for call in (
        lambda c: login(c, "operador.exemplo", SECRET, clock=clock, params=FAST),
        lambda c: resolve_session(c, "x", clock=clock),
        lambda c: logout(c, "x", clock=clock),
    ):
        with pytest.raises(ValueError, match="sem transação aberta"):
            call(conn)
    conn.rollback()
    with connect_checked(database_url, autocommit=True) as auto:
        with pytest.raises(ValueError, match="autocommit"):
            login(auto, "operador.exemplo", SECRET, clock=clock, params=FAST)


# --- restrições da tabela sessions ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("token_hash", "created", "last_used", "expires", "revoked", "reason", "error"),
    [
        (b"x" * 31, 0, 0, 1, None, None, errors.CheckViolation),
        (b"x" * 32, 1, 0, 2, None, None, errors.CheckViolation),     # uso antes da criação
        (b"x" * 32, 0, 0, 0, None, None, errors.CheckViolation),     # expira na criação
        (b"x" * 32, 0, 0, 1, 0, None, errors.CheckViolation),        # revogada sem motivo
        (b"x" * 32, 0, 0, 1, None, "logout", errors.CheckViolation),  # motivo sem data
        (b"x" * 32, 0, 0, 1, 0, "outro", errors.CheckViolation),
    ],
)
def test_session_constraints(conn, token_hash, created, last_used, expires, revoked, reason, error):
    user_id = _user(conn)
    at = lambda h: None if h is None else START + timedelta(hours=h)  # noqa: E731
    with pytest.raises(error):
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, last_used_at, expires_at, "
            "revoked_at, revoked_reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, token_hash, at(created), at(last_used), at(expires), at(revoked), reason),
        )


def test_session_user_must_exist_and_blocks_user_deletion(conn, clock):
    import uuid

    user_id = _user(conn)
    _login(conn, clock)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.rollback()
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, last_used_at, expires_at) "
            "VALUES (%s, %s, now(), now(), now() + interval '1 hour')",
            (uuid.uuid4(), b"y" * 32),
        )


def test_production_parameters_are_default_for_login():
    assert sessions.login.__kwdefaults__["params"] == PRODUCTION_PARAMETERS


# --- concorrência com alterações em users (ordem transacional) -----------------------------------
#
# Ordem estabelecida: login trava a linha do usuário (SELECT ... FOR NO KEY UPDATE) em
# READ COMMITTED antes de verificar a senha. Alteração confirmada antes da trava é vista pelo
# login; alteração iniciada depois espera o commit do login.

import threading  # noqa: E402
import time  # noqa: E402

from psycopg import IsolationLevel  # noqa: E402

from db_guard import connect_checked  # noqa: E402

NEW_SECRET = "senha-ficticia-substituta-2026"
ISOLATIONS = {
    "default": lambda c: None,
    "session_repeatable_read": lambda c: c.execute(
        "SET default_transaction_isolation = 'repeatable read'"),
    "session_serializable": lambda c: c.execute(
        "SET default_transaction_isolation = 'serializable'"),
    "psycopg_repeatable_read": lambda c: setattr(c, "isolation_level", IsolationLevel.REPEATABLE_READ),
}


def _waiting(observer, pid) -> bool:
    count = observer.execute(
        "SELECT count(*) FROM pg_locks WHERE pid = %s AND NOT granted", (pid,)
    ).fetchone()[0]
    observer.commit()
    return count > 0


def _wait_until_blocked(observer, pid, seconds=5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _waiting(observer, pid):
            return True
        time.sleep(0.02)
    return False


def _sessions_of(conn, user_id):
    count = conn.execute("SELECT count(*) FROM sessions WHERE user_id = %s", (user_id,)).fetchone()[0]
    conn.commit()
    return count


CHANGES = {
    # alteração concorrente, senha usada no login, resultado esperado, motivo da falha
    "password_changed_old_password": (
        "UPDATE users SET password_hash = %(new_hash)s WHERE id = %(id)s", SECRET, "failure",
        "wrong_password"),
    "password_changed_new_password": (
        "UPDATE users SET password_hash = %(new_hash)s WHERE id = %(id)s", NEW_SECRET, "success",
        None),
    "deactivated": (
        "UPDATE users SET active = false WHERE id = %(id)s", SECRET, "failure", "inactive"),
}


@pytest.mark.parametrize("isolation", ISOLATIONS.values(), ids=ISOLATIONS.keys())
@pytest.mark.parametrize("change", CHANGES, ids=CHANGES.keys())
def test_change_committed_while_login_waits_is_seen_by_login(conn, database_url, clock, change,
                                                              isolation):
    sql, password, expected, reason = CHANGES[change]
    user_id = _user(conn)
    params = {"new_hash": hash_password(NEW_SECRET, FAST), "id": user_id}
    outcome, failures, ready = {}, [], threading.Event()

    with connect_checked(database_url) as changer:
        changer.rollback()
        changer.execute(sql, params)  # linha travada, ainda não confirmada

        def run_login():
            try:
                with connect_checked(database_url) as c:
                    c.rollback()
                    isolation(c)
                    c.commit()
                    outcome["pid"] = c.info.backend_pid
                    ready.set()
                    outcome["result"] = login(c, "operador.exemplo", password, clock=clock,
                                              params=FAST)
            except BaseException as exc:  # noqa: BLE001 - repassado ao teste
                failures.append(exc)
                ready.set()

        thread = threading.Thread(target=run_login)
        thread.start()
        assert ready.wait(10)
        waited = "pid" in outcome and _wait_until_blocked(conn, outcome["pid"])
        changer.commit()
    thread.join(30)

    assert not failures, failures
    result = outcome["result"]
    if expected == "success":
        assert isinstance(result, LoginSuccess)
        assert _sessions_of(conn, user_id) == 1
    else:
        assert result is LOGIN_FAILED
        assert _sessions_of(conn, user_id) == 0  # nenhuma sessão com credencial substituída
        assert _events(conn, "auth.login")[-1][7] == {"reason": reason}
    assert waited, "login não esperou a alteração em andamento"


@pytest.mark.parametrize("change", ["password", "deactivate"])
def test_change_started_during_login_waits_for_login_commit(conn, database_url, clock,
                                                            monkeypatch, change):
    user_id = _user(conn)
    sql = ("UPDATE users SET password_hash = %(new_hash)s WHERE id = %(id)s" if change == "password"
           else "UPDATE users SET active = false WHERE id = %(id)s")
    params = {"new_hash": hash_password(NEW_SECRET, FAST), "id": user_id}
    in_verify, release = threading.Event(), threading.Event()
    order, failures, outcome = [], [], {}
    real_verify = sessions.verify_password

    def paused_verify(*args):
        in_verify.set()  # login já leu (e, na ordem correta, travou) a linha do usuário
        assert release.wait(30)
        return real_verify(*args)

    monkeypatch.setattr(sessions, "verify_password", paused_verify)

    def run_login():
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                outcome["result"] = login(c, "operador.exemplo", SECRET, clock=clock, params=FAST)
                order.append("login_committed")
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    def run_change():
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                outcome["changer_pid"] = c.info.backend_pid
                c.execute(sql, params)
                c.commit()
                order.append("change_committed")
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    login_thread = threading.Thread(target=run_login)
    login_thread.start()
    assert in_verify.wait(10)
    change_thread = threading.Thread(target=run_change)
    change_thread.start()
    deadline = time.monotonic() + 10
    while "changer_pid" not in outcome and time.monotonic() < deadline:
        time.sleep(0.01)
    change_blocked = _wait_until_blocked(conn, outcome["changer_pid"], seconds=3)
    release.set()
    login_thread.join(30)
    change_thread.join(30)

    assert not failures, failures
    # A sessão só pode existir se o login foi confirmado antes da alteração.
    assert isinstance(outcome["result"], LoginSuccess)
    assert order == ["login_committed", "change_committed"]
    assert change_blocked, "alteração não esperou o login em andamento"
    assert _sessions_of(conn, user_id) == 1
