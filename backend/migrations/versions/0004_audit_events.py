"""auditoria mínima: audit_events somente inserção (SPEC §6; S0-06)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_events (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            occurred_at    timestamptz NOT NULL DEFAULT now(),
            -- Ator humano (usuário) ou serviço (ex.: 'bootstrap'), nunca os dois.
            actor_type     text NOT NULL CHECK (actor_type IN ('user', 'service')),
            actor_user_id  uuid REFERENCES users (id) ON DELETE RESTRICT,
            actor_service  text CHECK (actor_service IS NULL OR actor_service ~ '^[a-z][a-z0-9_]*$'),
            action         text NOT NULL CHECK (action ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'),
            target_type    text CHECK (target_type IS NULL OR target_type ~ '^[a-z][a-z0-9_]*$'),
            target_id      uuid,
            result         text NOT NULL CHECK (result IN ('success', 'denied', 'failure')),
            -- Detalhes sanitizados; nunca senha, token ou conteúdo de documento.
            details        jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
            CONSTRAINT audit_events_actor_consistent CHECK (
                (actor_type = 'user' AND actor_user_id IS NOT NULL AND actor_service IS NULL)
                OR (actor_type = 'service' AND actor_service IS NOT NULL AND actor_user_id IS NULL)
            ),
            CONSTRAINT audit_events_target_consistent CHECK (target_id IS NULL OR target_type IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX audit_events_occurred ON audit_events (occurred_at)")
    op.execute("CREATE INDEX audit_events_target ON audit_events (target_type, target_id)")
    op.execute("CREATE INDEX audit_events_actor_user ON audit_events (actor_user_id)")
    # Somente inserção: UPDATE e DELETE recusados no banco (SPEC §8: sem alteração pela API comum).
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events é somente inserção' USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
