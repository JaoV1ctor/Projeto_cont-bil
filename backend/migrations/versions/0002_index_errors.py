"""erros de indexação por execução (SPEC §§7.2, 8)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE index_errors (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id         uuid NOT NULL REFERENCES index_runs (id) ON DELETE RESTRICT,
            -- Item afetado relativo à raiz da fonte; NULL quando o erro é da fonte inteira.
            relative_path  text,
            code           text NOT NULL
                           CHECK (code IN ('source_unavailable', 'permission_denied', 'vanished',
                                           'changed_during_scan', 'invalid_name', 'os_error')),
            -- Descrição sanitizada: código do sistema, sem caminho absoluto nem conteúdo.
            message        text NOT NULL CHECK (btrim(message) <> ''),
            occurred_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX index_errors_run ON index_errors (run_id, occurred_at)")


def downgrade() -> None:
    op.execute("DROP TABLE index_errors")
