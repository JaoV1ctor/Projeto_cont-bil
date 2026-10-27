# Arquitetura — MVP 0

**Status:** stack aprovada (D-005, D-006 em `docs/DECISIONS.md`). Demais itens são PROPOSTA até aprovação.

Fluxo de dados e topologia: `PROJECT_SPEC.md` §3. Este documento detalha componentes e limites de acesso.

## Componentes

| Componente | Responsabilidade | Acessa |
|---|---|---|
| Interface web (Next.js/TypeScript) | Telas do fluxo principal, pendências, dashboard | Somente a API |
| API (FastAPI/Python) | Autenticação, autorização, cadastros, busca, abertura mediada de documentos, auditoria | PostgreSQL; leitor de origem |
| Indexador (Python, processo separado) | Varredura com limites de carga, gravação de metadados e execuções | PostgreSQL; leitor de origem |
| Leitor de origem | Única porta de acesso ao compartilhamento; somente leitura | Raízes autorizadas |
| PostgreSQL local | Catálogo, cadastros, vínculos, pendências, execuções, auditoria | — |

Monólito modular: API e indexador compartilham o mesmo código de domínio e o leitor de origem, mas rodam como processos distintos.

## Leitor de origem (fronteira READ-ONLY)

Contrato proposto:

- Operações permitidas: listar diretório, obter metadados (`stat` sem seguir links), abrir para leitura com limite de bytes e timeout.
- Entrada: identificador da fonte + caminho relativo vindo do catálogo, nunca do cliente HTTP.
- Toda chamada resolve o caminho e verifica que permanece dentro da raiz autorizada; links simbólicos, junctions e reparse points são recusados no MVP.
- Nenhuma operação de escrita, renomeação, exclusão, criação de diretório ou alteração de atributos existe na interface.
- Erros de rede ou permissão retornam falha tipada; o componente nunca tenta outra credencial.

O controle efetivo é a conta de serviço sem permissão de escrita (SPEC §5.1). O contrato acima é a segunda camada.

## Limites de confiança

1. Navegador → API: rede interna, HTTPS, sessão autenticada. Navegador nunca recebe caminho físico como mecanismo de acesso.
2. API/indexador → origem: conta de serviço read-only; caminhos validados a cada acesso.
3. Dados de desenvolvimento: somente `tests/fixtures/servidor-teste/` ou cópia temporária dela.

## Estrutura de repositório proposta

```text
docs/                         arquitetura, decisões, tarefas
tests/fixtures/               amostra sintética e verificação
backend/app/                  domínio e acesso ao banco (API e indexador entram aqui)
backend/migrations/versions/  migrações Alembic versionadas
backend/tests/                testes de integração com PostgreSQL
frontend/                     Next.js (tarefa futura)
```

Esquema atual: `backend/migrations/versions/` (`0001` catálogo, `0002` erros de indexação, `0003` usuários e acesso por associação).

## Em aberto

Itens de infraestrutura que alteram esta arquitetura: SPEC §13 e `docs/DECISIONS.md`.
