<div align="center">

# Projeto Contábil

### Organização segura de documentos e rotinas contábeis em ambiente local

[![Status](https://img.shields.io/badge/status-em%20desenvolvimento-f59e0b?style=for-the-badge)](#estado-atual)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-local-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)

Aplicação web interna para localizar documentos, organizar associações, emendas e vigências e acompanhar pendências — sem alterar a estrutura física dos arquivos existentes.

</div>

> [!IMPORTANT]
> Projeto em desenvolvimento. A API HTTP e o frontend ainda não foram implementados. Não usar em produção nem conectar ao servidor real sem concluir as decisões de infraestrutura, os controles de segurança e a autorização prevista na especificação.

## Visão geral

O projeto nasceu para reduzir o tempo gasto procurando documentos em estruturas de pastas heterogêneas, com nomes inconsistentes e arquivos distribuídos pelo servidor do escritório.

O MVP 0 organiza metadados e vínculos no PostgreSQL, mantendo os documentos originais em sua localização atual. O fluxo planejado é:

> Entrar no sistema → escolher uma associação → listar documentos → pesquisar e filtrar → abrir o documento autorizado.

Princípios centrais:

- funcionamento local, sem dependência de internet durante a operação;
- acesso pelo navegador somente na rede interna autorizada;
- integração estritamente read-only com a origem dos documentos;
- autenticação, autorização e auditoria locais;
- dados reais, credenciais e documentos do escritório fora do repositório;
- implantação somente após aprovação explícita do responsável.

## Arquitetura planejada

```mermaid
flowchart TB
    U[Usuários na rede interna] -->|HTTPS| F[Interface Next.js]
    F -->|API| A[FastAPI]
    A --> D[(PostgreSQL local)]
    A --> R[Leitor de origem read-only]
    I[Indexador Python] --> D
    I --> R
    R -->|Listagem e leitura autorizadas| S[Servidor de arquivos]

    style S fill:#f8fafc,stroke:#64748b
    style D fill:#dbeafe,stroke:#2563eb
    style R fill:#dcfce7,stroke:#16a34a
```

API e indexador compartilham o domínio, mas executam como processos separados. O navegador nunca recebe caminho físico como mecanismo de acesso, e o leitor de origem não oferece operações de escrita, renomeação, exclusão ou reorganização.

## Estado atual

O backend de domínio está implementado até a tarefa **S0-09**:

- catálogo de fontes, documentos e execuções de indexação;
- indexador read-only restrito ao laboratório;
- usuários, associações e vínculos de acesso;
- senha com Argon2id e normalização Unicode NFC;
- bootstrap seguro do primeiro administrador;
- sessões opacas armazenadas somente como SHA-256;
- expiração por 30 minutos de inatividade ou 10 horas de duração máxima;
- bloqueio temporário após tentativas repetidas por login;
- autorização por perfil e associação;
- auditoria de autenticação e mudanças de acesso;
- migrações Alembic `0001` a `0006`.

A camada HTTP de autenticação está em revisão documental na **S0-10**. Ainda não existem API HTTP ou frontend do produto. O estado detalhado está em [Memória do projeto](docs/PROJECT_MEMORY.md) e [Pendências](PENDENCIAS.md).

## Stack

| Área | Tecnologia |
|---|---|
| Interface planejada | Next.js + TypeScript |
| Backend | Python + FastAPI |
| Banco | PostgreSQL local |
| Migrações | Alembic com SQL explícito |
| Acesso ao banco | psycopg 3, sem ORM na aplicação |
| Autenticação | Argon2id, sessões opacas no servidor |
| Testes | pytest + PostgreSQL descartável |

## Estrutura do repositório

```text
backend/
├── app/                    domínio, autenticação, catálogo e indexador
├── migrations/versions/    migrações SQL versionadas
└── tests/                  testes unitários e de integração
docs/
├── tasks/                  tarefas e critérios de aceite
├── ARCHITECTURE.md         componentes e limites de confiança
├── DECISIONS.md            decisões aprovadas e pendentes
└── PROJECT_MEMORY.md       ponto operacional de retomada
tests/fixtures/             amostra sintética do servidor de arquivos
PROJECT_SPEC.md             requisitos e regras canônicas
PENDENCIAS.md               índice operacional de pendências
```

## Preparação do backend

Requisitos atuais para desenvolvimento:

- Python 3.12 ou superior;
- PostgreSQL 13 ou superior para os testes de integração;
- ambiente Linux ou compatível com os comandos abaixo.

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

O `.env.example` contém somente valores fictícios. O arquivo `.env` é ignorado pelo Git.

### Migrações

```sh
cd backend
DATABASE_URL=postgresql://... .venv/bin/alembic upgrade head
```

### Testes sem PostgreSQL

```sh
cd backend
.venv/bin/pytest tests/test_db_guard.py tests/test_auth_passwords.py
```

### Testes de integração

> [!CAUTION]
> A suíte apaga e recria o schema `public`. Use exclusivamente um PostgreSQL local descartável, com banco terminado em `_test`. A proteção recusa host não loopback, `localhost`, socket, múltiplos hosts, query string e variáveis `PG*`.

```sh
cd backend
TEST_DATABASE_URL=postgresql://contabil_test:senha-ficticia@127.0.0.1:5432/contabil_test \
  .venv/bin/pytest
```

### Verificação da amostra sintética

```sh
sh tests/fixtures/verify-fixture.sh
```

Consulte o [README do backend](backend/README.md) para indexação de laboratório, bootstrap do administrador e detalhes do banco de teste.

## Segurança

- A origem dos documentos deve usar uma conta de serviço sem permissão de escrita.
- O desenvolvimento usa somente a amostra sintética em `tests/fixtures/servidor-teste/` ou cópia temporária.
- A aplicação nunca recebe caminho arbitrário do cliente para abrir arquivos.
- Links simbólicos e escapes da raiz autorizada são recusados.
- Senhas, tokens, credenciais e conteúdo integral de documentos não entram em logs ou auditoria.
- A role PostgreSQL da aplicação deve ser separada da role de migração antes da API e do piloto.
- Servidor real, dados reais e deploy exigem confirmação específica do responsável.

As regras completas estão em [PROJECT_SPEC.md](PROJECT_SPEC.md), especialmente nas seções 5 e 6.

## Roadmap resumido

- [x] Laboratório e amostra sintética
- [x] Catálogo e indexação read-only de laboratório
- [x] Usuários e acesso por associação
- [x] Senhas, administrador inicial, sessões e limite por login
- [x] Autorização por perfil e associação
- [ ] Camada HTTP de autenticação e separação de roles PostgreSQL
- [ ] Cadastros de associações, emendas e vigências
- [ ] Vínculos, classificação, busca e abertura mediada
- [ ] Pendências e dashboard
- [ ] Frontend Next.js
- [ ] Piloto controlado, após decisões de infraestrutura e autorização

## Documentação

- [Especificação do projeto](PROJECT_SPEC.md)
- [Arquitetura](docs/ARCHITECTURE.md)
- [Decisões](docs/DECISIONS.md)
- [Pendências](PENDENCIAS.md)
- [Memória operacional](docs/PROJECT_MEMORY.md)
- [Tarefas técnicas](docs/tasks/)
- [Amostra sintética](tests/fixtures/README.md)

---

<div align="center">
  <sub>MVP 0 focado em organização, consulta e segurança operacional.</sub>
</div>
