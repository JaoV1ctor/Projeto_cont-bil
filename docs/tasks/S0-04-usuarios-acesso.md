# S0-04 — Usuários e acesso por associação (esquema)

**Status:** correções da revisão entregues para nova revisão.

**Objetivo:** migração `0003` com `users`, `associations` e `user_associations` (SPEC §§4.1, 8, 8.1).

**Restrições:** sem API, login, frontend, documentos reais, vínculos de documento ou decisão de empacotamento.

**Entregue:**

- `users`: nome, login ASCII de identificador (`[A-Za-z0-9._-]`, 1 a 64) único sem distinção de maiúsculas, hash de senha obrigatório e não branco (formato não verificado no banco), perfil `administrator`/`operator`/`viewer`, ativo, criação/atualização e responsável.
- `associations`: nome, nome de uso, CNPJ normalizado opcional (numérico ou alfanumérico, sem unicidade até a revisão de inconsistências), situação `active`/`inactive`, observações, criação/atualização e responsável.
- `user_associations`: par usuário/associação único, criação e responsável.
- Todas as FKs `ON DELETE RESTRICT`; nada em cascata.
- Propostas D-011 a D-014 em `docs/DECISIONS.md`.

**Aceite:**

- `0003` aplica e reverte (isoladamente e até `base`) no banco de teste.
- Testes cobrem duplicidade (login com diferença de maiúsculas, par), login Unicode recusado sem skip por `LC_CTYPE`, referências inválidas, perfis e situações inválidos, hash vazio/branco, exclusão de cadastro referenciado e ausência de cascata.
- Suíte existente continua passando.

**Correções da revisão:**

1. `password_hash`: regex Argon2id removida; mantidos `NOT NULL` e recusa de vazio/branco. Argon2id fica como proposta para a tarefa de login (D-011); o banco não valida hash real.
2. CNPJ: índice único removido até a revisão de inconsistências; formato numérico/alfanumérico preservado (D-013). Teste confirma duplicata aceita e ausência de índice único.
3. Login: restrito a ASCII de identificador com `COLLATE "C"`; unicidade por `lower(login COLLATE "C")`. Qualquer caractere Unicode (NFC, NFD, confusáveis) é recusado, sem depender de `LC_CTYPE` nem de banco UTF8 (D-012). Substitui a regra NFC anterior.

**Fora desta tarefa:** unicidade de CNPJ, autenticação, sessões, geração/verificação de hash, validação de dígitos do CNPJ, `updated_at` automático, auditoria (`audit_events`), emendas, vigências e vínculos de documento.
