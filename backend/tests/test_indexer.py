"""Indexador sobre cópia temporária da amostra sintética (SPEC §§5, 7.2, 7.3).

A amostra original só é lida; casos com mutação usam cópia em tmp_path.
"""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import app.indexer as indexer
from app.indexer import IndexerBusy, run_index
from conftest import BACKEND_DIR

FIXTURES = BACKEND_DIR.parent / "tests" / "fixtures"
SAMPLE_ROOT = FIXTURES / "servidor-teste"
SAMPLE_FILES = sum(1 for _ in open(FIXTURES / "servidor-teste.sha256", encoding="utf-8"))
DEEP = "_ANTIGO - NÃO USAR/2019/a/b/c/d/e/f/g/h/arquivo-profundo.txt"
PIX = "ASSOC GRUPO EXEMPLO SAO JOAO/comprovante pix 05-03-2024.png"
IPE = "ASSOCIAÇÕES/Instituto Exemplo Ipê"


@pytest.fixture
def root(tmp_path) -> Path:
    copy = tmp_path / "servidor-teste"
    shutil.copytree(SAMPLE_ROOT, copy, symlinks=True)
    return copy


def _source(conn, root: Path, name: str = "Laboratório") -> object:
    source = conn.execute(
        "INSERT INTO document_sources (name, root_path, normalization_policy) "
        "VALUES (%s, %s, 'exact') RETURNING id",
        (name, str(root)),
    ).fetchone()[0]
    conn.commit()
    return source


def _index(conn, source, root: Path, **kwargs):
    return run_index(conn, source, allowed_roots=[str(root.parent)], **kwargs)


def _docs(conn) -> dict[str, tuple]:
    rows = conn.execute(
        "SELECT relative_path, availability, size_bytes, first_seen_at FROM documents"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def _errors(conn, run_id) -> list[tuple]:
    rows = conn.execute(
        "SELECT relative_path, code FROM index_errors WHERE run_id = %s", (run_id,)
    ).fetchall()
    return sorted(rows, key=lambda r: r[0] or "")


def _snapshot(root: Path) -> dict[str, tuple]:
    """Estado observável da árvore: tipo/permissão, tamanho, mtime e SHA-256 (leitura do teste)."""
    def entry(path: Path):
        st = os.lstat(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(st.st_mode) else None
        return (st.st_mode, st.st_size, st.st_mtime_ns, digest)

    result = {".": entry(root)}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            result[str(path.relative_to(root))] = entry(path)
    return result


def _touch_later(path: Path, data: bytes) -> None:
    st = path.stat()
    path.write_bytes(data)
    later = st.st_mtime_ns + int(timedelta(hours=1).total_seconds() * 1e9)
    os.utime(path, ns=(st.st_atime_ns, later))


# --- primeira varredura e reexecução -------------------------------------------------------------

def test_first_scan_records_metadata_of_every_file(conn, root):
    source = _source(conn, root)
    summary = _index(conn, source, root)

    assert summary.status == "completed"
    c = summary.counts
    assert (c.found, c.new, c.updated, c.not_found, c.ignored, c.errors) == (
        SAMPLE_FILES, SAMPLE_FILES, 0, 0, 0, 0)
    assert len(_docs(conn)) == SAMPLE_FILES

    st = (root / PIX).stat()
    row = conn.execute(
        "SELECT name, extension, size_bytes, source_modified_at, last_seen_run_id FROM documents "
        "WHERE relative_path = %s", (PIX,),
    ).fetchone()
    assert row[:3] == ("comprovante pix 05-03-2024.png", "png", st.st_size)
    assert int(row[3].timestamp() * 1_000_000) == st.st_mtime_ns // 1000
    assert row[4] == summary.run_id
    assert DEEP in _docs(conn)

    run = conn.execute(
        "SELECT status, finished_at IS NOT NULL, found_count, new_count, error_count "
        "FROM index_runs WHERE id = %s", (summary.run_id,),
    ).fetchone()
    assert run == ("completed", True, SAMPLE_FILES, SAMPLE_FILES, 0)
    source_row = conn.execute(
        "SELECT status, last_complete_run_at IS NOT NULL FROM document_sources WHERE id = %s",
        (source,),
    ).fetchone()
    assert source_row == ("available", True)


def test_rerun_without_changes_does_not_duplicate(conn, root):
    source = _source(conn, root)
    _index(conn, source, root)
    before = _docs(conn)

    summary = _index(conn, source, root, batch_size=7)

    assert summary.status == "completed"
    c = summary.counts
    assert (c.found, c.new, c.updated, c.not_found) == (SAMPLE_FILES, 0, 0, 0)
    assert _docs(conn) == before


def test_new_and_changed_files(conn, root):
    source = _source(conn, root)
    _index(conn, source, root)
    (root / "Digitalizados" / "SCAN0003.pdf").write_bytes(b"novo")
    _touch_later(root / PIX, b"alterado")

    summary = _index(conn, source, root)

    c = summary.counts
    assert (c.found, c.new, c.updated, c.not_found) == (SAMPLE_FILES + 1, 1, 1, 0)
    docs = _docs(conn)
    assert docs["Digitalizados/SCAN0003.pdf"][:2] == ("available", 4)
    assert docs[PIX][1] == len(b"alterado")
    assert len(docs) == SAMPLE_FILES + 1


def test_removed_file_marked_not_found_after_complete_scan_and_restored(conn, root):
    source = _source(conn, root)
    _index(conn, source, root)
    content = (root / DEEP).read_bytes()
    (root / DEEP).unlink()

    summary = _index(conn, source, root)
    assert (summary.status, summary.counts.not_found) == ("completed", 1)
    assert _docs(conn)[DEEP][0] == "not_found"
    assert len(_docs(conn)) == SAMPLE_FILES  # registro preservado

    (root / DEEP).write_bytes(content)
    _index(conn, source, root)
    assert _docs(conn)[DEEP][0] == "available"


# --- links, arquivos especiais e nomes recusados ------------------------------------------------

def test_links_are_refused_and_not_followed(conn, root, tmp_path):
    outside = tmp_path / "fora"
    outside.mkdir()
    (outside / "segredo.txt").write_text("fora da raiz")
    links = root / "Links"
    links.mkdir()
    (links / "arquivo-fora").symlink_to(outside / "segredo.txt")
    (links / "pasta-fora").symlink_to(outside, target_is_directory=True)
    (links / "pasta-dentro").symlink_to(root / "Digitalizados", target_is_directory=True)
    (links / "quebrado").symlink_to(tmp_path / "nao-existe")
    os.mkfifo(links / "fila")

    source = _source(conn, root)
    summary = _index(conn, source, root)

    assert summary.status == "completed"
    assert (summary.counts.found, summary.counts.ignored, summary.counts.errors) == (
        SAMPLE_FILES, 5, 0)
    assert not [p for p in _docs(conn) if p.startswith("Links/")]
    assert (outside / "segredo.txt").read_text() == "fora da raiz"


def test_root_that_is_a_link_is_refused(conn, root, tmp_path):
    link = tmp_path / "raiz-link"
    link.symlink_to(root, target_is_directory=True)
    source = _source(conn, link)

    summary = _index(conn, source, link)

    assert summary.status == "failed"
    assert _errors(conn, summary.run_id) == [(None, "source_unavailable")]
    assert _docs(conn) == {}


def test_names_rejected_by_catalog_become_errors(conn, root):
    (root / "Nomes especiais" / "...").write_bytes(b"x")  # o Win32 reduziria a '..'
    (root / "Nomes especiais").joinpath(os.fsdecode(b"latin1-\xe9.txt")).write_bytes(b"x")
    source = _source(conn, root)

    summary = _index(conn, source, root)

    assert summary.status == "completed_with_errors"
    assert summary.counts.errors == 2
    assert len(_docs(conn)) == SAMPLE_FILES
    assert _errors(conn, summary.run_id) == [
        ("Nomes especiais/...", "invalid_name"),
        ("Nomes especiais/latin1-\\udce9.txt", "invalid_name"),
    ]


# --- acesso negado, falha, cancelamento e interrupção -------------------------------------------

@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissões de diretório")
def test_access_denied_is_error_and_preserves_availability(conn, root):
    source = _source(conn, root)
    _index(conn, source, root)
    (root / DEEP).unlink()  # remoção real que não pode ser marcada nesta execução parcial
    denied = root / IPE
    denied.chmod(0)
    try:
        summary = _index(conn, source, root)
    finally:
        denied.chmod(0o755)

    assert summary.status == "completed_with_errors"
    assert summary.counts.not_found == 0
    assert _errors(conn, summary.run_id) == [(IPE, "permission_denied")]
    assert {v[0] for v in _docs(conn).values()} == {"available"}
    run = conn.execute("SELECT error_count FROM index_runs WHERE id = %s", (summary.run_id,))
    assert run.fetchone()[0] == 1


def test_unavailable_source_fails_without_marking(conn, root):
    source = _source(conn, root)
    _index(conn, source, root)
    shutil.rmtree(root)

    summary = _index(conn, source, root)

    assert summary.status == "failed"
    assert summary.interruption_reason == "fonte indisponível"
    assert _errors(conn, summary.run_id) == [(None, "source_unavailable")]
    assert {v[0] for v in _docs(conn).values()} == {"available"}
    status = conn.execute("SELECT status FROM document_sources WHERE id = %s", (source,))
    assert status.fetchone()[0] == "unavailable"


def test_cancel_preserves_availability_and_keeps_committed_progress(conn, root):
    source = _source(conn, root)
    _index(conn, source, root)
    (root / DEEP).unlink()
    calls = iter(range(10**6))

    summary = _index(conn, source, root, batch_size=5, should_cancel=lambda: next(calls) >= 12)

    assert (summary.status, summary.interruption_reason) == ("cancelled", "cancelamento solicitado")
    assert summary.counts.found == 12
    assert summary.counts.not_found == 0
    assert {v[0] for v in _docs(conn).values()} == {"available"}
    seen = conn.execute(
        "SELECT count(*) FROM documents WHERE last_seen_run_id = %s", (summary.run_id,)
    ).fetchone()[0]
    assert seen == 12
    run = conn.execute(
        "SELECT status, last_position IS NOT NULL, found_count FROM index_runs WHERE id = %s",
        (summary.run_id,),
    ).fetchone()
    assert run == ("cancelled", True, 12)


@pytest.mark.parametrize(
    ("exc", "status", "reason"),
    [(RuntimeError("queda"), "failed", "falha: RuntimeError"),
     (KeyboardInterrupt(), "cancelled", "interrompido")],
)
def test_interruption_mid_scan_preserves_availability(conn, root, monkeypatch, exc, status, reason):
    source = _source(conn, root)
    _index(conn, source, root)
    (root / DEEP).unlink()

    real = indexer.record_observation
    calls = iter(range(10**6))

    def flaky(*args):
        if next(calls) == 13:
            raise exc
        return real(*args)

    monkeypatch.setattr(indexer, "record_observation", flaky)
    with pytest.raises(type(exc)):
        _index(conn, source, root, batch_size=5)

    run = conn.execute(
        "SELECT status, interruption_reason, found_count, not_found_count FROM index_runs "
        "WHERE source_id = %s ORDER BY started_at DESC LIMIT 1", (source,),
    ).fetchone()
    assert run == (status, reason, 10, 0)  # só os 2 lotes confirmados
    assert {v[0] for v in _docs(conn).values()} == {"available"}

    # Execução interrompida não bloqueia a seguinte; varredura completa marca a remoção.
    monkeypatch.setattr(indexer, "record_observation", real)
    summary = _index(conn, source, root)
    assert (summary.status, summary.counts.not_found) == ("completed", 1)


def test_concurrent_run_on_same_source_refused(conn, root):
    source = _source(conn, root)
    conn.execute("INSERT INTO index_runs (source_id) VALUES (%s)", (source,))
    conn.commit()
    with pytest.raises(IndexerBusy):
        _index(conn, source, root)


def test_root_outside_allowed_roots_refused(conn, root, tmp_path):
    source = _source(conn, root)
    with pytest.raises(PermissionError):
        run_index(conn, source, allowed_roots=[str(tmp_path / "outra")])
    with pytest.raises(PermissionError):
        run_index(conn, source, allowed_roots=[])
    assert conn.execute("SELECT count(*) FROM index_runs").fetchone()[0] == 0


# --- raiz permitida: links em componentes intermediários (SPEC §5.5) ---------------------------

@pytest.fixture
def nested(tmp_path):
    """Raiz permitida com a fonte dois níveis abaixo e uma pasta externa de mesma forma."""
    allowed = tmp_path / "permitida"
    (allowed / "meio" / "fonte").mkdir(parents=True)
    (allowed / "meio" / "fonte" / "inside.txt").write_text("dentro")
    outside = tmp_path / "fora"
    (outside / "fonte").mkdir(parents=True)
    (outside / "fonte" / "outside.txt").write_text("fora")
    return allowed, outside


def test_intermediate_link_swapped_after_validation_is_refused(conn, nested, monkeypatch, tmp_path):
    allowed, outside = nested
    source = _source(conn, allowed / "meio" / "fonte")
    real_reader = indexer.SourceReader

    def swap_then_create(*args, **kwargs):
        # Entre a validação da raiz e a abertura: troca pasta intermediária por link para fora.
        (allowed / "meio").rename(tmp_path / "meio-original")
        (allowed / "meio").symlink_to(outside, target_is_directory=True)
        return real_reader(*args, **kwargs)

    monkeypatch.setattr(indexer, "SourceReader", swap_then_create)
    summary = run_index(conn, source, allowed_roots=[str(allowed)])

    assert _docs(conn) == {}
    assert summary.status == "failed"
    assert _errors(conn, summary.run_id) == [(None, "source_unavailable")]
    assert (outside / "fonte" / "outside.txt").read_text() == "fora"


def test_intermediate_link_present_before_scan_is_refused(conn, nested):
    allowed, outside = nested
    (allowed / "atalho").symlink_to(outside, target_is_directory=True)
    source = _source(conn, allowed / "atalho" / "fonte")

    try:
        summary = run_index(conn, source, allowed_roots=[str(allowed)])
    except PermissionError:
        assert conn.execute("SELECT count(*) FROM index_runs").fetchone()[0] == 0
    else:
        assert summary.status == "failed"
    assert _docs(conn) == {}


def test_allowed_root_reached_through_link_is_refused(conn, nested, tmp_path):
    allowed, _ = nested
    alias = tmp_path / "apelido"
    alias.symlink_to(allowed, target_is_directory=True)
    source = _source(conn, alias / "meio" / "fonte")

    summary = run_index(conn, source, allowed_roots=[str(alias)])

    assert summary.status == "failed"
    assert _docs(conn) == {}


def test_source_escaping_allowed_root_lexically_is_refused(conn, nested):
    allowed, _ = nested
    source = _source(conn, Path(str(allowed) + "/../fora/fonte"))
    with pytest.raises(PermissionError):
        run_index(conn, source, allowed_roots=[str(allowed)])
    assert conn.execute("SELECT count(*) FROM index_runs").fetchone()[0] == 0


def test_nested_source_under_allowed_root_is_indexed(conn, nested):
    allowed, _ = nested
    source = _source(conn, allowed / "meio" / "fonte")
    summary = run_index(conn, source, allowed_roots=[str(allowed)])
    assert summary.status == "completed"
    assert set(_docs(conn)) == {"inside.txt"}



def test_source_in_hidden_folder_and_source_equal_to_allowed_root(conn, tmp_path):
    hidden = tmp_path / "permitida" / ".oculta"
    hidden.mkdir(parents=True)
    (hidden / "a.txt").write_text("x")
    summary = run_index(conn, _source(conn, hidden), allowed_roots=[str(tmp_path / "permitida")])
    assert (summary.status, set(_docs(conn))) == ("completed", {"a.txt"})

    conn.execute("TRUNCATE index_errors, documents, index_runs, document_sources")
    conn.commit()
    summary = run_index(conn, _source(conn, hidden), allowed_roots=[str(hidden) + "/"])
    assert (summary.status, set(_docs(conn))) == ("completed", {"a.txt"})

# --- fronteira READ-ONLY -------------------------------------------------------------------------

def test_scan_opens_only_directories_read_only(conn, root, monkeypatch):
    source = _source(conn, root)
    flags_seen = []
    real_open = os.open

    def spy(path, flags, *args, **kwargs):
        flags_seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    _index(conn, source, root)
    monkeypatch.undo()

    write = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    assert flags_seen
    assert all(f & os.O_DIRECTORY and f & os.O_NOFOLLOW and not f & write for f in flags_seen)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissões")
def test_scan_of_read_only_copy_leaves_tree_unchanged(conn, root):
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            Path(dirpath, name).chmod(0o444)
    dirs = [Path(d) for d, _, _ in os.walk(root)]
    for d in dirs:
        d.chmod(0o555)
    try:
        before = _snapshot(root)
        source = _source(conn, root)
        assert _index(conn, source, root).status == "completed"
        assert _index(conn, source, root).status == "completed"
        assert _snapshot(root) == before
    finally:
        for d in dirs:
            d.chmod(0o755)


def test_original_sample_unchanged(conn):
    before = _snapshot(SAMPLE_ROOT)
    source = _source(conn, SAMPLE_ROOT)

    summary = run_index(conn, source, allowed_roots=[str(SAMPLE_ROOT)])

    assert (summary.status, summary.counts.found) == ("completed", SAMPLE_FILES)
    assert _snapshot(SAMPLE_ROOT) == before
    verify = subprocess.run(["sh", str(FIXTURES / "verify-fixture.sh")], capture_output=True)
    assert verify.returncode == 0, verify.stderr


# --- processo separado ---------------------------------------------------------------------------

def test_cli_runs_as_separate_process(conn, database_url, root):
    _source(conn, root, name="Laboratório CLI")
    env = {**os.environ, "DATABASE_URL": database_url, "INDEXER_ALLOWED_ROOTS": str(root)}

    result = subprocess.run(
        [sys.executable, "-m", "app.indexer", "--source", "Laboratório CLI"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "completed" in result.stdout
    assert str(root) not in result.stdout + result.stderr
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == SAMPLE_FILES

    env["INDEXER_ALLOWED_ROOTS"] = ""
    refused = subprocess.run(
        [sys.executable, "-m", "app.indexer", "--source", "Laboratório CLI"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert refused.returncode == 2
