# Backend (FastAPI/Python) — catálogo e indexador de laboratório

Estado: catálogo (`document_sources`, `index_runs`, `documents`, `index_errors`), gravação idempotente de metadados, indexador read-only de laboratório (S0-03), esquema de usuários e acesso por associação (`users`, `associations`, `user_associations`; S0-04), módulo de hash e política de senha (`app/auth/passwords.py`: Argon2id via `argon2-cffi`, NFC, 15 a 128 caracteres; S0-05) bootstrap do primeiro administrador com auditoria (`audit_events`; S0-06) e login/sessões no domínio (`app/auth/sessions.py`, tabela `sessions`; S0-07: token só como SHA-256, 30 min de inatividade / 10 h no máximo) e limite de tentativas por login (`app/auth/lockout.py`, tabelas `login_attempts` e `login_lockouts`; S0-08: 5 falhas em 15 min bloqueiam por 15 min) e autorização por associação (`app/auth/authorization.py`; S0-09: matriz por perfil, associação inativa só para administrador, sem autoalteração). Ainda sem limite por IP ou HTTP/API. Indexador só para `tests/fixtures/servidor-teste/` ou cópia dela; acesso ao servidor real depende de P-04.

## Preparar

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env   # valores fictícios; .env é ignorado pelo Git
```

## Migrações (Alembic, SQL explícito)

```sh
DATABASE_URL=postgresql://... .venv/bin/alembic upgrade head
DATABASE_URL=postgresql://... .venv/bin/alembic downgrade base
```

Migrações ficam em `migrations/versions/` com SQL escrito à mão; não há autogenerate.

## Indexador (somente laboratório)

Processo separado da futura API. Lê só metadados (nome, caminho relativo, extensão, tamanho, data de modificação); não abre arquivos nem escreve na raiz.

```sh
DATABASE_URL=postgresql://... INDEXER_ALLOWED_ROOTS=/caminho/absoluto/da/copia \
  .venv/bin/python -m app.indexer --source "Nome da fonte"
```

- A fonte (`document_sources.root_path`) deve estar dentro de uma raiz de `INDEXER_ALLOWED_ROOTS` (separadas por `:`). Variável vazia recusa tudo.
- A raiz permitida e a fonte são abertas de `/` em diante, componente a componente, sem seguir links. Caminho com link em qualquer componente falha como fonte indisponível; use o caminho real.
- Saída `0` somente para `completed`; `1` para execução com erros, falha ou cancelamento; `2` para fonte inexistente, raiz fora da lista ou execução já em andamento. `SIGTERM` cancela.
- Execução encerrada à força (kill -9) fica `running` e bloqueia a fonte até intervenção manual.

## Primeiro administrador (S0-06)

```sh
DATABASE_URL=postgresql://... .venv/bin/python -m app.admin create-first-admin --name "Nome" --login login.ascii
```

- Senha digitada duas vezes no terminal (sem eco). Não existe opção nem variável de ambiente para ela; entrada por pipe ou arquivo é recusada.
- Só cria quando não existe nenhum usuário `administrator` (ativo ou inativo). Execuções simultâneas são serializadas por advisory lock (`app/db_locks.py`).
- A transação do bootstrap força READ COMMITTED antes do lock, qualquer que seja o isolamento padrão da conexão.
- Eventos em `audit_events`, com ator de serviço `bootstrap`, só para tentativas que chegam à transação: `success` (administrador criado), `denied` (já existe administrador) e `failure` (nome ou login recusado pelo cadastro). Não geram evento, porque são recusadas antes da transação: senha fora da política, senhas que não conferem, entrada que não é terminal e conexão em autocommit ou com transação aberta.
- O trigger de `audit_events` recusa `UPDATE` e `DELETE`, mas não protege contra o dono da tabela nem contra `TRUNCATE`. Na API e no piloto, a role da aplicação não pode ser dona da tabela nem ter `UPDATE`/`DELETE`/`TRUNCATE` nela.

## Testes de integração

Exigem um PostgreSQL local descartável; os testes apagam e recriam o schema `public` desse banco. A trava (`tests/db_guard.py`) exige URL `postgresql://` com IP loopback literal (`127.0.0.1`, `[::1]`; não `localhost` nem socket), banco com sufixo `_test`, sem query string, um único host e nenhuma variável `PG*` no ambiente. Depois de conectar, confere endereço e banco efetivos antes de qualquer `DROP`/`TRUNCATE`.

```sh
TEST_DATABASE_URL=postgresql://contabil_test:senha-ficticia@127.0.0.1:5432/contabil_test .venv/bin/pytest
```

Qualquer PostgreSQL 13+ local serve (`gen_random_uuid()` nativo). Exemplo usado no desenvolvimento, apenas como banco de teste descartável (não decide P-03):

```sh
podman run -d --rm --name contabil-pg-test -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=contabil_test -e POSTGRES_PASSWORD=senha-ficticia -e POSTGRES_DB=contabil_test \
  docker.io/library/postgres:17-alpine
```
