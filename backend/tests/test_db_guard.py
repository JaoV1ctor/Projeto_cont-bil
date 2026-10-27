"""Trava do banco de testes. Não conecta a banco algum, exceto o teste final com stub."""
import pytest

from db_guard import UnsafeTestDatabase, validate_connection, validate_url

OK_URL = "postgresql://u:p@127.0.0.1:5432/contabil_test"


@pytest.mark.parametrize(
    "url",
    [
        OK_URL,
        "postgres://u:p@127.0.0.1/contabil_test",
        "postgresql://u:p@[::1]:5432/contabil_test",
        "postgresql://u:p@127.0.0.2:5432/contabil_test",
    ],
)
def test_accepts_loopback_test_database(url):
    assert validate_url(url, environ={})["dbname"] == "contabil_test"


@pytest.mark.parametrize(
    "url",
    [
        # Aparentam ser locais, mas redirecionam host ou banco.
        OK_URL + "?host=10.0.0.5",
        OK_URL + "?hostaddr=10.0.0.5",
        OK_URL + "?service=producao",
        OK_URL + "?dbname=producao",
        OK_URL + "?options=-csearch_path%3Doutro",
        OK_URL + "#producao",
        "postgresql://u:p@127.0.0.1,10.0.0.5:5432/contabil_test",
        "postgresql://u:p@127.0.0.1:5432,5433/contabil_test",
        "postgresql://u:p@localhost:5432/contabil_test",
        "postgresql://u:p@127.0.0.1.exemplo.invalid:5432/contabil_test",
        "postgresql:///contabil_test",
        "postgresql://u:p@%2Ftmp/contabil_test",
        # Destino ou banco explicitamente errados.
        "postgresql://u:p@10.0.0.5:5432/contabil_test",
        "postgresql://u:p@127.0.0.1:5432/producao",
        "postgresql://u:p@127.0.0.1:5432/contabil_test_backup",
        "postgresql://u:p@127.0.0.1:5432/",
        # Formato chave=valor permitiria hostaddr/service sem URL.
        "host=127.0.0.1 dbname=contabil_test hostaddr=10.0.0.5",
    ],
)
def test_rejects_redirecting_or_unsafe_url(url):
    with pytest.raises(UnsafeTestDatabase):
        validate_url(url, environ={})


@pytest.mark.parametrize(
    "var", ["PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGDATABASE", "PGPORT", "PGOPTIONS"]
)
def test_rejects_libpq_environment(var):
    with pytest.raises(UnsafeTestDatabase, match=var):
        validate_url(OK_URL, environ={var: "10.0.0.5"})


class _Info:
    def __init__(self, host, hostaddr, dbname):
        self.host, self.hostaddr, self.dbname = host, hostaddr, dbname


class _Conn:
    """Stub de conexão: parâmetros efetivos divergentes da URL validada."""

    def __init__(self, info, server_db):
        self.info, self._server_db = info, server_db

    def execute(self, _sql):
        return self

    def fetchone(self):
        return (self._server_db,)


@pytest.mark.parametrize(
    "info, server_db",
    [
        (_Info("127.0.0.1", "10.0.0.5", "contabil_test"), "contabil_test"),
        (_Info("db.exemplo.invalid", "", "contabil_test"), "contabil_test"),
        (_Info("127.0.0.1", "127.0.0.1", "producao"), "producao"),
        (_Info("127.0.0.1", "127.0.0.1", "contabil_test"), "producao"),
    ],
)
def test_rejects_unsafe_effective_connection(info, server_db):
    with pytest.raises(UnsafeTestDatabase):
        validate_connection(_Conn(info, server_db))


def test_accepts_safe_effective_connection():
    validate_connection(_Conn(_Info("127.0.0.1", "127.0.0.1", "contabil_test"), "contabil_test"))
