# Decisões

Formato: ID, decisão, motivo, origem/aprovação. Restrições já definidas na SPEC não são repetidas aqui; estão em `PROJECT_SPEC.md` §2.1.

## Aprovadas

| ID | Decisão | Motivo | Origem |
|---|---|---|---|
| D-001 | Restrições de `PROJECT_SPEC.md` §2.1 valem como decisões aprovadas | Definidas pelo responsável | SPEC v0.2 |
| D-005 | Frontend: Next.js com TypeScript, restrito à interface. Sem rotas de API, regras de negócio, acesso ao banco ou à origem no Next.js | Resolve P-01; um único backend (SPEC §2.2) | Responsável, 15/10/2026 |
| D-006 | Backend: FastAPI/Python para API, autenticação, autorização e abertura mediada; indexador Python como processo separado no mesmo código; PostgreSQL local como único banco | Resolve P-02; stack do desenvolvedor (SPEC §2.2) | Responsável, 15/10/2026 |
| D-011 | Argon2id (formato PHC) como algoritmo de hash de senha. O banco não valida o formato: `users.password_hash` exige apenas valor não nulo e não branco | SPEC §6 (algoritmo apropriado); fixar formato antes da biblioteca e dos parâmetros criaria falsa garantia | S0-04; confirmada por D-015 e pelo responsável em 19/10/2026 |
| D-015 | Hash de senha com `argon2-cffi` (Argon2id, formato PHC), dependência `argon2-cffi>=25.1,<26` em `backend/pyproject.toml`. Confirma D-011 | Resolve R1 (S0-05) | Responsável, 19/10/2026 |
| D-016 | Política de senha: mínimo de 15 caracteres (login só com senha), sem regras de composição, máximo de pelo menos 64 | Resolve R2 (S0-05); referência NIST SP 800-63B rev. 4 | Responsável, 19/10/2026 |
| D-014 | `created_by` (responsável) opcional em `users`, `associations` e `user_associations`, FK `RESTRICT` para `users`; NULL para o primeiro administrador e cargas iniciais. Acesso global do administrador vem do perfil, sem linhas em `user_associations` | SPEC §§4.1, 8; sem exclusão em cascata (§8.1) | Responsável, 19/10/2026 (proposta S0-04) |
| D-017 | Parâmetros e tratamento de senha em `app/auth/passwords.py`: Argon2id t=3, m=64 MiB, p=4, hash 32 B, sal 16 B (T1, RFC 9106); `verify_password` aceita só hash PHC `$argon2id$` e retorna False para Argon2i/Argon2d, hash inválido ou senha que não seja str; `needs_rehash` (T2) só depois de verificação bem-sucedida; senha normalizada em **NFC** antes de contar tamanho e de gerar/verificar hash (NFC e NFD equivalentes; largura total, ligaduras e outros caracteres de compatibilidade continuam distintos); senha com caractere não codificável em UTF-8 é recusada; máximo concreto de 128 caracteres (dentro de D-016) | NIST SP 800-63B rev. 4 §3.1.1.2 recomenda (SHOULD) NFC antes do hash de senhas Unicode; NFC também evita unir caracteres visualmente diferentes. Verificação medida em ~0,09 s no laboratório, a medir na VM (P-04) | Responsável, 19/10/2026 (proposta S0-05; revisão técnica do Codex) |
| D-018 | Sessão expira após 30 minutos de inatividade ou 10 horas de duração máxima, o que ocorrer primeiro | Resolve R3 (S0-07); jornada do escritório | Responsável, 20/10/2026 |
| D-019 | Após 5 falhas de login em 15 minutos, aquele login fica bloqueado por 15 minutos; o bloqueio expira sozinho e um administrador pode desbloquear antes, com auditoria | Resolve R4 (S0-08); bloqueio permanente desaconselhado (permitiria travar o administrador) | Responsável, 20/10/2026 |
| D-020 | Operador e consulta não acessam associação com `status = 'inactive'`; administrador acessa | Resolve R5 (S0-09) | Responsável, 20/10/2026 |
| D-021 | Ninguém, inclusive administrador, altera o próprio perfil ou os próprios acessos; outro administrador pode fazer a mudança. O bootstrap (S0-06) cria a conta inicial sem ator humano anterior e não é exceção a essa regra | Resolve R6 (S0-09); complementa a proibição de autoconcessão por classificação (SPEC §8.1) | Responsável, 20/10/2026 |

## Propostas para revisão

| ID | Decisão | Motivo | Origem |
|---|---|---|---|
| D-002 | Contexto persistente: `AGENTS.md` canônico para agentes; `CLAUDE.md` importa `AGENTS.md` e só contém regras específicas do Claude Code | Uma fonte por regra (SPEC §15.3) | Sprint 0 — aguarda revisão |
| D-003 | Amostra sintética versionada em `tests/fixtures/servidor-teste/`; manifesto e README ficam fora da raiz indexável; casos não portáveis (symlink, permissão, colisão de maiúsculas, arquivo grande) são criados em tempo de teste | Raiz sem arquivos auxiliares (SPEC §5.4); checkout portável | Sprint 0 — aguarda revisão |
| D-004 | Verificação da amostra em POSIX `sh` + coreutils, sem dependência da stack | Stack ainda pendente | Sprint 0 — aguarda revisão |
| D-007 | Ferramentas do backend: Alembic com SQL explícito (sem autogenerate), psycopg 3 sem ORM no código da aplicação, pytest | Restrições e índices parciais legíveis na migração; menos camadas | S0-02 — aguarda revisão |
| D-008 | `document_sources.normalization_policy` aceita somente `exact` (chave = caminho relativo original); políticas sem distinção de maiúsculas ou Unicode entram após P-04 | Não unir arquivos distintos sem conhecer o sistema de arquivos (SPEC §7.2) | S0-02 — aguarda revisão |
| D-009 | Categoria e estado de classificação de `documents` adiados para a migração de `document_categories`; `index_errors` adiada para a tarefa do indexador | Evitar valores de domínio não definidos na SPEC | S0-02 — aguarda revisão |
| D-010 | Testes de integração só aceitam banco com sufixo `_test` em IP loopback literal, sem query string, `hostaddr`, `service` ou variáveis `PG*`; destino efetivo conferido após conectar e antes de recriar o schema | Impedir que teste toque banco real (SPEC §12) | S0-02 — aguarda revisão |
| D-012 | Perfis `administrator`, `operator`, `viewer` (administrador, operador, consulta). Login restrito a ASCII de identificador `[A-Za-z0-9._-]`, 1 a 64 caracteres, avaliado com `COLLATE "C"`; único sem distinção de maiúsculas por `lower(login COLLATE "C")`. Regra independente de `LC_CTYPE` e de normalização Unicode; nome com acento fica em `users.name` | SPEC §4.1; impede logins visualmente duplicados (NFC/NFD, confusáveis, largura total) e colisões que mudam com o locale do servidor | S0-04 — aguarda revisão |
| D-013 | `associations.cnpj` opcional, normalizado sem pontuação em 14 posições (12 alfanuméricas maiúsculas + 2 dígitos; aceita CNPJ numérico e alfanumérico), **sem unicidade** até a revisão de inconsistências do cadastro; unicidade entra em migração posterior. Dígitos verificadores ficam para a API. `status` inicial: `active`/`inactive`. Nome de associação não é único | SPEC §8 ("único após revisão de inconsistências"); situações além de ativa/inativa não definidas na SPEC | S0-04 — aguarda revisão |

## Pendentes

| ID | Questão | Opções | Bloqueia | Responsável |
|---|---|---|---|---|
| P-03 | Empacotamento | Docker Compose ou serviços nativos | Execução local e montagem do compartilhamento | Depende de P-04 |
| P-04 | Ambiente | SO do servidor de arquivos e da VM, protocolo (SMB/NFS), domínio | Leitor de origem, conta de serviço, tratamento de links e maiúsculas | Infraestrutura (SPEC §13) |
| P-05 | Ferramentas restantes | Lint/formatação Python e TypeScript; versão mínima de Python e PostgreSQL em produção | Comandos em `AGENTS.md` | Após P-04 e proposta do Codex |
| P-06 | Busca | Índice no PostgreSQL (ex.: trigram, `unaccent`) | Desempenho de pesquisa | Após medição no laboratório (SPEC §8.1) |
| P-07 | HTTPS, backup, retenção | Emissão de certificado, destino e retenção de backup | Piloto | Infraestrutura (SPEC §§6, 13) |
