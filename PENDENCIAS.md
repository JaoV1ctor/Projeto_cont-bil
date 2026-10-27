# Pendências do projeto

Índice operacional, atualizado em 27/10/2026. Não é fonte de requisitos nem de decisões: cada item aponta para a fonte canônica (`PROJECT_SPEC.md`, `docs/DECISIONS.md`, `docs/tasks/`). Em caso de diferença, vale a fonte canônica. Contexto de retomada: `docs/PROJECT_MEMORY.md`.

Legenda de responsável: **Resp.** = responsável pelo projeto; **Infra** = infraestrutura do escritório; **Codex** = arquiteto/revisor; **Claude** = implementador.

## 1. Estado confirmado

- Domínio do backend implementado até S0-09 (migrações `0001`–`0006`): catálogo, indexador read-only de laboratório, usuários, hash de senha, primeiro administrador, sessões, limite por login e autorização por associação.
- S0-09: revisão técnica do Codex concluída sem bloqueios (registrada em `docs/PROJECT_MEMORY.md`).
- Último teste PostgreSQL da S0-09: `426 passed`, relatado pelo Claude em execução anterior (PostgreSQL 17 descartável). Resultado histórico; não foi reexecutado nesta rodada. Confirmar novamente após mudanças de código.
- Não existe API HTTP nem frontend do produto. A segunda revisão documental da S0-10 terminou com três ajustes pendentes; implementação não iniciada.
- Repositório versionado e publicado no remoto informado pelo responsável em 27/10/2026. Sem acesso ao servidor real, sem dados reais, sem deploy.

## 2. Próxima tarefa técnica

| Item | Estado | Dependência / bloqueio | Responsável | Próximo passo | Referência |
|---|---|---|---|---|---|
| Correção documental da S0-09 | Concluída e revisada sem bloqueios | Nenhuma | — | Nenhum | `docs/tasks/S0-05-autenticacao-autorizacao.md` (quadro) |
| Detalhar S0-10 (HTTP, cookies, CSRF, IP confiável, limite por IP, cabeçalhos) | Segunda revisão concluída com três ajustes pendentes. Subtarefas S0-10a–e; R7–R9 e T10–T21 ainda não aprovados. **Não implementada** | Claude corrigir roles privilegiadas, T11/T20 e auditoria do bloqueio por IP; depois, terceira revisão do Codex | Claude (correção); Codex (revisão); Resp. (R7–R9) | Corrigir somente a proposta documental | `docs/tasks/S0-10-http.md` |
| Implementar S0-10 | **Não iniciada** | Proposta documental aprovada; roles separadas em S0-10b; R8 antes de S0-10e; R7 apenas para execução fora dos testes; P-04 e P-07 antes de qualquer ativação real | Claude | Aguardar correção e terceira revisão | `docs/tasks/S0-10-http.md` §§2, 4 |
| Separar roles de migração e de aplicação para proteger `audit_events` | **Requisito obrigatório** para a API (S0-10) e o piloto: a role da aplicação não é dona de `audit_events`, não tem `UPDATE`, `DELETE` nem `TRUNCATE` e tem só `INSERT` e `SELECT`. O trigger `audit_events_append_only` (0004) não basta. Não implementado | Bloqueia a API (S0-10) e o piloto | Codex (detalhar tarefa); Claude (implementar e testar no laboratório); Infra (provisionar roles no ambiente real); Resp. (confirmar qualquer acesso real ou deploy) | Codex detalhar a tarefa | `PROJECT_SPEC.md` §6; `docs/tasks/S0-05-autenticacao-autorizacao.md` §5 |

## 3. Decisões do responsável ou da infraestrutura

Nada aqui está decidido. Opções e bloqueios completos em `docs/DECISIONS.md` (Pendentes).

| ID | Questão | Estado | Bloqueia | Responsável | Próximo passo | Referência |
|---|---|---|---|---|---|---|
| P-04 | Ambiente: SO do servidor de arquivos e da VM, protocolo (SMB/NFS), domínio, raízes autorizadas, volume e capacidade | Pendente | Leitor de origem, conta de serviço, links e maiúsculas; P-03; rede/proxy de S0-10 | Infra | Levantar as respostas | `docs/DECISIONS.md` P-04; `PROJECT_SPEC.md` §13 |
| P-03 | Empacotamento: Docker Compose ou serviços nativos | Pendente | Execução local e montagem do compartilhamento | Depende de P-04; escolha de serviço exige Resp. | Decidir após P-04 | `docs/DECISIONS.md` P-03 |
| P-07 | HTTPS/certificados, backup e restauração, retenção de logs, tentativas e cópias | Pendente | Piloto; cookies `Secure` de S0-10 | Infra (coordenação: Resp.) | Levantar respostas | `docs/DECISIONS.md` P-07; `PROJECT_SPEC.md` §§6, 13 |
| P-05 | Lint/formatação Python e TypeScript; versões mínimas de Python e PostgreSQL | Pendente | Comandos em `AGENTS.md`; depende de P-04 | Codex (proposta); Resp. (aprova) | Propor após P-04 | `docs/DECISIONS.md` P-05 |
| P-06 | Índice de busca no PostgreSQL (ex.: trigram, `unaccent`) | Pendente | Desempenho de pesquisa; depende de medição | Codex (proposta); Resp. (aprova) | Medir no laboratório e então propor | `docs/DECISIONS.md` P-06; `PROJECT_SPEC.md` §8.1 |
| Servidor real e deploy | Nenhum autorizado | Qualquer acesso ao servidor, dados ou credenciais reais; qualquer deploy, inclusive em rede local | Resp. | **Confirmação explícita obrigatória** antes de cada acesso real ou deploy; autorização separada do leitor de origem | `AGENTS.md` (Pare e peça decisão); `PROJECT_SPEC.md` §§5, 6, 11 (Etapa 3), 12 |

## 4. Propostas aguardando revisão

Continuam **propostas**, não aprovadas. Não tratar como vigentes até o responsável aprovar e `docs/DECISIONS.md` ser atualizado.

| IDs | Assunto | Estado | Responsável | Próximo passo | Referência |
|---|---|---|---|---|---|
| D-002 | Contexto persistente (`AGENTS.md` canônico) | Proposta | Resp. (com Codex) | Revisar e aprovar ou ajustar | `docs/DECISIONS.md` |
| D-003 | Amostra sintética versionada em `tests/fixtures/servidor-teste/` | Proposta | Idem | Idem | Idem |
| D-004 | Verificação da amostra em POSIX `sh` | Proposta | Idem | Idem | Idem |
| D-007 | Ferramentas do backend (Alembic com SQL, psycopg 3 sem ORM, pytest) | Proposta | Idem | Idem | Idem |
| D-008 | `normalization_policy` somente `exact` | Proposta; depende de P-04 para outras políticas | Idem | Idem | Idem |
| D-009 | Categoria/estado de classificação e `index_errors` adiados | Proposta | Idem | Idem | Idem |
| D-010 | Proteção de banco de teste (sufixo `_test`, loopback) | Proposta | Idem | Idem | Idem |
| D-012 | Perfis e formato de login | Proposta | Idem | Revisar e aprovar ou ajustar | Idem |
| D-013 | `associations.cnpj`, status e unicidade | Proposta; unicidade de CNPJ aguarda revisão de inconsistências | Idem | Revisar e aprovar ou ajustar | Idem |

Aprovadas e fora desta lista: D-001, D-005, D-006, D-011, D-014–D-021.

## 5. Etapas funcionais restantes do MVP 0

Nenhum dos fluxos abaixo está completo; algumas estruturas e partes técnicas já existem e aparecem como parciais. Ordem e dependências da tabela são planejamento proposto quando não definidas nas fontes canônicas. Cada etapa precisa de tarefa pequena detalhada pelo Codex, com critérios de aceite, e depende da camada HTTP (S0-10), salvo quando indicado. Requisitos em `PROJECT_SPEC.md` §4 e §8; roadmap na Etapa 2 (§11).

| Etapa | Estado | Dependência / bloqueio | Responsável | Próximo passo | Referência |
|---|---|---|---|---|---|
| Cadastros (associações, emendas e vigências) | Parcial: esquema de associações (S0-04); sem fluxo de cadastro | S0-10; significado de emenda/instrumento/vigência no escritório (regra de domínio não escrita) | Resp. (regra de domínio); Codex (tarefa) | Levantar definições e planejar tarefa | `PROJECT_SPEC.md` §4.2, §13 |
| Vínculos de documentos | Não iniciado | Cadastros; categoria/estado de documentos (D-009) | Codex | Planejar tarefa | `PROJECT_SPEC.md` §4.3, §8.1 |
| Classificação | Não iniciado | Vínculos; migração de `document_categories` (D-009) | Codex | Planejar tarefa | `PROJECT_SPEC.md` §4.3, §8 |
| Busca e filtros | Não iniciado | Vínculos e classificação para os filtros de associação, categoria e estado (§4.4). Busca básica por metadados não depende de P-06; P-06 trata só de índices e otimização após medição | Codex | Planejar tarefa | `PROJECT_SPEC.md` §4.4, §10.1 |
| Abertura mediada de documentos | Não iniciado | Busca; S0-09 (autorização); conta read-only real só via P-04 e autorização separada | Codex | Planejar tarefa | `PROJECT_SPEC.md` §§4.4, 5 |
| Pendências | Não iniciado | Cadastros e vínculos | Codex | Planejar tarefa | `PROJECT_SPEC.md` §4.5 |
| Dashboard | Não iniciado | Pendências e busca; mesma autorização de acesso | Codex | Planejar tarefa | `PROJECT_SPEC.md` §4.6 |
| Frontend (Next.js/TypeScript, só interface) | Não iniciado | S0-10; P-05 (lint TypeScript) | Codex | Planejar tarefa | `docs/DECISIONS.md` D-005; `PROJECT_SPEC.md` §2.2 |
| Auditoria básica dos fluxos acima | Parcial (autenticação e autorização) | Cada fluxo novo | Claude em cada tarefa | Incluir no aceite de cada tarefa | `PROJECT_SPEC.md` §6, §11 |

## 6. Fluxo de cada item técnico

Codex define tarefa e critérios → Claude implementa e testa → Codex revisa → Claude corrige → Resp. valida → confirmação explícita antes de qualquer deploy (`PROJECT_SPEC.md` §12, §15.8).
