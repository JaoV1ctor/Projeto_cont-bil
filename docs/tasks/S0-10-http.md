# S0-10 — Camada HTTP de autenticação (PROPOSTA PARA REVISÃO)

**Status:** proposta documental, não aprovada. Implementação não iniciada. Nada aqui é decisão até constar em `docs/DECISIONS.md`.

**Objetivo:** expor login, logout e sessão atual pela API FastAPI (D-006), reaproveitando o domínio de S0-07 a S0-09, com cookie seguro, CSRF, cabeçalhos de segurança, IP do cliente e limite por IP.

**Referências:** `PROJECT_SPEC.md` §§4.1, 6, 8, 10 (critério 6), 12; `docs/DECISIONS.md` D-005, D-006, D-012, D-017, D-018, D-019, P-04, P-07; `docs/tasks/S0-05-autenticacao-autorizacao.md` §§3 (T3–T8), 5; `docs/ARCHITECTURE.md` (fluxo 1).

**Contratos de domínio usados (já implementados):**

- `app.auth.sessions`: `login(conn, login, password, *, source_ip)` → `LoginSuccess` (token só em memória; S0-10c o estende com o login canônico de `users.login`, T10) ou `LOGIN_FAILED`; `resolve_session(conn, token)` → `SessionInfo | None`; `logout(conn, token)` → `bool`.
- `app.auth.lockout`: limite por login (D-019) já integrado em `login`; `normalize_ip` valida o IP sem ecoar a entrada.
- `app.auth.authorization`: `authorize`, `accessible_association_ids`, `AuthorizationDenied`.
- Cada função usa transação própria e exige conexão ociosa sem autocommit.

## 1. Fora do escopo

Rotas de cadastros, associações, documentos, busca ou abertura; gestão de usuários pela API; frontend; recuperação de senha, segundo fator, SSO; deploy; configuração de rede, proxy ou certificado reais; aceitar cabeçalhos de proxy (tarefa própria após P-04).

## 2. Situação das dependências e pendências

| ID | Questão | Situação / opções | Recomendação (não aprovada) | Impacto | Responsável |
|---|---|---|---|---|---|
| — | `fastapi` | Aprovado por D-006 | — | Entra em `pyproject.toml` na S0-10a | — |
| — | `httpx` | Aceito na revisão de 25/10/2026, só para `TestClient` (dependência de teste) | — | Entra em `dev` na S0-10a | — |
| R7 | Servidor ASGI `uvicorn` | Pendente | Aprovar quando a execução fora dos testes for necessária | S0-10a–e usam só `TestClient` e não dependem dele; bloqueia execução local fora dos testes e piloto | Responsável |
| R8 | Parâmetros do limite por IP | Número de falhas, janela, duração do bloqueio | Ponto de partida a calibrar: 20 falhas em 15 min bloqueiam o IP por 15 min. Maior que D-019 porque um IP pode ter vários usuários | Valor baixo bloqueia vários usuários que compartilhem IP | Responsável, após P-04 |
| R9 | Topologia de origem entre interface e API | (a) mesma origem, com proxy reverso encaminhando `/api` à API; (b) origens distintas com CORS | (a) | Esta proposta vale só para (a). (b) exige nova revisão de T12, T13 e CORS | Responsável e Infra, após P-04/P-07 |
| P-04 | Rede, proxy e domínio | Ver `docs/DECISIONS.md` | — | Até P-04, cabeçalhos de proxy desligados (T16); define o IP visto pelo limite | Infra |
| P-07 | HTTPS, certificado, retenção | Ver `docs/DECISIONS.md` | — | Cookie `Secure` e HSTS no ambiente real; retenção de tentativas por IP | Infra |
| Roles | Roles PostgreSQL separadas (SPEC §6) | Requisito, não opção | — | API e piloto não sobem sem elas | Codex/Claude no laboratório; Infra no ambiente real |

Sem P-04 e P-07, a implementação fica limitada ao laboratório (`TestClient` com URL `https://`).

## 3. Propostas técnicas (revisão do Codex)

| ID | Proposta |
|---|---|
| T10 | **Rotas** (JSON, prefixo `/api/auth`): `POST /login` (`{login, password}`; 200 com `{login, role, absolute_expires_at}` e `Set-Cookie`; 401 uniforme); `POST /logout` (204 sempre, idempotente; revoga a sessão se o cookie for válido e remove o cookie); `GET /session` (200 com `{login, role, absolute_expires_at}` ou 401). `absolute_expires_at` é o limite absoluto de 10 horas da sessão (D-018); a sessão pode expirar antes por 30 minutos de inatividade, então o campo não é a previsão do fim da sessão. O `login` do corpo vem do valor canônico de `users.login`, devolvido por `LoginSuccess` e `SessionInfo`; nunca é o texto recebido. S0-10c altera `LoginSuccess` para incluir esse valor e atualiza os testes do domínio. O token nunca vai no corpo, na URL nem em log. |
| T11 | **Identidade só da sessão:** dependência FastAPI `current_session` lê o cookie e chama `resolve_session` a cada requisição (T4). Nenhuma rota aceita `user_id`, perfil ou associação do cliente como identidade. Dependência `require(action, association_id)` chama `authorize` e responde 403 uniforme; testada com app de teste, sem rota de produto nesta tarefa. |
| T12 | **Cookie:** nome `__Host-session`; `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, sem `Domain`. Cookie de sessão do navegador (sem `Max-Age`/`Expires`); o servidor é a autoridade de expiração (D-018). Remoção no logout e em 401 por sessão inválida: mesmo nome e atributos, `Max-Age=0`. **Substituição de sessão:** em `POST /login` com cookie de sessão válido, só depois de autenticação bem-sucedida e da criação da sessão nova, a sessão anterior indicada pelo cookie é revogada. São duas transações sequenciais, não atômicas: se a revogação falhar depois da criação, a sessão nova continua válida e a falha é tratada como erro interno (T15), sem devolver o token. Falha de credenciais não revoga a sessão existente. |
| T13 | **CSRF (cenário R9(a), mesma origem, sem CORS), inclusive login e logout:** em todo método que altera estado (`POST`, `PUT`, `PATCH`, `DELETE`): (1) `Origin` obrigatório e exatamente igual à origem configurada (`API_ORIGIN`: esquema, host e porta), sem curinga; ausente, `null` ou diferente → 403 `csrf_rejected`; (2) media type do corpo `application/json` (parâmetros como `charset` ignorados na comparação); outro → 403 `csrf_rejected`; (3) `Sec-Fetch-Site`, quando presente, deve ser `same-origin`; outro valor → 403 `csrf_rejected`. `Referer` não substitui `Origin`. `SameSite=Strict` é defesa adicional, não a principal. Sem token CSRF neste cenário. Sem `CORSMiddleware`. A recusa ocorre antes de abrir conexão com o banco: não grava `audit_events`, tentativas nem sessões, e não registra o valor bruto de `Origin` em log (só o código do erro). R9(b) exige nova revisão. |
| T14 | **Cabeçalhos:** em todas as respostas, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: same-origin`; `Cache-Control: no-store` em todas as respostas de `/api/auth` e nas que dependem de sessão. `Strict-Transport-Security` só após P-07, por configuração. |
| T15 | **Entrada e erros:** corpo de requisição limitado a 4 KiB (verificado por `Content-Length` e pela leitura, também sem `Content-Length`); excesso → 413 `invalid_request`. Login: obedece integralmente D-012, `[A-Za-z0-9._-]{1,64}`; espaço, acento e qualquer outro caractere fora desse conjunto são recusados. Senha: 1 a 128 caracteres (D-017). Campos extras recusados. Entrada inválida → 422 `invalid_request`, sem banco e sem hash. Corpo de erro `{"error": "<código>"}` com códigos fixos (`login_failed`, `not_authenticated`, `forbidden`, `csrf_rejected`, `invalid_request`, `too_many_requests`, `temporarily_unavailable`, `internal_error`). Nenhum erro devolve a entrada: handler próprio para `RequestValidationError`, porque o padrão do FastAPI ecoa o valor no campo `input` (exporia a senha). Exceção não tratada → 500 genérico, sem traceback. |
| T16 | **IP do cliente até P-04:** usar somente `request.client.host` (endereço do socket), validado por `normalize_ip`. `Forwarded` e `X-Forwarded-For` são ignorados; nenhum parser próprio desses cabeçalhos e nenhum middleware de proxy. Quando houver servidor ASGI (R7), ele roda com `--no-proxy-headers` (o padrão do uvicorn aceita esses cabeçalhos de `127.0.0.1`; conferir na documentação da versão adotada). Proxy real fica para tarefa própria após P-04. |
| T17 | **Limite por IP, separado de D-019:** migração `0007` com `ip_login_attempts` (`seq` identity, IP `inet`, data, resultado `failure`/`success`/`blocked`; sem texto de login nem `user_id`) e `ip_login_blocks` (IP, `locked_until`, `trigger_attempt_seq`). Login desconhecido conta como falha do IP sem gravar o texto digitado. Ordem transacional dentro de `login`: READ COMMITTED (S0-07); trava por IP com `pg_advisory_xact_lock` (chave registrada em `app/db_locks.py`, derivada do IP normalizado; colisão só serializa); trava do usuário depois (ordem fixa IP → usuário, sem deadlock). IP bloqueado: grava `blocked`, responde 429 `too_many_requests` antes da busca do usuário (não revela existência de conta) e não estende o bloqueio. Caso contrário, segue o login e grava o resultado no mesmo commit; a falha que atinge R8 cria o bloqueio e o evento `auth.ip_block`. Sucesso não zera a contagem do IP (uma conta válida não pode liberar tentativas contra outras). Bloqueio expira sozinho. Falhas com `seq <= trigger_attempt_seq` do último bloqueio do IP não contam para um novo bloqueio: depois da expiração começa nova contagem e não ocorre rebloqueio imediato por falhas já consumidas. Retenção das linhas depende de P-07. |
| T18 | **Auditoria:** reaproveitar `auth.login`, `auth.logout`, `auth.lockout`, `auth.revoke_sessions` e `authz.*` sem mudar formato. Novo evento proposto: `auth.ip_block` (ator de serviço, IP normalizado em `details`). Cada login processado, cada logout que efetivamente revoga uma sessão e cada bloqueio por IP geram o evento aplicável. Logout sem cookie, com cookie inválido ou repetido continua 204 e não exige evento novo. Recusas CSRF (T13), de entrada (T15) e por excesso de verificações (T21) não geram `audit_events`. Nunca senha, token, cookie ou segredo. |
| T19 | **Roles PostgreSQL (SPEC §6):** somente autenticação, autorização e API rodam com a role da aplicação. Migrações rodam com a role de migração, dona do schema, que executa Alembic. A role da aplicação não é dona de nada, não tem DDL e não tem `CREATE` efetivo no schema nem `TEMPORARY` efetivo no banco. `TEMPORARY` pode vir de `PUBLIC`; sua revogação é responsabilidade do provisionamento do banco (laboratório: preparação do teste; ambiente real: Infra), e o script de privilégios continua sem criar roles. Privilégios aplicados por script SQL versionado e idempotente (`REVOKE ALL` seguido de `GRANT` explícitos), executado pela role de migração depois das migrações. Sem `GRANT` dentro de migração e sem `ALTER DEFAULT PRIVILEGES`: tabela nova fica sem acesso até entrar na matriz. Matriz proposta para a role da API: `USAGE` no schema; `audit_events` `INSERT`, `SELECT`; `sessions` `SELECT`, `INSERT`, `UPDATE`; `users` `SELECT` e `UPDATE` só nas colunas usadas (`password_hash`, `role`, `updated_at`; também necessário para `FOR NO KEY UPDATE`); `associations` `SELECT`; `user_associations` `SELECT`, `INSERT`, `DELETE`; `login_attempts` `SELECT`, `INSERT`; `login_lockouts` `SELECT`, `INSERT`, `UPDATE`; `ip_login_attempts` `SELECT`, `INSERT`; `ip_login_blocks` `SELECT`, `INSERT`, `UPDATE`; tabelas do catálogo e do indexador (`documents`, `document_sources`, `index_runs`, `index_errors`) sem acesso. Os testes existentes de catálogo e indexador continuam rodando separados, com a role atual, até terem roles próprias; não se concede a eles acesso pela role da API. Sequences: nenhuma por padrão; `USAGE` só se o teste mostrar necessário para identity. Indexador e bootstrap (`app.admin`) ficam fora desta matriz e terão role definida em tarefa própria. |
| T20 | **Conexão:** fábrica/provedor injetável, sem pool nesta tarefa (pool seria dependência nova). Resolver a fábrica como dependência do FastAPI não abre conexão. A rota abre no máximo uma conexão, somente depois de CSRF (T13), limite de corpo e validação do modelo (T15) e aquisição do semáforo (T21), e a fecha em `finally`. Rotas síncronas (`def`), executadas no threadpool. |
| T21 | **Verificações Argon2id simultâneas:** semáforo por processo, com limite configurável (`LOGIN_MAX_CONCURRENT_VERIFICATIONS`). Laboratório: 1. Produção: definir após P-04 (memória da VM; 64 MiB por verificação, D-017). Aquisição sem espera, depois de CSRF e validação e antes de abrir conexão: excesso → 503 `temporarily_unavailable`, uniforme, sem transação, sem hash, sem gravar tentativa. Aplica-se só a `POST /login`. |

## 4. Subtarefas (ordem proposta)

Cada uma é entregue e revisada antes da seguinte. Nenhuma depende de `uvicorn`.

| Ordem | Tarefa | Entrega | Depende de |
|---|---|---|---|
| 1 | S0-10a | `fastapi` e `httpx` (teste) no `pyproject.toml`; app FastAPI (fábrica `create_app`), configuração, T14, T15, fábrica de conexão T20 (sem abrir conexão ao ser resolvida). Sem rotas de produto | Aprovação desta proposta |
| 2 | S0-10b | Roles no laboratório (T19): script de privilégios, preparação do banco de teste com role de migração e revogação de `TEMPORARY` no provisionamento; só os testes de autenticação, autorização e API rodam com a role da aplicação; testes de catálogo e indexador continuam separados | S0-10a |
| 3 | S0-10c | Rotas de T10, `LoginSuccess` com login canônico (e testes do domínio), cookie e substituição de sessão T12, identidade T11, CSRF T13, validação de login D-012 (T15) e limite T21, juntos (login nunca sem CSRF) | S0-10a, S0-10b |
| 4 | S0-10d | IP do socket T16, com testes de cabeçalhos de proxy ignorados | S0-10c |
| 5 | S0-10e | Limite por IP T17 (inclusive não recontagem após bloqueio), migração `0007`, linhas novas na matriz T19, auditoria T18 (`auth.ip_block`) | S0-10d, R8 |
| — | Execução fora dos testes | Servidor ASGI | R7 |
| — | Ativação real | Proxy confiável, HTTPS/HSTS, limite por IP e concorrência no ambiente real | P-04, P-07, confirmação do responsável |

## 5. Critérios de aceite e testes

PostgreSQL de teste conforme D-010; banco preparado pela role de migração; testes de autenticação, autorização e API executados com a role da aplicação (catálogo e indexador seguem separados, T19); relógio injetado (T8); `TestClient` com `https://`. Sem rede real.

1. **Login:** sucesso devolve 200, cookie com todos os atributos de T12 e corpo sem token, com `login` igual ao valor de `users.login` (não ao texto enviado) e `absolute_expires_at`. Login inexistente, inativo, senha errada e bloqueado por D-019 devolvem 401 idênticos (status, corpo, cabeçalhos), sem `Set-Cookie`.
2. **Sessão:** `GET /session` com cookie válido devolve o estado atual (T4); usuário desativado ou com perfil alterado no banco reflete na próxima chamada. Cookie ausente, expirado (inatividade e vida máxima), revogado ou malformado → 401 e remoção do cookie.
3. **Logout:** revoga e remove o cookie; repetir devolve 204; o token antigo deixa de resolver.
   **Substituição de sessão:** login com cookie válido e credenciais corretas cria sessão nova e revoga a anterior (token anterior deixa de resolver); credenciais inválidas não revogam a sessão existente.
4. **Identidade:** `user_id`, perfil ou outro identificador enviados por corpo, query ou cabeçalho são recusados (campos extras) ou ignorados; `require` nega associação não autorizada com 403 e corpo uniforme.
5. **CSRF:** login e logout com `Origin` ausente, `null` ou diferente, com `Sec-Fetch-Site` diferente de `same-origin`, ou com media type diferente de JSON → 403 `csrf_rejected` sem nenhum efeito no banco: nenhuma linha nova em `sessions`, `login_attempts`, `login_lockouts`, `ip_login_attempts`, `ip_login_blocks` ou `audit_events`. O valor bruto de `Origin` não aparece em log capturado.
6. **Entrada:** corpo acima de 4 KiB → 413; login acima de 64 ou senha acima de 128 caracteres, campo ausente, vazio ou extra → 422; login com espaço, acento ou caractere ASCII não permitido por D-012 → 422 `invalid_request`; nenhum toca o banco nem calcula hash; nenhum corpo de erro contém a entrada. A fábrica de conexão instrumentada registra zero chamadas nas recusas de CSRF (T13), de entrada (T15) e de T21.
7. **Cabeçalhos:** todas as respostas, inclusive erros, têm T14; HSTS ausente enquanto desligado.
8. **Vazamento:** senha, token e valor do cookie não aparecem em corpo de erro, 422, logs capturados, `audit_events`, `sessions` ou exceções. Teste com senha marcadora e varredura de tudo isso.
9. **IP:** o IP registrado é sempre o do socket; `X-Forwarded-For` e `Forwarded`, com qualquer valor, não o alteram.
10. **Limite por IP:** começa e expira exatamente nos parâmetros de R8; login desconhecido conta sem gravar o texto digitado; sucesso não zera a contagem; bloqueio de IP não cria bloqueio de login e vice-versa; IP bloqueado responde 429 sem buscar o usuário; após a expiração, falhas com `seq <= trigger_attempt_seq` não contam e o IP não é rebloqueado imediatamente; nova contagem começa do zero.
11. **Concorrência:** requisições paralelas do mesmo IP no limite não ultrapassam R8; tentativas paralelas no limite de D-019 não o ultrapassam. Estes testes chamam o domínio diretamente ou configuram T21 acima de 1, para não serem barrados pelo semáforo.
12. **Verificações simultâneas (T21):** com limite 1 e uma verificação em andamento, nova tentativa recebe 503 `temporarily_unavailable` sem abrir conexão (fábrica instrumentada), sem transação, sem verificar hash e sem gravar tentativa.
13. **Roles:** a role da aplicação recebe erro de privilégio em `UPDATE`, `DELETE` e `TRUNCATE` de `audit_events`, em DDL persistente e em tabelas fora da matriz; `CREATE TEMP TABLE` falha; privilégios efetivos (`has_schema_privilege`, `has_database_privilege`) confirmam ausência de `CREATE` no schema e de `TEMPORARY` no banco; não é dona de nenhum objeto do schema; `INSERT` e `SELECT` em `audit_events` funcionam. Toda tabela do schema tem entrada explícita na matriz (teste falha com tabela nova sem entrada). O script de privilégios aplicado duas vezes dá o mesmo resultado.
14. **Auditoria:** cada login processado, cada logout que efetivamente revoga uma sessão e cada bloqueio por IP gera o evento de T18 com ator, ação, alvo, resultado e data; logout ausente, inválido ou repetido devolve 204 sem evento novo; recusas de CSRF, entrada e T21 não geram evento.

## 6. Riscos

- Sem P-04, o IP do socket pode ser o de um proxy e o limite por IP pode bloquear vários usuários juntos. Por isso o limite fica desligado no ambiente real até P-04 e confirmação.
- A trava por IP serializa logins do mesmo IP durante o Argon2id; aceitável no volume previsto, a medir no piloto.
- `SameSite=Strict` e a verificação de `Origin` valem só para R9(a). R9(b) exige nova revisão.
- Com T21 = 1, logins simultâneos legítimos recebem 503 e precisam repetir; o valor de produção depende de P-04.
- Falhas recusadas por T21 não contam no limite por IP; o semáforo limita o custo, não as tentativas.
- O semáforo é por processo; com vários processos, o limite efetivo multiplica.
- As tabelas de tentativas por IP crescem; retenção depende de P-07.
- Indexador, bootstrap e testes de catálogo e indexador continuam sem role própria até tarefa específica.
- A substituição de sessão (T12) não é atômica: uma falha entre a criação da sessão nova e a revogação da anterior deixa as duas válidas até a anterior expirar ou ser revogada.
