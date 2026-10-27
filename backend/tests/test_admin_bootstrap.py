"""S0-06: bootstrap do primeiro administrador e audit_events. Dados e senhas fictícios."""
import inspect
import logging
import os
import pty
import select
import subprocess
import sys
import threading
import time
import traceback

import pytest
from psycopg import IsolationLevel, errors

import app.admin as admin
from app import db_locks
from app.admin import BootstrapError, bootstrap_first_admin
from app.auth.passwords import HashParameters, verify_password
from conftest import BACKEND_DIR
from db_guard import connect_checked

FAST = HashParameters(time_cost=1, memory_cost_kib=1024, parallelism=1)
SECRET = "senha-ficticia-bootstrap-2026"


def _bootstrap(conn, login="admin.exemplo", password=SECRET, **kwargs):
    return bootstrap_first_admin(
        conn, name="Administrador Exemplo", login=login, password=password, params=FAST, **kwargs
    )


def _events(conn):
    return conn.execute(
        "SELECT actor_type, actor_user_id, actor_service, action, target_type, target_id, "
        "result, details, occurred_at FROM audit_events ORDER BY occurred_at, id"
    ).fetchall()


def _admins(conn):
    return conn.execute(
        "SELECT id, login, role, active, created_by, password_hash FROM users "
        "WHERE role = 'administrator'"
    ).fetchall()


def _all_text(conn) -> str:
    users = conn.execute("SELECT row_to_json(u)::text FROM users u").fetchall()
    events = conn.execute("SELECT row_to_json(e)::text FROM audit_events e").fetchall()
    return "\n".join(r[0] for r in users + events)


# --- criação e recusa ----------------------------------------------------------------------------

def test_creates_first_admin(conn):
    result = _bootstrap(conn)

    assert result.created
    [(user_id, login, role, active, created_by, password_hash)] = _admins(conn)
    assert (user_id, login, role, active, created_by) == (
        result.user_id, "admin.exemplo", "administrator", True, None)
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, SECRET)


def test_creation_event_has_actor_action_target_result_and_date(conn):
    result = _bootstrap(conn)

    [(actor_type, actor_user, actor_service, action, target_type, target_id, outcome, details,
      occurred_at)] = _events(conn)
    assert (actor_type, actor_user, actor_service) == ("service", None, "bootstrap")
    assert (action, target_type, target_id, outcome) == (
        "user.bootstrap_first_admin", "user", result.user_id, "success")
    assert details == {"login": "admin.exemplo"}
    assert occurred_at is not None
    assert result.event_id is not None


@pytest.mark.parametrize("active", [True, False])
def test_refuses_when_admin_exists_and_does_not_change_users(conn, active):
    _bootstrap(conn)
    conn.execute("UPDATE users SET active = %s", (active,))
    conn.commit()
    before = conn.execute("SELECT row_to_json(u)::text FROM users u ORDER BY id").fetchall()
    conn.commit()

    result = _bootstrap(conn, login="outro.admin")

    assert not result.created and result.user_id is None
    assert conn.execute("SELECT row_to_json(u)::text FROM users u ORDER BY id").fetchall() == before
    last = _events(conn)[-1]
    assert (last[3], last[6], last[7]) == (
        "user.bootstrap_first_admin", "denied", {"reason": "administrator_exists"})
    assert (last[4], last[5]) == (None, None)


def test_non_admin_users_do_not_block_bootstrap(conn):
    conn.execute(
        "INSERT INTO users (name, login, password_hash, role) VALUES ('Op', 'op', 'h', 'operator')"
    )
    conn.commit()
    assert _bootstrap(conn).created


@pytest.mark.parametrize("password", ["curta", " " * 20, "x" * 129])
def test_policy_rejection_writes_nothing(conn, password):
    with pytest.raises(BootstrapError) as info:
        _bootstrap(conn, password=password)
    assert password not in str(info.value)
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0


@pytest.mark.parametrize("login", ["joão", "com espaco", ""])
def test_invalid_login_is_audited_as_failure(conn, login):
    with pytest.raises(BootstrapError):
        _bootstrap(conn, login=login)
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
    [event] = _events(conn)
    assert (event[6], event[7]) == ("failure", {"reason": "invalid_name_or_login"})


def test_requires_idle_non_autocommit_connection(conn, database_url):
    conn.execute("SELECT 1")  # transação aberta
    with pytest.raises(ValueError, match="sem transação aberta"):
        _bootstrap(conn)
    conn.rollback()
    with connect_checked(database_url, autocommit=True) as auto:
        with pytest.raises(ValueError, match="autocommit"):
            _bootstrap(auto)


# --- concorrência (T9) ---------------------------------------------------------------------------

def _waiting_on_bootstrap_lock(conn, pid) -> bool:
    key = db_locks.FIRST_ADMIN_BOOTSTRAP
    waiting = conn.execute(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = %s AND NOT granted "
        "AND classid = %s AND objid = %s AND objsubid = 1",
        (pid, key >> 32, key & 0xFFFFFFFF),
    ).fetchone()[0]
    conn.commit()
    return waiting == 1


def test_second_bootstrap_waits_for_lock_and_is_refused(conn, database_url):
    locked, release, second_ready = threading.Event(), threading.Event(), threading.Event()
    results, failures, pids = {}, [], {}

    def hold_lock():
        locked.set()
        assert release.wait(30), "liberação não ocorreu"

    def run(name, login, **kwargs):
        try:
            with connect_checked(database_url) as c:
                c.rollback()  # connect_checked consulta o servidor; bootstrap exige conexão ociosa
                pids[name] = c.info.backend_pid
                if name == "second":
                    second_ready.set()
                results[name] = _bootstrap(c, login=login, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - repassado ao teste
            failures.append(exc)
            locked.set()

    first = threading.Thread(target=run, args=("first", "admin.a"), kwargs={"on_locked": hold_lock})
    first.start()
    assert locked.wait(30) and not failures
    second = threading.Thread(target=run, args=("second", "admin.b"))
    second.start()
    assert second_ready.wait(30)

    deadline = time.monotonic() + 30
    while not _waiting_on_bootstrap_lock(conn, pids["second"]):
        assert time.monotonic() < deadline, "segunda execução não ficou esperando o lock"
        time.sleep(0.05)
    assert second.is_alive() and "second" not in results

    release.set()
    first.join(30)
    second.join(30)
    assert not failures, failures
    assert results["first"].created and not results["second"].created

    assert [a[1] for a in _admins(conn)] == ["admin.a"]
    outcomes = [e[6] for e in _events(conn)]
    assert sorted(outcomes) == ["denied", "success"]


ISOLATION_SETUPS = {
    # Padrão do servidor/sessão alterado (default_transaction_isolation).
    "session_default_repeatable_read": lambda c: c.execute(
        "SET default_transaction_isolation = 'repeatable read'"),
    "session_default_serializable": lambda c: c.execute(
        "SET default_transaction_isolation = 'serializable'"),
    # Isolamento configurado no próprio psycopg (BEGIN ISOLATION LEVEL ...).
    "psycopg_repeatable_read": lambda c: setattr(c, "isolation_level", IsolationLevel.REPEATABLE_READ),
}


@pytest.mark.parametrize("setup", ISOLATION_SETUPS.values(), ids=ISOLATION_SETUPS.keys())
def test_waiting_bootstrap_under_stricter_isolation_does_not_create_second_admin(
    conn, database_url, setup
):
    locked, release, second_ready = threading.Event(), threading.Event(), threading.Event()
    results, failures, pids, isolation_seen = {}, [], {}, {}

    def run(name, login, hold):
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                setup(c)
                c.commit()
                pids[name] = c.info.backend_pid

                def on_locked():
                    isolation_seen[name] = c.execute("SHOW transaction_isolation").fetchone()[0]
                    if hold:
                        locked.set()
                        assert release.wait(30), "liberação não ocorreu"

                if name == "second":
                    second_ready.set()
                results[name] = _bootstrap(c, login=login, on_locked=on_locked)
        except BaseException as exc:  # noqa: BLE001 - repassado ao teste
            failures.append(exc)
            locked.set()

    first = threading.Thread(target=run, args=("first", "admin.a", True))
    first.start()
    assert locked.wait(30) and not failures, failures
    second = threading.Thread(target=run, args=("second", "admin.b", False))
    second.start()
    assert second_ready.wait(30)

    deadline = time.monotonic() + 30
    while not _waiting_on_bootstrap_lock(conn, pids["second"]):
        assert time.monotonic() < deadline, "segunda execução não ficou esperando o lock"
        time.sleep(0.05)

    release.set()
    first.join(30)
    second.join(30)
    assert not failures, failures

    assert [a[1] for a in _admins(conn)] == ["admin.a"]
    assert sorted(e[6] for e in _events(conn)) == ["denied", "success"]
    assert results["first"].created and not results["second"].created
    assert isolation_seen == {"first": "read committed", "second": "read committed"}


def test_many_simultaneous_bootstraps_create_exactly_one_admin(conn, database_url):
    n = 6
    barrier = threading.Barrier(n)
    results, failures = [], []

    def run(i):
        try:
            with connect_checked(database_url) as c:
                c.rollback()
                barrier.wait(30)
                results.append(_bootstrap(c, login=f"admin.{i}"))
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    assert not failures, failures
    assert sum(r.created for r in results) == 1
    assert len(_admins(conn)) == 1
    outcomes = [e[6] for e in _events(conn)]
    assert outcomes.count("success") == 1 and outcomes.count("denied") == n - 1


def test_lock_key_comes_from_central_registry():
    keys = list(db_locks.ALL_KEYS.values())
    assert len(keys) == len(set(keys))
    assert all(-(2**63) <= k < 2**63 for k in keys)
    source = inspect.getsource(admin)
    assert "pg_advisory_xact_lock(%s)" in source
    assert "FIRST_ADMIN_BOOTSTRAP" in source
    assert admin.FIRST_ADMIN_BOOTSTRAP == db_locks.FIRST_ADMIN_BOOTSTRAP


# --- audit_events somente inserção ---------------------------------------------------------------

@pytest.mark.parametrize("statement", [
    "UPDATE audit_events SET result = 'failure'",
    "DELETE FROM audit_events",
])
def test_audit_events_are_append_only(conn, statement):
    _bootstrap(conn)
    with pytest.raises(errors.InsufficientPrivilege, match="somente inserção"):
        conn.execute(statement)


@pytest.mark.parametrize(
    ("columns", "values"),
    [
        ("actor_type, action, result", "'user', 'a.b', 'success'"),            # usuário sem id
        ("actor_type, action, result", "'service', 'a.b', 'success'"),         # serviço sem nome
        ("actor_type, actor_service, action, result", "'robot', 's', 'a.b', 'success'"),
        ("actor_type, actor_service, action, result", "'service', 's', 'semponto', 'success'"),
        ("actor_type, actor_service, action, result", "'service', 's', 'a.b', 'ok'"),
        ("actor_type, actor_service, action, result, details", "'service', 's', 'a.b', 'success', '[]'"),
        ("actor_type, actor_service, action, result, target_id",
         "'service', 's', 'a.b', 'success', gen_random_uuid()"),                # alvo sem tipo
    ],
)
def test_audit_event_constraints(conn, columns, values):
    with pytest.raises(errors.CheckViolation):
        conn.execute(f"INSERT INTO audit_events ({columns}) VALUES ({values})")


def test_audit_actor_user_must_exist(conn):
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO audit_events (actor_type, actor_user_id, action, result) "
            "VALUES ('user', gen_random_uuid(), 'a.b', 'success')"
        )


# --- senha: terminal apenas; nunca em argumento, ambiente, log, evento ou exceção ---------------

def test_password_not_in_database_logs_or_exceptions(conn, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(BootstrapError) as info:
        _bootstrap(conn, login="joão")  # falha auditada
    _bootstrap(conn)  # sucesso
    _bootstrap(conn, login="segundo")  # recusa
    assert sorted(e[6] for e in _events(conn)) == ["denied", "failure", "success"]
    assert SECRET not in _all_text(conn).replace(_admins(conn)[0][5], "")
    assert SECRET not in caplog.text
    assert SECRET not in "".join(traceback.format_exception(info.value))


def test_cli_has_no_password_option():
    with pytest.raises(SystemExit) as info:
        admin.main(["create-first-admin", "--name", "A", "--login", "a", "--password", SECRET])
    assert info.value.code == 2


def test_password_source_is_only_the_terminal():
    source = inspect.getsource(admin)
    assert "environ" not in source and "getenv" not in source
    assert "getpass" in source


def test_non_terminal_stdin_is_refused(conn, database_url):
    env = {**os.environ, "DATABASE_URL": database_url, "PASSWORD": SECRET, "ADMIN_PASSWORD": SECRET}
    result = subprocess.run(
        [sys.executable, "-m", "app.admin", "create-first-admin", "--name", "A", "--login", "a"],
        cwd=BACKEND_DIR, env=env, input=f"{SECRET}\n{SECRET}\n", capture_output=True, text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "terminal interativo" in result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def _read_until(fd, marker: bytes, timeout=30) -> bytes:
    data, deadline = b"", time.monotonic() + timeout
    while marker not in data:
        assert time.monotonic() < deadline, data
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            data += chunk
    return data


def test_cli_reads_password_from_terminal(conn, database_url):
    master, slave = pty.openpty()
    env = {**os.environ, "DATABASE_URL": database_url}
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.admin", "create-first-admin", "--name", "Admin CLI",
         "--login", "admin.cli"],
        cwd=BACKEND_DIR, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
    )
    os.close(slave)
    try:
        transcript = _read_until(master, b"Senha do primeiro administrador: ")
        os.write(master, SECRET.encode() + b"\n")
        transcript += _read_until(master, b"Confirme a senha: ")
        os.write(master, SECRET.encode() + b"\n")
        transcript += _read_until(master, b"criado")
        assert proc.wait(60) == 0
        transcript += _read_until(master, b"\n", timeout=5)
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()

    assert SECRET.encode() not in transcript  # eco desligado pelo getpass
    [(_, login, _, _, created_by, password_hash)] = _admins(conn)
    assert (login, created_by) == ("admin.cli", None)
    assert password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")  # produção no CLI
    assert verify_password(password_hash, SECRET)
