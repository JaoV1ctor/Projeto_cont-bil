from uuid import uuid4

import pytest
from psycopg import errors

from helpers import MTIME, finish_run, make_source, start_run


def _insert_document(conn, source_id, relative_path, path_key=None):
    conn.execute(
        "INSERT INTO documents (source_id, relative_path, path_key, name, size_bytes, source_modified_at) "
        "VALUES (%s, %s, %s, %s, 1, %s)",
        (source_id, relative_path, path_key or relative_path, relative_path.rsplit("/", 1)[-1], MTIME),
    )


def test_document_requires_existing_source(conn):
    with pytest.raises(errors.ForeignKeyViolation):
        _insert_document(conn, uuid4(), "a.pdf")


def test_run_requires_existing_source(conn):
    with pytest.raises(errors.ForeignKeyViolation):
        start_run(conn, uuid4())


def test_source_with_documents_cannot_be_deleted(conn):
    source = make_source(conn)
    _insert_document(conn, source, "a.pdf")
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("DELETE FROM document_sources WHERE id = %s", (source,))


def test_run_referenced_by_document_cannot_be_deleted(conn):
    source = make_source(conn)
    run = start_run(conn, source)
    _insert_document(conn, source, "a.pdf")
    conn.execute("UPDATE documents SET last_seen_run_id = %s", (run,))
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("DELETE FROM index_runs WHERE id = %s", (run,))


def test_path_key_unique_per_source(conn):
    source = make_source(conn)
    _insert_document(conn, source, "Plano de Trabalho.pdf")
    with pytest.raises(errors.UniqueViolation):
        _insert_document(conn, source, "Plano de Trabalho.pdf")


def test_same_path_allowed_in_different_sources(conn):
    _insert_document(conn, make_source(conn, "Fonte A"), "Plano de Trabalho.pdf")
    _insert_document(conn, make_source(conn, "Fonte B"), "Plano de Trabalho.pdf")
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 2


def test_same_name_in_different_folders_allowed(conn):
    source = make_source(conn)
    _insert_document(conn, source, "A/Plano de Trabalho.pdf")
    _insert_document(conn, source, "B/Plano de Trabalho.pdf")
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 2


UNSAFE_PATHS = [
    # vazio e POSIX
    "", "/etc/passwd", "../fora.pdf", "a/../../b.pdf", "a/..", "./a.pdf", "a//b.pdf", "a/",
    # Windows: unidade, raiz, UNC, dispositivo, separador '\'
    "C:\\Windows\\win.ini", "C:/Windows/win.ini", "c:relativo.pdf", "\\raiz.pdf",
    "\\\\servidor\\compartilhamento\\a.pdf", "//servidor/compartilhamento/a.pdf",
    "\\\\?\\C:\\a.pdf", "..\\fora.pdf", "a\\..\\..\\b.pdf", "a/..\\b.pdf",
    # segmentos que o Win32 reduz a '..'
    "a/.../b.pdf", "a/.. /b.pdf", "a\\. \\b.pdf",
]


@pytest.mark.parametrize("bad_path", UNSAFE_PATHS)
def test_unsafe_relative_path_rejected(conn, bad_path):
    source = make_source(conn)
    with pytest.raises(errors.CheckViolation):
        _insert_document(conn, source, bad_path, path_key="k")


@pytest.mark.parametrize(
    "path",
    [
        "nome.com.varios.pontos.pdf",
        "..oculto/arquivo..pdf",
        ".arquivo-oculto",
        "Nomes especiais/Ofício nº 15 & anexos (cópia) #2 – 50% [rev] + extra, final!.pdf",
        "ASSOCIAÇÕES/Associação Exemplo Aurora/2023/Emenda 2023-0007/Plano de Trabalho.pdf",
    ],
)
def test_safe_relative_paths_allowed(conn, path):
    _insert_document(conn, make_source(conn), path)


def test_last_seen_run_must_belong_to_document_source(conn):
    source_a = make_source(conn, "Fonte A")
    run_b = start_run(conn, make_source(conn, "Fonte B"))
    _insert_document(conn, source_a, "a.pdf")
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("UPDATE documents SET last_seen_run_id = %s", (run_b,))


def test_last_seen_run_from_same_source_allowed(conn):
    source = make_source(conn)
    run = start_run(conn, source)
    _insert_document(conn, source, "a.pdf")
    conn.execute("UPDATE documents SET last_seen_run_id = %s", (run,))


def test_only_one_running_run_per_source(conn):
    source = make_source(conn)
    start_run(conn, source)
    with pytest.raises(errors.UniqueViolation):
        start_run(conn, source)


def test_new_run_allowed_after_previous_finished(conn):
    source = make_source(conn)
    finish_run(conn, start_run(conn, source))
    start_run(conn, source)


def test_completed_run_cannot_have_errors(conn):
    run = start_run(conn, make_source(conn))
    conn.execute("UPDATE index_runs SET error_count = 1 WHERE id = %s", (run,))
    with pytest.raises(errors.CheckViolation):
        finish_run(conn, run, "completed")


def test_completed_with_errors_allowed(conn):
    run = start_run(conn, make_source(conn))
    conn.execute("UPDATE index_runs SET error_count = 1 WHERE id = %s", (run,))
    finish_run(conn, run, "completed_with_errors")


def test_finished_run_requires_finished_at(conn):
    run = start_run(conn, make_source(conn))
    with pytest.raises(errors.CheckViolation):
        conn.execute("UPDATE index_runs SET status = 'failed' WHERE id = %s", (run,))


def test_unknown_normalization_policy_rejected(conn):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO document_sources (name, root_path, normalization_policy) "
            "VALUES ('x', '/lab', 'casefold')"
        )


def test_extension_must_be_lowercase(conn):
    source = make_source(conn)
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO documents (source_id, relative_path, path_key, name, extension, size_bytes, "
            "source_modified_at) VALUES (%s, 'a.PDF', 'a.PDF', 'a.PDF', 'PDF', 1, %s)",
            (source, MTIME),
        )


def test_primary_keys_are_uuid(conn):
    rows = conn.execute(
        "SELECT table_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'id'"
    ).fetchall()
    tables = ("document_sources", "index_runs", "documents", "index_errors",
              "users", "associations", "user_associations", "audit_events",
              "sessions", "login_attempts", "login_lockouts")
    assert dict(rows) == {t: "uuid" for t in tables}
