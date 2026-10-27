"""usuários, associações e acesso por associação (SPEC §§4.1, 8, 8.1)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE users (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name           text NOT NULL CHECK (btrim(name) <> ''),
            -- Somente ASCII de identificador (D-012): sem acentos, espaços ou formas Unicode
            -- visualmente iguais. COLLATE "C" fixa a avaliação independente de LC_CTYPE.
            login          text NOT NULL
                           CONSTRAINT users_login_ascii
                           CHECK (login COLLATE "C" ~ '^[A-Za-z0-9._-]{1,64}$'),
            -- Hash gerado pela futura tarefa de login. O banco só recusa vazio/branco;
            -- não verifica se o valor é um hash real (D-011).
            password_hash  text NOT NULL CHECK (password_hash !~ '^[[:space:]]*$'),
            role           text NOT NULL CHECK (role IN ('administrator', 'operator', 'viewer')),
            active         boolean NOT NULL DEFAULT true,
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            -- Responsável pelo cadastro; NULL somente no primeiro administrador.
            created_by     uuid REFERENCES users (id) ON DELETE RESTRICT
        )
        """
    )
    # lower() sob COLLATE "C" converte só A-Z, em qualquer LC_CTYPE (ex.: tr_TR não muda 'I').
    op.execute('CREATE UNIQUE INDEX users_login_unique ON users (lower(login COLLATE "C"))')
    op.execute(
        """
        CREATE TABLE associations (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name        text NOT NULL CHECK (btrim(name) <> ''),
            trade_name  text CHECK (trade_name IS NULL OR btrim(trade_name) <> ''),
            -- CNPJ normalizado: 12 posições alfanuméricas maiúsculas + 2 dígitos verificadores
            -- (formato numérico e alfanumérico). Sem pontuação. Dígitos verificadores: API.
            -- Sem unicidade até a revisão de inconsistências do cadastro (D-013).
            cnpj        text CHECK (cnpj IS NULL OR cnpj ~ '^[0-9A-Z]{12}[0-9]{2}$'),
            status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            notes       text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            created_by  uuid REFERENCES users (id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE user_associations (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
            association_id  uuid NOT NULL REFERENCES associations (id) ON DELETE RESTRICT,
            created_at      timestamptz NOT NULL DEFAULT now(),
            created_by      uuid REFERENCES users (id) ON DELETE RESTRICT,
            CONSTRAINT user_associations_pair_unique UNIQUE (user_id, association_id)
        )
        """
    )
    op.execute("CREATE INDEX user_associations_association ON user_associations (association_id)")


def downgrade() -> None:
    op.execute("DROP TABLE user_associations")
    op.execute("DROP TABLE associations")
    op.execute("DROP TABLE users")
