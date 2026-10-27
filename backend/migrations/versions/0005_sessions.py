"""sessões no servidor com token só como hash (S0-07; T3, R3)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE sessions (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
            -- SHA-256 do token opaco; o token em si nunca é gravado (T3).
            token_hash      bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
            created_at      timestamptz NOT NULL,
            last_used_at    timestamptz NOT NULL,
            -- Vida máxima (R3). Inatividade é calculada a partir de last_used_at.
            expires_at      timestamptz NOT NULL,
            revoked_at      timestamptz,
            revoked_reason  text CHECK (revoked_reason IN ('logout', 'revoked')),
            CONSTRAINT sessions_used_after_created CHECK (last_used_at >= created_at),
            CONSTRAINT sessions_expires_after_created CHECK (expires_at > created_at),
            CONSTRAINT sessions_revocation_consistent
                CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL)),
            CONSTRAINT sessions_revoked_after_created
                CHECK (revoked_at IS NULL OR revoked_at >= created_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE sessions")
