"""catálogo inicial: document_sources, index_runs, documents (SPEC §§7, 8)

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_sources (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name                  text NOT NULL UNIQUE CHECK (btrim(name) <> ''),
            root_path             text NOT NULL CHECK (btrim(root_path) <> ''),
            -- Somente 'exact' até P-04 definir o sistema de arquivos (sensibilidade a maiúsculas).
            normalization_policy  text NOT NULL CHECK (normalization_policy IN ('exact')),
            -- Referência ao segredo (ex.: nome de variável), nunca a credencial.
            credential_ref        text,
            active                boolean NOT NULL DEFAULT true,
            status                text NOT NULL DEFAULT 'unknown'
                                  CHECK (status IN ('unknown', 'available', 'unavailable')),
            last_complete_run_at  timestamptz,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE index_runs (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id            uuid NOT NULL REFERENCES document_sources (id) ON DELETE RESTRICT,
            scope                text NOT NULL DEFAULT '',
            status               text NOT NULL DEFAULT 'running'
                                 CHECK (status IN ('running', 'completed', 'completed_with_errors',
                                                   'failed', 'cancelled')),
            started_at           timestamptz NOT NULL DEFAULT now(),
            finished_at          timestamptz,
            found_count          integer NOT NULL DEFAULT 0 CHECK (found_count >= 0),
            new_count            integer NOT NULL DEFAULT 0 CHECK (new_count >= 0),
            updated_count        integer NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
            not_found_count      integer NOT NULL DEFAULT 0 CHECK (not_found_count >= 0),
            ignored_count        integer NOT NULL DEFAULT 0 CHECK (ignored_count >= 0),
            error_count          integer NOT NULL DEFAULT 0 CHECK (error_count >= 0),
            interruption_reason  text,
            last_position        text,
            CONSTRAINT index_runs_finished_iff_not_running
                CHECK ((status = 'running') = (finished_at IS NULL)),
            CONSTRAINT index_runs_finished_after_start
                CHECK (finished_at IS NULL OR finished_at >= started_at),
            -- Execução com erros não pode aparecer como sucesso completo (SPEC §7.2).
            CONSTRAINT index_runs_completed_without_errors
                CHECK (status <> 'completed' OR error_count = 0),
            -- Alvo da FK composta de documents (execução da mesma fonte).
            CONSTRAINT index_runs_id_source_unique UNIQUE (id, source_id)
        )
        """
    )
    # Uma execução em andamento por fonte (SPEC §7.2: evitar execuções concorrentes).
    op.execute(
        "CREATE UNIQUE INDEX index_runs_one_running_per_source ON index_runs (source_id) "
        "WHERE status = 'running'"
    )
    op.execute("CREATE INDEX index_runs_source_started ON index_runs (source_id, started_at DESC)")
    op.execute(
        r"""
        CREATE TABLE documents (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id           uuid NOT NULL REFERENCES document_sources (id) ON DELETE RESTRICT,
            relative_path       text NOT NULL,
            path_key            text NOT NULL CHECK (path_key <> ''),
            name                text NOT NULL CHECK (name <> ''),
            extension           text CHECK (extension IS NULL OR (extension <> '' AND extension = lower(extension))),
            size_bytes          bigint NOT NULL CHECK (size_bytes >= 0),
            source_modified_at  timestamptz NOT NULL,
            first_seen_at       timestamptz NOT NULL DEFAULT now(),
            last_seen_at        timestamptz NOT NULL DEFAULT now(),
            last_seen_run_id    uuid,
            availability        text NOT NULL DEFAULT 'available'
                                CHECK (availability IN ('available', 'not_found')),
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT documents_source_path_key_unique UNIQUE (source_id, path_key),
            -- Última execução que viu o documento pertence à mesma fonte.
            CONSTRAINT documents_last_seen_run_same_source
                FOREIGN KEY (last_seen_run_id, source_id) REFERENCES index_runs (id, source_id)
                ON DELETE RESTRICT,
            -- Caminho relativo seguro sem presumir o SO do servidor (SPEC §5.5): '/' e '\' são
            -- separadores; recusa unidade (C:), raiz, UNC, segmento vazio e segmento só de
            -- pontos/espaços ('.', '..', '...', '.. '), que o Win32 reduz a '.' ou '..'.
            CONSTRAINT documents_relative_path_safe CHECK (
                relative_path !~ '^[A-Za-z]:'
                AND relative_path !~ '(^|[/\\])[. ]*([/\\]|$)'
            ),
            CONSTRAINT documents_seen_order CHECK (last_seen_at >= first_seen_at)
        )
        """
    )
    op.execute("CREATE INDEX documents_last_seen_run ON documents (last_seen_run_id)")
    op.execute("CREATE INDEX documents_source_availability ON documents (source_id, availability)")


def downgrade() -> None:
    op.execute("DROP TABLE documents")
    op.execute("DROP TABLE index_runs")
    op.execute("DROP TABLE document_sources")
