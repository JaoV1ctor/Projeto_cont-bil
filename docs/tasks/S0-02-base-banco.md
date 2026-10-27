# S0-02 — Stack aprovada e base do banco

**Status:** entregue para revisão.

**Objetivo:** registrar P-01/P-02 como aprovadas (D-005, D-006) e criar o esquema mínimo do catálogo para indexação em laboratório.

**Restrições:** somente laboratório; sem servidor real, leitura de documentos, API, frontend ou decisão de P-03; nenhuma escrita na origem.

**Aceite:**

- Migração `0001` aplica e reverte em banco de teste.
- Testes de integração passam: chaves, unicidade por fonte/caminho, reexecução sem duplicação.
- Configuração com valores fictícios; `.env` fora do Git.
- P-03 a P-07 continuam pendentes.

**Correções da revisão (bloqueios):**

1. Trava do banco de teste valida URL, ambiente libpq e destino efetivo antes de `DROP SCHEMA` (`backend/tests/db_guard.py`).
2. `documents.relative_path` recusa caminho absoluto e traversal em sintaxe POSIX e Windows.
3. `documents.last_seen_run_id` só referencia execução da mesma `source_id` (FK composta).

**Fora desta tarefa (próximas):** `index_errors`, `document_categories` com categoria/estado de classificação em `documents`, marcação de não localizado após varredura completa, leitor de origem e indexador.
