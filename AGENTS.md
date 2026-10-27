# AGENTS.md — regras compartilhadas (Claude Code e Codex)

Requisitos, segurança e papéis estão em `PROJECT_SPEC.md`. Este arquivo não os repete: indica onde cada regra vive e quando parar. Em conflito, vale a fonte canônica abaixo.

## Fonte canônica por assunto

| Assunto | Fonte |
|---|---|
| Escopo, requisitos, fora de escopo | `PROJECT_SPEC.md` §§ 4, 9 |
| Segurança do servidor de arquivos (READ-ONLY) | `PROJECT_SPEC.md` § 5 |
| Segurança da aplicação, segredos, dados reais | `PROJECT_SPEC.md` § 6 |
| Indexação | `PROJECT_SPEC.md` § 7 |
| Papéis, ciclo de trabalho, qualidade | `PROJECT_SPEC.md` § 12 |
| Formatos de tarefa, revisão e achados; economia de tokens | `PROJECT_SPEC.md` § 15 |
| Arquitetura proposta e limites de componentes | `docs/ARCHITECTURE.md` |
| Decisões aprovadas e pendentes | `docs/DECISIONS.md` |
| Tarefas e critérios de aceite | `docs/tasks/` |
| Amostra sintética | `tests/fixtures/README.md` |

## Pare e peça decisão ao responsável quando a tarefa exigir

- acesso ao servidor do escritório, a dados reais ou a credenciais reais;
- qualquer operação que possa escrever na origem dos documentos;
- deploy, inclusive em rede local;
- adotar, trocar ou adicionar stack, framework ou serviço ainda pendente em `docs/DECISIONS.md`;
- enviar conteúdo do projeto a serviço externo (conectores, nuvem, telemetria);
- regra contábil ou de domínio não escrita na SPEC.

## Estado atual

Stack aprovada: D-005 e D-006 em `docs/DECISIONS.md`. Backend tem catálogo (S0-02), indexador read-only de laboratório (S0-03, `python -m app.indexer`, restrito a `INDEXER_ALLOWED_ROOTS`), esquema de usuários e acesso por associação (S0-04), módulo de hash e política de senha (S0-05, `app/auth/passwords.py`), bootstrap do primeiro administrador com `audit_events` (S0-06, `python -m app.admin create-first-admin`), login/sessões no domínio (S0-07, `app/auth/sessions.py`), limite de tentativas por login (S0-08, `app/auth/lockout.py`) e autorização por associação no domínio (S0-09, `app/auth/authorization.py`); ainda sem limite por IP, HTTP/API ou frontend. Indexador não acessa servidor real até P-04. Empacotamento (P-03) e infraestrutura continuam pendentes.

Ponto de retomada e próximos passos: `docs/PROJECT_MEMORY.md` (resumo operacional; as fontes canônicas acima prevalecem).

## Comandos de validação

```sh
sh tests/fixtures/verify-fixture.sh   # integridade da amostra sintética
cd backend && TEST_DATABASE_URL=postgresql://...:.../<nome>_test .venv/bin/pytest   # integração com PostgreSQL
```

Preparação do ambiente e banco de teste: `backend/README.md`. Lint e frontend: após P-05 e tarefa do frontend.

## Convenções

- Documentação e mensagens ao responsável em português do Brasil; identificadores de código conforme a stack escolhida.
- Testes nunca apontam para caminho real; usam `tests/fixtures/servidor-teste/` ou cópia temporária dela.
- Mudança de decisão: atualizar `docs/DECISIONS.md` (e a SPEC, se for requisito) no mesmo diff.
