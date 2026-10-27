# S0-03 — Indexação read-only de metadados no laboratório

**Status:** entregue para revisão.

**Objetivo:** varrer somente `tests/fixtures/servidor-teste/` ou cópia temporária dela e registrar metadados no catálogo via `record_observation`, com execução, contagens e erros (SPEC §§5, 7).

**Restrições:** sem escrita, renomeação ou exclusão na raiz lida; sem leitura de conteúdo; sem servidor real, API, frontend, agendamento ou escolha de P-03/P-04; indexador em processo separado da futura API.

**Entregue:**

- Migração `0002`: tabela `index_errors` (execução, item, código restrito, descrição sanitizada, data).
- `backend/app/source_reader.py`: lista diretórios e faz `stat` sem seguir links; abre somente diretórios (`O_RDONLY | O_DIRECTORY | O_NOFOLLOW`, relativo ao descritor do pai); recusa links e reparse points; arquivos especiais são ignorados. Exige POSIX.
- `backend/app/indexer.py`: `run_index()` e CLI `python -m app.indexer --source NOME`. Grava em lotes; nomes recusados pelo catálogo viram erro sem abortar o lote; raiz precisa estar em `INDEXER_ALLOWED_ROOTS` (vazio recusa).
- Regras de estado: `completed` só sem erros; com erros, `completed_with_errors`; fonte indisponível ou exceção, `failed`; cancelamento ou `SIGINT`, `cancelled`. Somente `completed` marca `not_found` e grava `last_complete_run_at`. Documento visto de novo volta a `available`.

**Aceite:**

- Testes com cópia temporária: primeira varredura, reexecução, arquivo novo/alterado/removido, link recusado (arquivo, pasta, quebrado, raiz), acesso negado, fonte indisponível, cancelamento, falha e interrupção no meio do lote, execução concorrente, raiz fora da lista permitida, CLI em subprocesso.
- Amostra original comparada antes e depois (modo, tamanho, mtime, SHA-256) e `verify-fixture.sh` após a varredura.
- Migrações `0001`/`0002` aplicam e revertem no banco de teste.

**Propostas para `docs/DECISIONS.md` (não registradas; arquivo fora do escopo desta tarefa):**

- Links, junctions e reparse points contam como `ignored`, não como erro; não impedem a marcação de não localizado.
- Nome que o catálogo recusa (segmento só de pontos/espaços, bytes fora de UTF-8) é erro `invalid_name`; a execução fica `completed_with_errors`.
- `not_found_count` conta apenas documentos que passaram de `available` para `not_found` na execução.
- Temporários e arquivos de sistema (`~$*`, `Thumbs.db`, `desktop.ini`) são indexados como qualquer arquivo; regra de exclusão depende de decisão de domínio.

**Fora desta tarefa:** execução órfã em `running` após término abrupto do processo (bloqueia a fonte até intervenção), limites de carga além de lotes (intervalo, timeout de rede), tratamento Windows/SMB (P-04), `document_categories` e classificação.
