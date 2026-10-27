import unicodedata
from datetime import timedelta

import pytest

from app.catalog import ObservedFile, record_observation, split_name
from helpers import MTIME, finish_run, make_source, start_run

# Metadados sintéticos inspirados em tests/fixtures/servidor-teste; nenhum arquivo é lido.
SAMPLE = [
    "ASSOCIAÇÕES/Associação Exemplo Aurora/2023/Emenda 2023-0007/Plano de Trabalho.pdf",
    "ASSOCIAÇÕES/Associação Exemplo Aurora/2024/Emenda 2024-0001/Plano de Trabalho.pdf",
    "ASSOCIAÇÕES/Instituto Exemplo Ipê/Emenda 2024-0001/Plano de Trabalho.pdf",
    "ASSOC GRUPO EXEMPLO SAO JOAO/estatuto.PDF",
    "ASSOC GRUPO EXEMPLO SAO JOAO/estatuto (1).pdf",
    "Nomes especiais/Relatório de Execução.txt",
    "Nomes especiais/" + unicodedata.normalize("NFD", "Relatório de Execução.txt"),
    "Nomes especiais/vazio.pdf",
    "Nomes especiais/sem extensao",
    "Nomes especiais/.arquivo-oculto",
]


def _observe(path, size=10, mtime=MTIME):
    return ObservedFile(relative_path=path, size_bytes=size, modified_at=mtime)


def _scan(conn, source, files):
    run = start_run(conn, source)
    outcomes = [record_observation(conn, source, run, f) for f in files]
    finish_run(conn, run)
    return run, outcomes


def _count(conn):
    return conn.execute("SELECT count(*) FROM documents").fetchone()[0]


def test_rerun_without_changes_does_not_duplicate(conn):
    source = make_source(conn)
    files = [_observe(p) for p in SAMPLE]

    _, first = _scan(conn, source, files)
    first_seen = dict(conn.execute("SELECT path_key, first_seen_at FROM documents").fetchall())
    run2, second = _scan(conn, source, files)

    assert first == ["new"] * len(SAMPLE)
    assert second == ["unchanged"] * len(SAMPLE)
    assert _count(conn) == len(SAMPLE)
    assert dict(conn.execute("SELECT path_key, first_seen_at FROM documents").fetchall()) == first_seen
    assert {r[0] for r in conn.execute("SELECT last_seen_run_id FROM documents")} == {run2}


def test_changed_metadata_updates_without_duplicate(conn):
    source = make_source(conn)
    path = SAMPLE[0]
    _scan(conn, source, [_observe(path)])
    _, outcomes = _scan(conn, source, [_observe(path, size=20, mtime=MTIME + timedelta(days=1))])

    assert outcomes == ["updated"]
    assert _count(conn) == 1
    assert conn.execute("SELECT size_bytes FROM documents").fetchone()[0] == 20


def test_missing_file_is_not_deleted(conn):
    source = make_source(conn)
    _scan(conn, source, [_observe(p) for p in SAMPLE])
    _scan(conn, source, [_observe(SAMPLE[0])])
    assert _count(conn) == len(SAMPLE)


def test_exact_policy_keeps_case_and_unicode_variants_distinct(conn):
    source = make_source(conn)
    nfc = "Relatório.txt"
    nfd = unicodedata.normalize("NFD", nfc)
    _, outcomes = _scan(conn, source, [_observe(p) for p in ("A.pdf", "a.pdf", nfc, nfd)])
    assert outcomes == ["new"] * 4
    stored = {r[0] for r in conn.execute("SELECT relative_path FROM documents")}
    assert stored == {"A.pdf", "a.pdf", nfc, nfd}


def test_run_from_other_source_rejected(conn):
    source_a = make_source(conn, "Fonte A")
    source_b = make_source(conn, "Fonte B")
    run_b = start_run(conn, source_b)
    with pytest.raises(ValueError, match="não pertence"):
        record_observation(conn, source_a, run_b, _observe("a.pdf"))


def test_finished_run_rejected(conn):
    source = make_source(conn)
    run = start_run(conn, source)
    finish_run(conn, run)
    with pytest.raises(ValueError, match="não está em andamento"):
        record_observation(conn, source, run, _observe("a.pdf"))


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/estatuto.PDF", ("estatuto.PDF", "pdf")),
        ("nome.com.varios.pontos.pdf", ("nome.com.varios.pontos.pdf", "pdf")),
        ("sem extensao", ("sem extensao", None)),
        (".arquivo-oculto", (".arquivo-oculto", None)),
        ("termina.", ("termina.", None)),
    ],
)
def test_split_name(path, expected):
    assert split_name(path) == expected
