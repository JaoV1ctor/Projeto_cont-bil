# Memória operacional do projeto

Atualizada em 27/10/2026. Ponto de retomada, não fonte de requisitos ou decisões. Em caso de diferença, consultar `PROJECT_SPEC.md`, `docs/DECISIONS.md` e `docs/tasks/`.

## Estado confirmado

- Stack aprovada: Next.js/TypeScript só na interface; backend FastAPI/Python, indexador Python separado e PostgreSQL local (D-005/D-006).
- Laboratório e backend de domínio implementados até S0-09: catálogo, indexador read-only de laboratório, usuários, hash de senha, primeiro administrador, sessões, limite por login e autorização por associação. As migrações vão de `0001` a `0006`.
- Codex concluiu a revisão técnica da S0-09 sem bloqueios; o quadro de `docs/tasks/S0-05-autenticacao-autorizacao.md` já registra isso.
- Índice operacional de pendências: `PENDENCIAS.md` (raiz). Este arquivo mantém só o ponto de retomada.
- S0-10 está detalhada em `docs/tasks/S0-10-http.md`. A segunda revisão documental do Codex confirmou as correções anteriores, mas encontrou três ajustes restantes: impedir atributos elevados e associação da role da aplicação a roles privilegiadas; eliminar a contradição entre T11 e T20 sobre quem abre a conexão; definir a auditoria de requisições recusadas por bloqueio de IP. A proposta ainda não está aprovada e a implementação não foi iniciada. Não há API HTTP nem frontend.
- Último teste PostgreSQL relatado pelo Claude para S0-09: `426 passed` em PostgreSQL 17 descartável. Codex conferiu sintaxe e a amostra sintética de 55 arquivos, mas não reexecutou essa suíte. Confirmar novamente após mudanças.
- Repositório passou a ser versionado em Git e publicado no remoto `https://github.com/JaoV1ctor/Projeto_cont-bil.git` em 27/10/2026. Não houve acesso ao servidor real nem deploy.

## Pendências que orientam o trabalho

1. Claude corrigir somente `docs/tasks/S0-10-http.md` conforme os três achados da segunda revisão. SHA-256 revisado: `6d694b197ffcc58ccfb71efa490a18fe908d6610007b2a4ef38de6e9099d5781`. Depois, Codex faz a terceira revisão. Decisões ainda abertas: R7 (`uvicorn`, só para execução fora dos testes), R8 (parâmetros do limite por IP, após P-04) e R9 (mesma origem/CORS, após P-04/P-07).
2. Somente após a aprovação documental, iniciar S0-10a: dependências `fastapi`/`httpx`, fábrica da aplicação, configuração, cabeçalhos, entrada/erros e fábrica de conexão sem abertura antecipada. Claude implementa; Codex revisa antes de S0-10b.
3. S0-10b deve separar roles no laboratório. A role da aplicação não pode ser dona de `audit_events` nem ter `UPDATE`, `DELETE` ou `TRUNCATE`; privilégios serão aplicados por script versionado e testado. API e piloto não avançam sem essa proteção.
4. Levantar P-04: sistemas operacionais, VM, protocolo de compartilhamento, domínio, raízes autorizadas, volume e capacidade. P-04 bloqueia proxy confiável, parâmetros reais de IP, P-03 e integração real.
5. Resolver P-07: certificados/HTTPS, backup e restauração e retenção de logs, tentativas e cópias. Sem P-04/P-07, S0-10 fica restrita ao laboratório; nenhum servidor real ou deploy está autorizado.
6. P-05, P-06 e as propostas D-002–D-004, D-007–D-010, D-012 e D-013 continuam pendentes. Após HTTP, planejar cadastros, vínculos, classificação, busca, abertura, pendências, dashboard e frontend em tarefas separadas.

## Fluxo de retomada

- Claude implementa uma tarefa por vez; Codex revisa. Após cada revisão, informar brevemente o resultado e enviar o próximo prompt para o Claude.
- Antes de iniciar trabalho, conferir `git status`, a tarefa específica e as decisões vigentes. Sem servidor real, dados reais ou deploy sem autorização do responsável.
- Ponto exato de retomada: enviar ao Claude um prompt curto, no formato de `PROJECT_SPEC.md` §15.5, para corrigir os três achados da segunda revisão da S0-10. Não implementar código antes da terceira revisão e aprovação documental.
