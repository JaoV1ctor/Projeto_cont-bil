import os


def database_url() -> str:
    """URL do PostgreSQL, lida somente do ambiente; segredos nunca ficam no código."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não definida (ver backend/.env.example)")
    return url


def sqlalchemy_url(url: str) -> str:
    """Força o driver psycopg 3 para SQLAlchemy/Alembic."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    raise ValueError("DATABASE_URL deve usar o esquema postgresql://")


def indexer_allowed_roots() -> list[str]:
    """Raízes que o indexador pode varrer (INDEXER_ALLOWED_ROOTS, separadas por os.pathsep).

    Segunda camada de proteção; o controle efetivo é a conta read-only (SPEC §5.1). Vazio recusa tudo.
    """
    raw = os.environ.get("INDEXER_ALLOWED_ROOTS", "")
    return [p for p in raw.split(os.pathsep) if p.strip()]
