"""Trava do banco de testes: só libera banco `_test` em endereço loopback explícito.

Os testes apagam o schema `public`; nenhuma etapa destrutiva roda antes de
`validate_url` (antes de conectar) e `validate_connection` (parâmetros efetivos).
"""
import ipaddress
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict

ALLOWED_KEYS = {"host", "port", "user", "password", "dbname"}


class UnsafeTestDatabase(ValueError):
    pass


def _require_loopback_ip(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise UnsafeTestDatabase(f"host deve ser IP loopback literal, não {host!r}") from None
    if not ip.is_loopback:
        raise UnsafeTestDatabase(f"host não é loopback: {host}")


def _require_test_dbname(dbname: str | None) -> None:
    if not dbname or not dbname.endswith("_test"):
        raise UnsafeTestDatabase(f"banco deve terminar em _test, não {dbname!r}")


def validate_url(url: str, environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Valida a URL e o ambiente antes de qualquer conexão; retorna os parâmetros aceitos."""
    libpq_vars = sorted(k for k in environ if k.startswith("PG"))
    if libpq_vars:
        raise UnsafeTestDatabase(f"variáveis libpq não permitidas no ambiente: {', '.join(libpq_vars)}")
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres"):
        raise UnsafeTestDatabase("TEST_DATABASE_URL deve ser URL postgresql://")
    if parts.query or parts.fragment:
        raise UnsafeTestDatabase("TEST_DATABASE_URL não pode ter query string nem fragmento")
    params = conninfo_to_dict(url)
    extra = sorted(set(params) - ALLOWED_KEYS)
    if extra:
        raise UnsafeTestDatabase(f"parâmetros não permitidos: {', '.join(extra)}")
    if "," in params.get("host", "") or "," in params.get("port", ""):
        raise UnsafeTestDatabase("múltiplos hosts não permitidos")
    _require_loopback_ip(params.get("host", ""))
    _require_test_dbname(params.get("dbname"))
    return params


def validate_connection(conn: psycopg.Connection) -> None:
    """Confere o destino efetivo da conexão aberta (cliente e servidor)."""
    info = conn.info
    _require_loopback_ip(info.hostaddr or info.host)
    _require_test_dbname(info.dbname)
    server_db = conn.execute("SELECT current_database()").fetchone()[0]
    _require_test_dbname(server_db)


def connect_checked(url: str, **kwargs) -> psycopg.Connection:
    """Conecta somente com os parâmetros validados e confere o destino efetivo."""
    params = validate_url(url)
    conn = psycopg.connect(**params, **kwargs)
    try:
        validate_connection(conn)
    except BaseException:
        conn.close()
        raise
    return conn
