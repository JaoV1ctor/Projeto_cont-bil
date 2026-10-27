"""S0-08: limite de tentativas por login (R4/D-019). Dados e senhas fictícios."""
import threading
from collections import Counter
import time
from datetime import datetime, timedelta, timezone

import pytest
from psycopg import errors

import app.auth.sessions as sessions
from app.auth.lockout import LOCKOUT_DURATION, LOCKOUT_THRESHOLD, LOCKOUT_WINDOW, unlock_user
from app.auth.passwords import HashParameters, hash_password
from app.auth.sessions import LOGIN_FAILED, LoginSuccess, login
from db_guard import connect_checked

FAST = HashParameters(time_cost=1, memory_cost_kib=1024, parallelism=1)
SECRET = "senha-ficticia-bloqueio-2026"
WRONG = "senha-ficticia-errada-0000"
START = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return FakeClock()


def _user(conn, login="operador.exemplo", role="operator", active=True):
    user_id = conn.execute(
        "INSERT INTO users (name, login, password_hash, role, active) "
        "VALUES ('Usuário Exemplo', %s, %s, %s, %s) RETURNING id",
        (login, hash_password(SECRET, FAST), role, active),
    ).fetchone()[0]
    conn.commit()
    return user_id


def _try(conn, clock, password=SECRET, login_name="operador.exemplo", **kwargs):
    return login(conn, login_name, password, clock=clock, params=FAST, **kwargs)


def _fail(conn, clock, times, step_seconds=0):
    for _ in range(times):
        assert _try(conn, clock, WRONG) is LOGIN_FAILED
        if step_seconds:
            clock.advance(seconds=step_seconds)


def _rows(conn, sql, *args):
    rows = conn.execute(sql, args).fetchall()
    conn.commit()
    return rows


def _attempts(conn, user_id) -> Counter:
    """Contagem por resultado; tentativas no mesmo instante não têm ordem definida."""
    return Counter(r[0] for r in _rows(
        conn, "SELECT result FROM login_attempts WHERE user_id = %s", user_id))


def _lockouts(conn, user_id):
    return _rows(conn, "SELECT locked_at, locked_until, unlocked_at, unlocked_by FROM login_lockouts "
                       "WHERE user_id = %s ORDER BY locked_at", user_id)


def _events(conn, action):
    return _rows(conn, "SELECT actor_type, actor_user_id, actor_service, target_id, result, details "
                       "FROM audit_events WHERE action = %s ORDER BY occurred_at, id", action)


def test_r4_values():
    assert (LOCKOUT_THRESHOLD, LOCKOUT_WINDOW, LOCKOUT_DURATION) == (
        5, timedelta(minutes=15), timedelta(minutes=15))


# --- limite exato e duração (aceite 1) -----------------------------------------------------------

def test_four_failures_do_not_lock(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    assert isinstance(_try(conn, clock), LoginSuccess)
    assert _lockouts(conn, user_id) == []


def test_fifth_failure_locks_and_correct_password_then_fails(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)

    [(locked_at, locked_until, unlocked_at, _)] = _lockouts(conn, user_id)
    assert (locked_at, locked_until, unlocked_at) == (START, START + LOCKOUT_DURATION, None)
    assert _try(conn, clock) is LOGIN_FAILED  # senha correta, bloqueado (aceite 2)
    assert _attempts(conn, user_id) == Counter(failure=5, blocked=1)
    assert _rows(conn, "SELECT count(*) FROM sessions")[0][0] == 0


def test_lock_expires_exactly_after_duration(conn, clock):
    _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    clock.advance(seconds=LOCKOUT_DURATION.total_seconds() - 1)
    assert _try(conn, clock) is LOGIN_FAILED
    clock.advance(seconds=1)
    assert isinstance(_try(conn, clock), LoginSuccess)


def test_attempts_during_lock_do_not_extend_it(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    for _ in range(10):
        clock.advance(minutes=1)
        assert _try(conn, clock, WRONG) is LOGIN_FAILED
    clock.now = START + LOCKOUT_DURATION
    assert isinstance(_try(conn, clock), LoginSuccess)
    assert len(_lockouts(conn, user_id)) == 1


def test_failure_after_expiry_starts_new_count(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    clock.now = START + LOCKOUT_DURATION
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    assert isinstance(_try(conn, clock), LoginSuccess)
    assert len(_lockouts(conn, user_id)) == 1


@pytest.mark.parametrize(("offset", "locks"), [
    (LOCKOUT_WINDOW - timedelta(seconds=1), True),  # 5ª falha ainda dentro da janela
    (LOCKOUT_WINDOW, False),                        # 1ª falha já saiu da janela
])
def test_window_boundary(conn, clock, offset, locks):
    user_id = _user(conn)
    _fail(conn, clock, 1)
    clock.advance(minutes=1)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 2)
    clock.now = START + offset
    _fail(conn, clock, 1)
    assert bool(_lockouts(conn, user_id)) is locks


def test_success_resets_count(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    assert isinstance(_try(conn, clock), LoginSuccess)
    clock.advance(seconds=1)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)  # 8 falhas na janela, só 4 após o sucesso
    assert _lockouts(conn, user_id) == []
    clock.advance(seconds=1)
    _fail(conn, clock, 1)  # 5ª falha após o sucesso
    assert len(_lockouts(conn, user_id)) == 1


def test_inactive_user_failures_count_and_keep_uniform_result(conn, clock):
    user_id = _user(conn, active=False)
    for _ in range(LOCKOUT_THRESHOLD):
        assert _try(conn, clock) is LOGIN_FAILED
    assert len(_lockouts(conn, user_id)) == 1


# --- resultado uniforme e caminho T7 (aceite 2) --------------------------------------------------

def test_locked_login_follows_t7_path(conn, clock, monkeypatch):
    _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    calls = {"find": 0, "verify": 0, "rehash": 0}
    real = (sessions._find_user, sessions.verify_password, sessions.needs_rehash)

    def count(name, fn):
        def wrapper(*args, **kwargs):
            calls[name] += 1
            return fn(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(sessions, "_find_user", count("find", real[0]))
    monkeypatch.setattr(sessions, "verify_password", count("verify", real[1]))
    monkeypatch.setattr(sessions, "needs_rehash", count("rehash", real[2]))

    result = _try(conn, clock)

    assert result is LOGIN_FAILED
    assert calls == {"find": 1, "verify": 1, "rehash": 0}
    last = _events(conn, "auth.login")[-1]
    assert (last[4], last[5]) == ("failure", {"reason": "locked"})


# --- concorrência no limiar (aceite 3) -----------------------------------------------------------

def _waiting(observer, pid):
    count = observer.execute(
        "SELECT count(*) FROM pg_locks WHERE pid = %s AND NOT granted", (pid,)).fetchone()[0]
    observer.commit()
    return count > 0


def test_concurrent_failures_at_threshold_create_single_lock(conn, database_url, clock,
                                                             monkeypatch):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    in_verify, release = threading.Event(), threading.Event()
    real_verify = sessions.verify_password
    paused = {"done": False}
    pids, results, failures = {}, {}, []

    def verify_pausing_first(*args):
        if not paused["done"]:
            paused["done"] = True
            in_verify.set()
            assert release.wait(30)
        return real_verify(*args)

    monkeypatch.setattr(sessions, "verify_password", verify_pausing_first)

    def run(name):
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                pids[name] = c.info.backend_pid
                results[name] = _try(c, clock, WRONG)
        except BaseException as exc:  # noqa: BLE001 - repassado ao teste
            failures.append(exc)
            in_verify.set()

    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert in_verify.wait(10) and not failures
    second = threading.Thread(target=run, args=("second",))
    second.start()
    deadline = time.monotonic() + 10
    while not ("second" in pids and _waiting(conn, pids["second"])):
        assert time.monotonic() < deadline, "segunda tentativa não esperou a trava do usuário"
        time.sleep(0.02)
    release.set()
    first.join(30)
    second.join(30)

    assert not failures, failures
    assert results == {"first": LOGIN_FAILED, "second": LOGIN_FAILED}
    assert len(_lockouts(conn, user_id)) == 1
    assert _attempts(conn, user_id) == Counter(failure=LOCKOUT_THRESHOLD, blocked=1)
    assert len(_events(conn, "auth.lockout")) == 1


def test_many_simultaneous_failures_never_exceed_r4(conn, database_url, clock):
    user_id = _user(conn)
    n = 8
    barrier = threading.Barrier(n)
    failures = []

    def run():
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                barrier.wait(30)
                assert _try(c, clock, WRONG) is LOGIN_FAILED
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    assert not failures, failures
    assert _attempts(conn, user_id) == Counter(failure=LOCKOUT_THRESHOLD,
                                               blocked=n - LOCKOUT_THRESHOLD)
    assert len(_lockouts(conn, user_id)) == 1


# --- desbloqueio pelo administrador (aceite 4) ---------------------------------------------------

def test_admin_unlock_allows_login_and_is_audited(conn, clock):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    clock.advance(minutes=2)

    assert unlock_user(conn, user_id, actor_user_id=admin_id, clock=clock) is True

    [(_, _, unlocked_at, unlocked_by)] = _lockouts(conn, user_id)
    assert (unlocked_at, unlocked_by) == (START + timedelta(minutes=2), admin_id)
    [event] = _events(conn, "auth.unlock")
    assert event == ("user", admin_id, None, user_id, "success", {"unlocked": True})
    clock.advance(seconds=1)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)  # falhas anteriores ao desbloqueio não contam
    assert len(_lockouts(conn, user_id)) == 1
    assert isinstance(_try(conn, clock), LoginSuccess)


@pytest.mark.parametrize("actor", ["operator", "viewer", "inactive_admin"])
def test_unlock_by_non_admin_is_denied_and_audited(conn, clock, actor):
    user_id = _user(conn)
    actor_id = _user(conn, login="ator.exemplo",
                     role="administrator" if actor == "inactive_admin" else actor,
                     active=actor != "inactive_admin")
    _fail(conn, clock, LOCKOUT_THRESHOLD)

    assert unlock_user(conn, user_id, actor_user_id=actor_id, clock=clock) is False

    assert _lockouts(conn, user_id)[0][2] is None
    assert _try(conn, clock) is LOGIN_FAILED
    [event] = _events(conn, "auth.unlock")
    assert event[1] == actor_id and event[4:] == ("denied", {"unlocked": False})


def test_unlock_without_active_lock_returns_false_but_is_audited(conn, clock):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    assert unlock_user(conn, user_id, actor_user_id=admin_id, clock=clock) is False
    [event] = _events(conn, "auth.unlock")
    assert event[4:] == ("success", {"unlocked": False})


def test_unlock_with_unknown_actor_is_rejected(conn, clock):
    import uuid

    user_id = _user(conn)
    with pytest.raises(ValueError, match="ator"):
        unlock_user(conn, user_id, actor_user_id=uuid.uuid4(), clock=clock)


def test_lockout_event_is_audited(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    [event] = _events(conn, "auth.lockout")
    assert event == ("service", None, "authentication", user_id, "success",
                     {"failures": 5, "locked_until": (START + LOCKOUT_DURATION).isoformat()})


# --- login desconhecido e ausência de senha nos registros ----------------------------------------

def test_unknown_login_creates_no_attempt_and_no_lock(conn, clock):
    _user(conn)
    for _ in range(LOCKOUT_THRESHOLD + 2):
        assert _try(conn, clock, login_name="nao.existe") is LOGIN_FAILED
    assert _rows(conn, "SELECT count(*) FROM login_attempts")[0][0] == 0
    assert _rows(conn, "SELECT count(*) FROM login_lockouts")[0][0] == 0


def test_password_typed_as_login_and_password_never_stored(conn, clock):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _try(conn, clock, password=WRONG, login_name=SECRET)  # senha digitada no campo de login
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    _try(conn, clock)  # bloqueado com senha correta
    unlock_user(conn, user_id, actor_user_id=admin_id, clock=clock)
    _try(conn, clock, source_ip="192.0.2.10")

    dump = "\n".join(r[0] for r in _rows(
        conn,
        "SELECT row_to_json(t)::text FROM login_attempts t "
        "UNION ALL SELECT row_to_json(t)::text FROM login_lockouts t "
        "UNION ALL SELECT row_to_json(t)::text FROM audit_events t "
        "UNION ALL SELECT row_to_json(t)::text FROM sessions t",
    ))
    for secret in (SECRET, WRONG):
        assert secret not in dump


# --- IP de origem só armazenado ------------------------------------------------------------------

def test_source_ip_is_stored_and_validated(conn, clock):
    user_id = _user(conn)
    _try(conn, clock, source_ip="2001:db8::1")
    assert _rows(conn, "SELECT host(source_ip) FROM login_attempts WHERE user_id = %s",
                 user_id) == [("2001:db8::1",)]
    with pytest.raises(ValueError) as info:
        _try(conn, clock, source_ip=SECRET)
    assert SECRET not in str(info.value)


def test_ip_does_not_change_lock_rules(conn, clock):
    user_id = _user(conn)
    for i in range(LOCKOUT_THRESHOLD):
        _try(conn, clock, WRONG, source_ip=f"192.0.2.{i + 1}")
    assert len(_lockouts(conn, user_id)) == 1


# --- restrições das tabelas ----------------------------------------------------------------------

LOCKOUT_COLUMNS = "user_id, locked_at, locked_until, trigger_attempt_seq"


@pytest.mark.parametrize(("sql", "error"), [
    ("INSERT INTO login_attempts (user_id, attempted_at, result) VALUES (%(u)s, now(), 'ok')",
     errors.CheckViolation),
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}) VALUES (%(u)s, now(), now(), %(s)s)",
     errors.CheckViolation),
    ("INSERT INTO login_lockouts (user_id, locked_at, locked_until) "
     "VALUES (%(u)s, now(), now() + interval '1 min')", errors.NotNullViolation),
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}) VALUES (%(u)s, now(), now(), 999999999)",
     errors.CheckViolation),
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}, unlocked_at) "
     "VALUES (%(u)s, now(), now() + interval '1 min', %(s)s, now())", errors.CheckViolation),
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}, unlocked_at, unlocked_by) "
     "VALUES (%(u)s, now(), now() + interval '1 min', %(s)s, now(), %(u)s)",
     errors.CheckViolation),  # sem unlocked_after_seq
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}, unlocked_at, unlocked_by, unlocked_after_seq) "
     "VALUES (%(u)s, now(), now() + interval '1 min', %(s)s, now() - interval '1 min', %(u)s, %(s)s)",
     errors.CheckViolation),
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}, unlocked_at, unlocked_by, unlocked_after_seq) "
     "VALUES (%(u)s, now(), now() + interval '1 min', %(s)s, now(), %(u)s, %(s)s - 1)",
     errors.CheckViolation),
    (f"INSERT INTO login_lockouts ({LOCKOUT_COLUMNS}) "
     "VALUES (%(u)s, now(), now() + interval '1 min', 999999999)", errors.ForeignKeyViolation),
])
def test_table_constraints(conn, sql, error):
    user_id = _user(conn)
    seq = conn.execute(
        "INSERT INTO login_attempts (user_id, attempted_at, result) VALUES (%s, now(), 'failure') "
        "RETURNING seq", (user_id,),
    ).fetchone()[0]
    with pytest.raises(error):
        conn.execute(sql, {"u": user_id, "s": seq})


def test_attempt_seq_is_generated_and_not_writable(conn):
    user_id = _user(conn)
    with pytest.raises(errors.GeneratedAlways):
        conn.execute(
            "INSERT INTO login_attempts (seq, user_id, attempted_at, result) "
            "VALUES (1, %s, now(), 'failure')", (user_id,),
        )


def test_attempts_block_user_deletion(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, 1)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


# --- ordem transacional por sequência, não por horário (relógio fixo) ----------------------------

def test_failures_after_success_at_same_instant_reach_r4(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    assert isinstance(_try(conn, clock), LoginSuccess)
    _fail(conn, clock, LOCKOUT_THRESHOLD)  # mesmo instante do sucesso, mas depois dele
    assert len(_lockouts(conn, user_id)) == 1
    assert _try(conn, clock) is LOGIN_FAILED


def test_failures_after_unlock_at_same_instant_reach_r4(conn, clock):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    assert unlock_user(conn, user_id, actor_user_id=admin_id, clock=clock) is True
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    assert len(_lockouts(conn, user_id)) == 1  # falhas anteriores ao desbloqueio não contam
    _fail(conn, clock, 1)
    assert len(_lockouts(conn, user_id)) == 2
    assert _try(conn, clock) is LOGIN_FAILED


def test_failures_after_expired_lock_at_same_instant_reach_r4(conn, clock):
    user_id = _user(conn)
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    clock.now = START + LOCKOUT_DURATION  # bloqueio acabou de expirar
    _fail(conn, clock, LOCKOUT_THRESHOLD - 1)
    assert len(_lockouts(conn, user_id)) == 1
    _fail(conn, clock, 1)
    assert len(_lockouts(conn, user_id)) == 2


# --- desbloqueio × mudança concorrente do ator ---------------------------------------------------

ACTOR_CHANGES = {
    "deactivated": "UPDATE users SET active = false WHERE id = %s",
    "demoted": "UPDATE users SET role = 'operator' WHERE id = %s",
}


@pytest.mark.parametrize("change", ACTOR_CHANGES, ids=ACTOR_CHANGES.keys())
def test_actor_change_committed_while_unlock_waits_denies_unlock(conn, database_url, clock,
                                                                 change):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    outcome, failures, ready = {}, [], threading.Event()

    with connect_checked(database_url) as changer:
        changer.rollback()
        changer.execute(ACTOR_CHANGES[change], (admin_id,))  # linha do ator travada

        def run_unlock():
            try:
                with connect_checked(database_url) as c:
                    c.rollback()
                    outcome["pid"] = c.info.backend_pid
                    ready.set()
                    outcome["result"] = unlock_user(c, user_id, actor_user_id=admin_id,
                                                    clock=clock)
            except BaseException as exc:  # noqa: BLE001 - repassado ao teste
                failures.append(exc)
                ready.set()

        thread = threading.Thread(target=run_unlock)
        thread.start()
        assert ready.wait(10)
        deadline, waited = time.monotonic() + 5, False
        while time.monotonic() < deadline and not waited:
            waited = "pid" in outcome and _waiting(conn, outcome["pid"])
            time.sleep(0.02)
        changer.commit()
    thread.join(30)

    assert not failures, failures
    assert outcome["result"] is False
    assert _lockouts(conn, user_id)[0][2] is None  # continua bloqueado
    [event] = _events(conn, "auth.unlock")
    assert (event[1], event[4], event[5]) == (admin_id, "denied", {"unlocked": False})
    assert _try(conn, clock) is LOGIN_FAILED
    assert waited, "desbloqueio não esperou a mudança do ator"


def _pause_after_user_locks(monkeypatch, first_only=True):
    """Pausa unlock_user logo após travar ator e alvo (gancho só de teste)."""
    import app.auth.lockout as lockout_module

    locked, release, state = threading.Event(), threading.Event(), {"paused": False}
    real = lockout_module._lock_users

    def wrapper(*args, **kwargs):
        rows = real(*args, **kwargs)
        if not (first_only and state["paused"]):
            state["paused"] = True
            locked.set()
            assert release.wait(30)
        return rows

    monkeypatch.setattr(lockout_module, "_lock_users", wrapper)
    return locked, release


@pytest.mark.parametrize("change", ACTOR_CHANGES, ids=ACTOR_CHANGES.keys())
def test_actor_change_started_during_unlock_waits_for_unlock(conn, database_url, clock,
                                                             monkeypatch, change):
    user_id = _user(conn)
    admin_id = _user(conn, login="admin.exemplo", role="administrator")
    _fail(conn, clock, LOCKOUT_THRESHOLD)
    locked, release = _pause_after_user_locks(monkeypatch)
    order, failures, outcome = [], [], {}

    def run_unlock():
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                outcome["result"] = unlock_user(c, user_id, actor_user_id=admin_id, clock=clock)
                order.append("unlock_committed")
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)
            locked.set()

    def run_change():
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                outcome["changer_pid"] = c.info.backend_pid
                c.execute(ACTOR_CHANGES[change], (admin_id,))
                c.commit()
                order.append("change_committed")
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    unlock_thread = threading.Thread(target=run_unlock)
    unlock_thread.start()
    assert locked.wait(10) and not failures, failures
    change_thread = threading.Thread(target=run_change)
    change_thread.start()
    deadline, blocked = time.monotonic() + 5, False
    while time.monotonic() < deadline and not blocked:
        blocked = "changer_pid" in outcome and _waiting(conn, outcome["changer_pid"])
        time.sleep(0.02)
    release.set()
    unlock_thread.join(30)
    change_thread.join(30)

    assert not failures, failures
    assert outcome["result"] is True
    assert order == ["unlock_committed", "change_committed"]
    assert blocked, "mudança do ator não esperou o desbloqueio"
    [event] = _events(conn, "auth.unlock")
    assert (event[1], event[4]) == (admin_id, "success")


def test_crossed_unlocks_do_not_deadlock(conn, database_url, clock, monkeypatch):
    admin_a = _user(conn, login="admin.a", role="administrator")
    admin_b = _user(conn, login="admin.b", role="administrator")
    locked, release = _pause_after_user_locks(monkeypatch)
    results, failures, pids = {}, [], {}

    def run(name, target, actor):
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                pids[name] = c.info.backend_pid
                results[name] = unlock_user(c, target, actor_user_id=actor, clock=clock)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)
            locked.set()

    first = threading.Thread(target=run, args=("first", admin_b, admin_a))
    first.start()
    assert locked.wait(10) and not failures, failures
    second = threading.Thread(target=run, args=("second", admin_a, admin_b))
    second.start()
    deadline, waited = time.monotonic() + 5, False
    while time.monotonic() < deadline and not waited:
        waited = "second" in pids and _waiting(conn, pids["second"])
        time.sleep(0.02)
    release.set()
    first.join(30)
    second.join(30)

    assert not failures, failures  # nenhum DeadlockDetected
    assert results == {"first": False, "second": False}  # ninguém estava bloqueado
    assert len(_events(conn, "auth.unlock")) == 2
    assert waited, "segundo desbloqueio não esperou as travas na mesma ordem"
