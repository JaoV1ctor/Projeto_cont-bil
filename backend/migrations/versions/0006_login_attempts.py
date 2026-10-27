"""limite de tentativas por login: login_attempts e login_lockouts (S0-08; R4/D-019)

Tentativas são registradas só para usuários existentes, por user_id. O texto digitado como
login nunca é gravado: pode ser uma senha digitada no campo errado.

`seq` ordena as tentativas na ordem transacional (tentativas do mesmo usuário são
serializadas pela trava da linha em users). Bloqueio e desbloqueio guardam a sequência da
última tentativa que os precede; a contagem usa essa ordem, não o horário.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE login_attempts (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            seq           bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            user_id       uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
            attempted_at  timestamptz NOT NULL,
            -- 'blocked': tentativa durante bloqueio; não conta para novo bloqueio.
            result        text NOT NULL CHECK (result IN ('success', 'failure', 'blocked')),
            -- Só armazenado; limite por IP depende de IP confiável (S0-10).
            source_ip     inet
        )
        """
    )
    op.execute("CREATE INDEX login_attempts_user_time ON login_attempts (user_id, attempted_at)")
    op.execute(
        """
        CREATE TABLE login_lockouts (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
            locked_at     timestamptz NOT NULL,
            locked_until  timestamptz NOT NULL,
            -- Falha que atingiu R4; só falhas com seq maior contam depois deste bloqueio.
            trigger_attempt_seq  bigint NOT NULL REFERENCES login_attempts (seq) ON DELETE RESTRICT,
            unlocked_at   timestamptz,
            unlocked_by   uuid REFERENCES users (id) ON DELETE RESTRICT,
            -- Última tentativa do usuário no momento do desbloqueio.
            unlocked_after_seq   bigint,
            CONSTRAINT login_lockouts_until_after_start CHECK (locked_until > locked_at),
            CONSTRAINT login_lockouts_unlock_consistent CHECK (
                (unlocked_at IS NULL) = (unlocked_by IS NULL)
                AND (unlocked_at IS NULL) = (unlocked_after_seq IS NULL)
            ),
            CONSTRAINT login_lockouts_unlock_after_trigger
                CHECK (unlocked_after_seq IS NULL OR unlocked_after_seq >= trigger_attempt_seq),
            CONSTRAINT login_lockouts_unlock_after_start
                CHECK (unlocked_at IS NULL OR unlocked_at >= locked_at)
        )
        """
    )
    op.execute("CREATE INDEX login_lockouts_user_time ON login_lockouts (user_id, locked_at)")


def downgrade() -> None:
    op.execute("DROP TABLE login_lockouts")
    op.execute("DROP TABLE login_attempts")
