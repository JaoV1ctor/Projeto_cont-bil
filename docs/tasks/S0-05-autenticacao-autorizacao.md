# S0-05 a S0-10 — Autenticação e autorização (PROPOSTA)

**Status:** plano aprovado na revisão como proposta. Cada tarefa só começa depois de aprovadas as decisões da seção 2 de que depende.

| Tarefa | Situação |
|---|---|
| S0-05 | Implementada (`backend/app/auth/passwords.py`). R1 e R2 aprovados pelo responsável (D-015, D-016). Revisão técnica do Codex concluída em 19/10/2026, após correção de bloqueadores (Argon2id exclusivo, NFC, `app.auth` no pacote, entrada inválida retorna False) |
| S0-06 | Implementada (`backend/app/admin.py`, `backend/app/db_locks.py`, migração `0004`). D-014 e D-017 aprovados pelo responsável em 19/10/2026. Revisão técnica do Codex concluída, incluindo a correção de isolamento |
| S0-07 | Implementada (`backend/app/auth/sessions.py`, migração `0005`). R3 aprovada pelo responsável em 20/10/2026 (D-018). Revisão técnica do Codex concluída, incluindo a correção de concorrência do login |
| S0-08 | Implementada (`backend/app/auth/lockout.py`, integração em `sessions.login`, migração `0006`). R4 aprovada pelo responsável em 20/10/2026 (D-019). Revisão técnica do Codex concluída, incluindo as correções de ordem por sequência e de trava do ator no desbloqueio |
| S0-09 | Implementada (`backend/app/auth/authorization.py`). R5 e R6 aprovadas pelo responsável em 20/10/2026 (D-020, D-021). Revisão técnica do Codex concluída sem bloqueios |
| S0-10 | Detalhada para revisão em `docs/tasks/S0-10-http.md`; implementação não iniciada |

**Objetivo:** dividir login e autorização em tarefas pequenas e ordenadas. As cinco primeiras ficam só na camada de domínio, sem HTTP; a última expõe tudo pela API.

**Referências:** `PROJECT_SPEC.md` §§4.1, 6, 8 (`user_associations`, `document_suggestions`), 8.1, 10 (critério 6), 12; `docs/DECISIONS.md` D-006, D-011, D-012, D-014; esquema `0003` (S0-04).

| Ordem | Tarefa | Entrega | Depende de |
|---|---|---|---|
| 1 | S0-05 | Hash e política de senha (sem migração) | R1, R2 |
| 2 | S0-06 | Bootstrap do primeiro administrador, atômico, com auditoria da criação | S0-05 |
| 3 | S0-07 | Primeiro login, sessões e auditoria de autenticação | S0-06, R3 |
| 4 | S0-08 | Limite de tentativas por login | S0-07, R4 |
| 5 | S0-09 | Autorização por associação | S0-07, R5, R6 |
| 6 | S0-10 | Rotas HTTP, cookies, CSRF, IP confiável e limite por IP | S0-08, S0-09, P-04 (rede/proxy) |

Numeração anterior: HTTP estava reservado para S0-06 e depois para S0-09. Passa para S0-10.

## 1. Já definido na SPEC (não reabrir)

- Contas individuais, ativação/desativação e encerramento de sessão (§4.1).
- Perfis (§4.1; identificadores em D-012):
  - Administrador gerencia contas, permissões, raízes autorizadas e execução da indexação. Tem acesso global às associações, que é auditado (§8 `user_associations`).
  - Operador mantém cadastros, vínculos e pendências nas associações autorizadas.
  - Consulta lista, pesquisa e abre documentos das associações autorizadas.
- Acesso a associação é concedido explicitamente (§4.1). A mesma autorização vale para busca, dashboard e abertura (§4.1). Usuário sem permissão não obtém documentos, resultados, contagens ou metadados restritos, nem chamando a API diretamente (§10 critério 6; §8.1).
- Documentos sem associação ficam numa fila restrita a administradores (§4.1).
- Vínculo a outra associação exige permissão no destino. Usuário não pode se conceder acesso por classificação (§8.1). Sugestão não concede acesso (§8 `document_suggestions`).
- Senha com algoritmo apropriado, sessão com expiração, cookies seguros, proteção contra tentativas repetidas e contra CSRF quando aplicável (§6).
- Auditar autenticação e mudanças de permissão com ator, ação, alvo, resultado e data. Nunca registrar senha (§6).
- Segredos fora do Git e dos logs. Processamento local, sem provedor externo de identidade (§§2.1, 6).
- Testes de autorização com casos negativos em PostgreSQL de teste (§12).
- O banco guarda só `password_hash` não branco, sem validar formato (D-011).

## 2. Decisões do responsável

Só o que depende de escolha do escritório ou de aprovação exigida pelo AGENTS.md. Cada item traz uma recomendação, que não está aprovada.

| ID | Questão | Recomendação | Tarefa |
|---|---|---|---|
| R1 | Adicionar a dependência `argon2-cffi` (hash Argon2id, confirma D-011). O AGENTS.md exige aprovação para dependência nova | Aprovar. Alternativa sem dependência: `hashlib.scrypt`, que troca D-011 | S0-05 |
| R2 | Tamanho mínimo da senha | 15 caracteres (login só com senha), sem regras de composição, máximo de pelo menos 64. Referência: NIST SP 800-63B rev. 4, a confirmar. Alternativa: 12 | S0-05 |
| R3 | Tempos de sessão | Expira após 30 min sem uso e após 10 h no total | S0-07 |
| R4 | Bloqueio por tentativas | Após 5 falhas em 15 min, bloqueio temporário de 15 min daquele login. Expira sozinho; administrador pode desbloquear antes, com auditoria. Bloqueio permanente é desaconselhado: permite que terceiros travem o administrador | S0-08 |
| R5 | Associação `inactive` | Operador e consulta não acessam; administrador acessa | S0-09 |
| R6 | Autoconcessão em geral (além da proibição por classificação, §8.1): um usuário pode alterar o próprio perfil ou os próprios acessos? | Proibir para todos, inclusive administrador. Mudanças na própria conta exigem outro administrador. O bootstrap (S0-06) não é exceção a essa regra: cria a conta inicial sem ator humano anterior (`created_by` NULL, D-014) e não dá ao administrador criado permissão para alterar depois o próprio perfil ou os próprios acessos | S0-09 |

## 3. Propostas técnicas (revisão do Codex; não exigem escolha do responsável)

| ID | Proposta | Tarefa |
|---|---|---|
| T1 | Argon2id com ponto de partida m=64 MiB, t=3, p=4 (segunda opção da RFC 9106), mínimo m=19 MiB, t=2, p=1 (OWASP). Custo ajustado por medição no laboratório e depois na VM (P-04) | S0-05 |
| T2 | Rehash no login bem-sucedido quando os parâmetros mudarem | S0-05 |
| T3 | Sessão no servidor (tabela `sessions`). Token opaco aleatório de 32 bytes; o banco guarda só o SHA-256. Sem JWT | S0-07 |
| T4 | A cada resolução de sessão, recarregar do banco o estado atual do usuário (ativo, perfil). Autorização sempre consulta `user_associations` atual. Não manter perfil nem acessos em cache dentro da sessão | S0-07, S0-09 |
| T5 | Revogação explícita (`revoked_at`) só pelas funções de domínio: `logout` e `revoke_user_sessions`. Futuras funções que desativam usuário ou mudam perfil chamam `revoke_user_sessions` | S0-07 |
| T6 | Primeiro administrador por comando local `python -m app.admin create-first-admin`, só quando não existe administrador. Senha lida do terminal, nunca de argumento ou variável de ambiente | S0-06 |
| T7 | Falhas de login com resposta externa uniforme e caminho de processamento comparável: uma busca de usuário, uma verificação Argon2id (hash fictício para login inexistente, inativo ou bloqueado) e um registro de tentativa. Sem promessa de tempo idêntico | S0-07, S0-08 |
| T8 | Relógio injetável nos testes; nenhum `sleep` real | S0-07, S0-08 |
| T9 | Bootstrap atômico numa única transação: `pg_advisory_xact_lock` com chave fixa do bootstrap, depois verificação de que não existe administrador, inserção do usuário e evento de auditoria. Execução concorrente espera o lock, vê o administrador criado e recusa. Alternativa: transação `SERIALIZABLE` com nova tentativa | S0-06 |

## 4. Tarefas

### S0-05 — Hash e política de senha

- **Escopo:** `backend/app/auth/passwords.py` (`hash_password`, `verify_password`, `needs_rehash`, `validate_password_policy`), `pyproject.toml` (dependência R1), `backend/tests/test_auth_passwords.py`. Sem migração e sem banco.
- **Fora:** usuários, sessões, login, HTTP.
- **Aceite:**
  1. O hash usa o algoritmo de R1 e os parâmetros de T1; o formato é PHC.
  2. A verificação aceita a senha correta e recusa senha errada, hash corrompido e hash vazio, sem lançar exceção não tratada.
  3. `needs_rehash` é verdadeiro para hash com parâmetros antigos e falso para os atuais.
  4. A política aplica R2 e recusa senha vazia ou só com espaços.
  5. A senha não aparece em `repr`, exceção ou log capturado.
- **Testes:** unidade, com parâmetros reduzidos só em teste e os padrões de produção conferidos à parte.

### S0-06 — Bootstrap do primeiro administrador

- **Escopo:**
  - migração `0004`: `audit_events` mínima (ator, ação, alvo, resultado, data, detalhes sanitizados);
  - `backend/app/admin.py` (T6, T9);
  - testes de integração.
- **Auditoria:** criação do primeiro administrador, com resultado de sucesso ou de recusa. Ator registrado como serviço/bootstrap, pois não há ator humano anterior.
- **Fora:** login, sessões, gestão de outros usuários, HTTP.
- **Aceite:**
  1. `0004` aplica e reverte; a suíte existente continua passando.
  2. Com banco sem administrador, o comando cria um usuário `administrator` ativo, com `created_by` NULL e hash gerado por S0-05.
  3. Com administrador existente, o comando recusa e não altera `users`.
  4. Concorrência: duas ou mais execuções simultâneas em conexões distintas, sincronizadas para competir pela criação, resultam em exatamente um administrador e um evento de sucesso; as demais recusam com auditoria (T9).
  5. A senha não é aceita por argumento nem por variável de ambiente, e não aparece em `users`, `audit_events`, logs capturados ou exceções.
  6. O evento de criação tem ator, ação, alvo, resultado e data.
- **Escolhas de implementação (para revisão; não são decisões aprovadas):**
  - `audit_events`: ator `user` (FK) ou `service` (nome), ação em `dominio.verbo`, alvo tipo+id, resultado `success`/`denied`/`failure`, `details` jsonb objeto; trigger recusa `UPDATE`/`DELETE`.
  - Chave do lock registrada em `app/db_locks.py` (`FIRST_ADMIN_BOOTSTRAP`); toda chave nova entra nesse registro.
  - "Já existe administrador" considera também administradores inativos.
  - Login ou nome recusado pelo cadastro gera evento `failure` sem dados de entrada além do motivo.
  - Senha só por `getpass` em terminal interativo; stdin que não é TTY é recusado.
  - Isolamento exigido: READ COMMITTED. `bootstrap_first_admin` executa `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` como primeiro comando, confere com `SHOW transaction_isolation` e só depois adquire o lock. Isso vale também quando o padrão da sessão/servidor ou do psycopg é REPEATABLE READ ou SERIALIZABLE. Correção da revisão: antes, em REPEATABLE READ, a execução que esperou o lock usava um snapshot anterior e criava um segundo administrador.

### S0-07 — Primeiro login, sessões e auditoria de autenticação

- **Escopo:**
  - migração `0005`: `sessions` (usuário FK RESTRICT, `token_hash` único, criada, último uso, expira, revogada);
  - `backend/app/auth/sessions.py`: `login`, `resolve_session`, `logout`, `revoke_user_sessions`;
  - testes de integração.
- **Auditoria de autenticação:** login com sucesso, login com falha, logout e revogação, em `audit_events` (S0-06).
- **Fora:** bloqueio por tentativas (S0-08), autorização (S0-09), HTTP (S0-10), auditoria de cadastros.
- **Aceite:**
  1. `0005` aplica e reverte; a suíte existente continua passando.
  2. O banco guarda só o hash do token. Token e senha não aparecem em `sessions`, `audit_events`, logs capturados ou exceções.
  3. A sessão expira por inatividade e por vida máxima (R3), verificada com relógio injetado.
  4. `logout` e `revoke_user_sessions` fazem a sessão deixar de resolver.
  5. Usuário desativado ou com perfil alterado diretamente no banco: a sessão existente passa a refletir o estado atual na próxima resolução. Inativo não resolve; perfil novo é retornado (T4). A sessão não é marcada como revogada, e o teste verifica isso.
  6. Login inexistente, usuário inativo e senha errada retornam o mesmo resultado externo e passam pelos mesmos passos de T7 (o teste conta as chamadas de verificação de hash). Nenhum teste mede ou exige tempo igual.
  7. Cada evento de autenticação é gravado com ator, ação, alvo, resultado e data.
  8. Rehash (T2): `needs_rehash` só é chamado depois de `verify_password` retornar True para o mesmo hash, e só então o hash é regravado. Teste: hash inválido ou senha errada nunca regravam `password_hash`, mesmo com `needs_rehash` True.
- **Escolhas de implementação (para revisão; não são decisões aprovadas):**
  - Token: `secrets.token_urlsafe(32)`. `sessions.token_hash` guarda SHA-256 em `bytea` de 32 bytes. `expires_at` = criação + 10 h; a inatividade é calculada de `last_used_at`. A sessão expira exatamente em 30 min / 10 h (limite exclusivo).
  - Cada função (`login`, `resolve_session`, `logout`, `revoke_user_sessions`) usa transação própria e exige conexão ociosa sem autocommit.
  - Login sem distinção de maiúsculas (`lower(login COLLATE "C")`, igual ao índice de S0-04). Login que não é `str` vira busca vazia.
  - Falha de login: evento `auth.login`/`failure`, ator de serviço `authentication`, alvo = usuário quando existe, `details.reason` em `unknown_login`/`inactive`/`wrong_password`. O texto digitado como login não é gravado: pode ser uma senha digitada no campo errado.
  - Hash fictício para T7: Argon2id gerado uma vez por conjunto de parâmetros e mantido em cache no processo. A primeira falha com login inexistente paga um hash a mais.
  - Rehash por compare-and-set (`WHERE password_hash = antigo`). Senha antiga fora da política atual autentica, mas não é regravada.
  - `revoke_user_sessions` exige exatamente um ator (usuário ou serviço) e audita `auth.revoke_sessions` com a contagem.
  - Ordem transacional do login com alterações em `users`: o primeiro comando da transação é `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` (conferido com `SHOW`), antes da busca. A busca trava a linha do usuário com `FOR NO KEY UPDATE` até o commit do login (sessão e auditoria). Alteração de senha ou de `active` confirmada antes da trava é lida pelo login na versão atual. Alteração iniciada depois espera o commit do login. Vale também quando o padrão da conexão é REPEATABLE READ ou SERIALIZABLE.

### S0-08 — Limite de tentativas por login

- **Escopo:** migração `0006` (`login_attempts`: usuário, resultado, data; IP opcional, só armazenado; `login_lockouts`), integração com `login`, desbloqueio pelo administrador com auditoria, testes.
- **Tensão resolvida (proposta técnica, para revisão):** contar por login × não gravar texto de login desconhecido, que pode ser uma senha digitada no campo errado. Escolha: tentativas contadas por `user_id`, só para usuários existentes. Login desconhecido não gera linha em `login_attempts`, e seu texto não é gravado em nenhuma tabela, nem na auditoria. Não há bloqueio para login inexistente. O resultado externo é igual (bloqueado e inexistente retornam o mesmo `LOGIN_FAILED`), mas o processamento difere: usuário existente grava `login_attempts` e consulta bloqueio/contagem; login desconhecido não. Essa diferença pode ser medível por tempo, embora pequena perto do Argon2id. Alternativa descartada: HMAC do login com segredo do servidor, que contaria também logins inexistentes, mas exige gestão de segredo e ainda guarda um derivado da senha digitada por engano.
- **Fora:** limite por IP, que depende de IP confiável e vai para S0-10.
- **Aceite:**
  1. O bloqueio começa exatamente na tentativa definida em R4 e expira no tempo de R4 (relógio injetado).
  2. Login bloqueado com senha correta não autentica e tem o mesmo resultado externo das demais falhas (T7).
  3. Tentativas simultâneas no limite não ultrapassam R4: o teste usa conexões paralelas e verifica a contagem.
  4. Bloqueio e desbloqueio geram auditoria; a senha nunca é registrada.
  5. `0006` aplica e reverte.
- **Escolhas de implementação (para revisão; não são decisões aprovadas):**
  - Contam falhas (`failure`) na janela de horário (agora − 15 min, agora] que vêm depois, na ordem transacional, do último sucesso, da falha que iniciou o último bloqueio e do último desbloqueio. A ordem usa `login_attempts.seq` (identity), não horários: com relógio fixo, 5 falhas posteriores a um sucesso ou desbloqueio atingem R4. `login_lockouts.trigger_attempt_seq` guarda a falha que bloqueou; `unlocked_after_seq` guarda a última tentativa no desbloqueio. A 5ª falha cria `login_lockouts` (`locked_until` = agora + 15 min) e o evento `auth.lockout`.
  - Durante o bloqueio, a tentativa é gravada como `blocked`, não conta e não estende o bloqueio. O login ainda executa busca e verificação Argon2id (T7); evento `auth.login`/`failure` com `reason: locked`.
  - Falha de usuário inativo também conta.
  - A contagem ocorre com a linha do usuário travada (`FOR NO KEY UPDATE`, ordem da S0-07): tentativas simultâneas do mesmo usuário ficam em série e não ultrapassam R4.
  - `unlock_user` exige ator administrador ativo (senão, evento `denied`) e grava `auth.unlock` com `{"unlocked": bool}`. Ordem transacional: READ COMMITTED; trava ator e alvo com `FOR NO KEY UPDATE`, em ordem de id (sem deadlock entre desbloqueios cruzados), antes de ler perfil/ativo do ator. Desativação ou rebaixamento do ator confirmados antes da trava recusam o desbloqueio; mudança iniciada depois espera o commit. O login trava só o alvo.
  - `source_ip` é validado com `ipaddress` e só armazenado. A mensagem de erro não ecoa a entrada.
  - Usuário existente executa `INSERT` em `login_attempts` e consultas de bloqueio/contagem que login desconhecido não executa. A diferença de processamento é pequena perto do Argon2id, mas existe e pode ser medível.

### S0-09 — Autorização por associação

- **Escopo:** `backend/app/auth/authorization.py`, com `authorize(conn, user_id, action, association_id)` e `accessible_association_ids(conn, user_id)`. Funções de domínio para conceder e remover acesso, aplicando R6 e auditando. Testes.
- **Fora:** filtragem de documentos e vínculos (entra com a busca), gestão de usuários pela API, HTTP.
- **Aceite:**
  1. Testes de concessão e de negativa para cada combinação: perfil × ação (ler, alterar, gerenciar acessos) × associação (autorizada, não autorizada, inativa conforme R5) × usuário (ativo, inativo). Cada caso tem o resultado esperado explícito, e `accessible_association_ids` concorda com `authorize`.
  2. Remoção de acesso tem efeito na próxima chamada, sem revogar sessão (T4). Inclui remoção feita diretamente no banco.
  3. O acesso global do administrador gera auditoria.
  4. A concessão aplica R6: usuário (inclusive administrador) alterando o próprio perfil ou os próprios acessos é recusado, com auditoria do resultado. Outro administrador consegue fazer a mesma mudança.
  5. Operador e consulta sem linha em `user_associations` recebem negativa mesmo quando existem documentos, sugestões ou mapeamentos da associação no banco de teste (§8.1). Esses dados entram nos testes quando as tabelas existirem.
- **Item de revisão de código (não comprovado por teste comportamental):** `authorize` e `accessible_association_ids` consultam só `users` (ativo, perfil), `associations` (situação) e `user_associations`; nenhuma consulta a sugestões, classificação ou vínculos de documento. Verificado na revisão do diff. Um teste estático (`test_authorization_source_reads_only_allowed_tables`) lista as tabelas em `FROM`/`JOIN` dessas funções como apoio, mas não substitui a revisão.
- **Escolhas de implementação (para revisão; não são decisões aprovadas):**
  - Ações: `read`, `write`, `manage_access`. Matriz: administrador tudo em associação existente, inclusive inativa; operador `read`/`write` em associação autorizada e ativa; consulta só `read` nela; usuário inativo ou inexistente nada. `accessible_association_ids(user, action)` devolve exatamente as associações em que `authorize(user, action, ·)` é True.
  - Acesso global do administrador gera `authz.global_access` a cada `authorize` (alvo: associação) e a cada `accessible_association_ids` (alvo nulo, `scope: all`, contagem). Negativas de leitura não são auditadas.
  - `grant_access`, `revoke_access` e `change_role`: só administrador ativo, nunca sobre si mesmo (D-021). Ordem transacional igual à do desbloqueio: READ COMMITTED; trava ator e alvo em ordem de id (`lock_users`) antes de ler o perfil do ator. Recusa gera `denied` com `reason` (`actor_not_admin`, `self_change`) e lança `AuthorizationDenied`.
  - `grant_access` é idempotente (`ON CONFLICT DO NOTHING`, `created: bool`) e grava `created_by`. Conceder acesso a associação inativa é permitido; só vale se ela for reativada.
  - `change_role` revoga as sessões abertas do alvo na mesma transação (T5), via `revoke_open_sessions_in_transaction`. Remoção de acesso não revoga sessão (T4).
  - Ajuste em código já aprovado, sem mudança de comportamento: `lock_users` passou para `app/auth/transactions.py` (`lockout._lock_users` virou alias); `revoke_user_sessions` usa a nova `revoke_open_sessions_in_transaction`.

### S0-10 — HTTP (resumo)

Rotas FastAPI de login/logout. Cookie `HttpOnly`/`Secure`/`SameSite` e CSRF (§6). Obtenção confiável do IP: proxies confiáveis configurados, sem aceitar `X-Forwarded-For` arbitrário. Limite por IP só depois disso. Cabeçalhos de segurança. Precisa de decisão de rede e proxy (P-04/P-07). Detalhamento (proposta para revisão): `docs/tasks/S0-10-http.md`.

## 5. Restrições comuns

**Condição para a futura API (S0-10) e para o piloto:** a role usada pela aplicação não é dona de `audit_events` e não tem `UPDATE`, `DELETE` nem `TRUNCATE` nela (só `INSERT` e `SELECT`). O trigger `audit_events_append_only` (0004) não protege contra o dono da tabela nem contra `TRUNCATE`/`DROP`. Até existir separação de roles, ele não é proteção suficiente.

- Somente laboratório: dados fictícios, PostgreSQL descartável conforme `tests/db_guard.py`. Sem servidor real, credenciais reais ou deploy.
- Nenhuma tarefa aprova decisão. Ao implementar, registrar em `docs/DECISIONS.md` só o que o responsável aprovou (R*) e o que o Codex aceitou (T*).
- Sem frontend, recuperação de senha, segundo fator ou SSO/LDAP/AD.

## 6. Riscos

- O custo de memória do Argon2id com logins simultâneos pode pesar na VM. Medir antes do piloto (T1).
- Bloqueio por login permite bloqueio temporário provocado por terceiros. O limite por IP, que reduz o abuso, só chega em S0-10.
- T4 adiciona uma consulta por resolução de sessão. É aceitável no volume previsto, mas deve ser medido no piloto.
- Mudanças diretas no banco não revogam sessões. Só têm efeito pelo que T4 recarrega (ativo, perfil, acessos).
- O advisory lock de T9 só protege execuções do comando de bootstrap. Inserção direta de administrador no banco fica fora dessa garantia.
