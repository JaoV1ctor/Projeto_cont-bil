# PROJECT_SPEC — Sistema interno de organização contábil

**Versão:** 0.3
**Data:** 25/10/2026
**Entrega inicial:** MVP 0 — Organização
**Status:** especificação inicial para revisão e planejamento; não autoriza implantação.

## 1. Objetivo e contexto

Criar uma aplicação web interna para o escritório contábil localizar documentos, consultar associações, emendas e vigências e acompanhar pendências simples. A organização atual envolve muitos arquivos, estruturas diferentes, nomes inconsistentes e documentos distribuídos pelo servidor existente.

A primeira entrega deve permitir este fluxo completo:

> Entrar no sistema → escolher uma associação → listar seus documentos → pesquisar e filtrar → abrir o documento autorizado em sua localização atual.

O sistema organizará inicialmente **informações e vínculos no banco**, preservando a organização física dos arquivos. A necessidade de resultados rápidos não permite atalhos na segurança do servidor.

Esta especificação consolida o contexto disponível da conversa “Automatizar gestão contábil”. Detalhes técnicos novos são propostas de projeto, não descrições de infraestrutura já verificada.

## 2. Decisões definidas e propostas

### 2.1. Restrições definidas

- Aplicação e dados operacionais executados e armazenados 100% localmente no escritório.
- Acesso pelo navegador, exclusivamente pela rede interna autorizada.
- PostgreSQL local.
- Servidor de arquivos existente permanece como fonte dos documentos originais.
- Integração inicial estritamente somente leitura, inclusive durante o piloto real.
- MVP 0 centrado em organização, consulta e visibilidade operacional.
- Claude Code como implementador principal; Codex como arquiteto, elaborador de tarefas e revisor.
- Toda implantação exige confirmação prévia do responsável pelo projeto, mesmo em rede local.

### 2.2. Arquitetura proposta para validação no planejamento

- Aplicação em máquina ou VM local separada do servidor crítico de arquivos.
- Frontend React com TypeScript; Next.js é uma opção, não uma decisão já aprovada.
- Backend Python/FastAPI e indexador Python, favorecendo a stack do desenvolvedor. Uma API integrada ao Next.js pode ser avaliada antes da implementação; evitar dois backends sem necessidade.
- Monólito modular com processo separado para indexação. Não iniciar com microsserviços, filas distribuídas ou mecanismo externo de busca.
- Busca inicial no PostgreSQL, sem Elasticsearch ou serviço de nuvem.
- Docker Compose somente se compatível com o ambiente local e com a montagem segura do compartilhamento. Contêineres não substituem permissões do sistema operacional.

Registrar a escolha final da stack e seus motivos antes de criar a estrutura do produto. Não trocar essas decisões silenciosamente durante uma tarefa.

## 3. Arquitetura e fluxo de dados

```text
Computadores do escritório
          │ HTTPS / rede local
          ▼
Máquina ou VM da aplicação
  ├─ Interface web e API
  ├─ Autenticação e autorização locais
  ├─ PostgreSQL local
  └─ Processo de indexação com limites de carga
          │ listagem e leitura autorizadas
          ▼
Servidor de arquivos existente
  └─ Compartilhamentos e pastas explicitamente permitidos
```

1. Administrador configura uma raiz autorizada no servidor da aplicação.
2. Indexador lista arquivos e registra metadados no PostgreSQL.
3. Usuários consultam o catálogo e mantêm vínculos e pendências no banco.
4. Para abrir um documento, a API verifica a autorização e lê o arquivo original.
5. O navegador recebe o conteúdo permitido; credenciais e caminhos físicos não são expostos como mecanismo de acesso.

O navegador não deve depender de links `file://` ou acesso direto a caminhos UNC. O catálogo não é uma cópia integral nem um backup dos arquivos.

O funcionamento normal deve continuar sem internet: autenticação, recursos visuais, bibliotecas do navegador, busca e abertura de documentos não podem depender de CDN, fontes remotas, autenticação externa ou API hospedada. Instalação e atualizações podem exigir preparação de pacotes, sem envio de dados do escritório.

## 4. Escopo funcional do MVP 0

### 4.1. Login e permissões

- Contas individuais, ativação/desativação e encerramento de sessão.
- Perfis iniciais: administrador, operador e consulta.
- Administrador gerencia contas, permissões, raízes autorizadas e execução da indexação.
- Operador mantém cadastros, vínculos e pendências nas associações autorizadas.
- Consulta lista, pesquisa e abre documentos das associações autorizadas.
- Acesso a uma associação deve ser concedido explicitamente. Aplicar a mesma autorização à busca, ao dashboard e à abertura de arquivos.
- Documentos ainda sem associação ficam em uma fila restrita a administradores.

### 4.2. Associações, emendas e vigências

- Associações: nome, nome de uso opcional, CNPJ quando disponível, situação e observações.
- Emendas: associação, referência, ano, origem/órgão quando conhecido, descrição e situação administrativa.
- Vigências: associação, emenda opcional, identificação do instrumento, início, fim e observações.
- Não presumir que número de emenda seja único globalmente ou que toda associação possua emenda.
- Manter documentos gerais da associação sem exigir emenda ou vigência.
- Não derivar automaticamente vigência ou situação jurídica pelo nome de uma pasta.
- Encerramento/inativação preserva histórico e documentos vinculados.

### 4.3. Documentos e organização lógica

- Listagem paginada com nome, extensão, tamanho, data de modificação, localização relativa, categoria e vínculos confirmados.
- Detalhes com última observação pelo indexador, disponibilidade e estado de classificação.
- Categorias iniciais editáveis: constituição, certidões, termos/instrumentos, planos de trabalho, notas fiscais, extratos, comprovantes e outros.
- Associação sugerida por regra de caminho deve aparecer como sugestão até confirmação ou mapeamento explícito aprovado.
- Correções manuais de categoria e vínculos devem sobreviver às reindexações.
- Suportar documentos não classificados, nomes repetidos em pastas diferentes e estruturas heterogêneas.
- Categorizar um arquivo como nota fiscal não implica validar seu conteúdo fiscal.

### 4.4. Pesquisa e abertura

- Pesquisa por nome do arquivo e caminho relativo, com tratamento consistente de maiúsculas e acentos.
- Filtros combináveis: associação, emenda, vigência, categoria, extensão, disponibilidade e estado de classificação.
- Ordenação estável, paginação e mensagem clara para ausência de resultados.
- Busca inicial exclusivamente por metadados; não promete pesquisa no conteúdo de PDFs ou documentos digitalizados.
- PDF e imagens poderão ser visualizados no navegador somente com tratamento seguro; outros formatos serão baixados para abertura local.
- Nunca executar macros, scripts, arquivos ou comandos no servidor para abrir documentos.
- Download é leitura da origem e pode gerar cópia no computador autorizado. Não oferecer edição ou salvamento de volta ao servidor.

### 4.5. Pendências simples

- Cadastro manual de título, descrição, associação, responsável opcional, prazo opcional e estado: aberta, em andamento, resolvida ou cancelada.
- Vínculos opcionais a emenda, vigência e documento.
- Atraso calculado pelo prazo e estado; não é um estado gravado separado.
- Nenhum arquivo ausente deve gerar conclusão automática de irregularidade contábil.

### 4.6. Dashboard

- Quantidade de associações acessíveis, documentos indexados, pendências abertas e atrasadas e vigências próximas do fim.
- Janela inicial proposta para vigências próximas do fim: 30 dias, configurável.
- Última indexação, situação da fonte e avisos de catálogo desatualizado; detalhes técnicos de execução restritos ao administrador.
- Contagens respeitam permissões e exibem sua referência temporal.
- Não mostrar valores financeiros, conformidade ou completude documental que o sistema ainda não calcula.

## 5. Regras críticas de segurança do servidor

1. **Somente leitura imposta fora da aplicação.** Usar conta de serviço dedicada com listagem/leitura e sem criação, alteração, exclusão ou renomeação, tanto no compartilhamento quanto nas permissões do sistema de arquivos.
2. **Sem credenciais administrativas.** Não executar aplicação ou indexador com conta de administrador do domínio ou do servidor.
3. **Sem operações de escrita na origem.** O módulo de integração não implementará upload, delete, move, rename, overwrite, sincronização bidirecional ou reorganização física.
4. **Sem efeitos indiretos na origem.** Logs, banco, temporários, relatórios e qualquer cache ficam em armazenamento da aplicação. Não criar arquivos auxiliares nas pastas indexadas.
5. **Raízes permitidas explícitas.** A API recebe identificador de documento, nunca um caminho arbitrário do cliente. Resolver e validar o caminho no servidor a cada abertura, impedindo traversal e escapes por links simbólicos, junctions e reparse points. No MVP, não seguir esses links durante a varredura.
6. **Autorização em toda leitura.** Permissão da conta de serviço não equivale à permissão do usuário. Revalidar autorização antes de entregar bytes, inclusive em requisições parciais.
7. **Não publicar o compartilhamento.** Sem diretório estático apontando para a origem e sem listagem pública de arquivos. Acesso sempre mediado pela API.
8. **Carga limitada.** Configurar concorrência, lotes, intervalos, timeout e tamanho máximo de leitura. Começar com um trabalhador; ampliar após medição no piloto. Evitar hash integral e extração de conteúdo em toda varredura.
9. **Falhar com segurança.** Queda de rede ou permissão negada não autoriza usar outra credencial, aumentar privilégios ou alterar permissões automaticamente.
10. **Interrupção simples.** Administrador deve poder suspender novas varreduras e cancelar uma execução sem alterar os arquivos originais.
11. **Desenvolvimento isolado.** Começar com estrutura sintética ou cópia autorizada e anonimizada. Não conectar o ambiente de desenvolvimento à raiz real por padrão.
12. **Implantação controlada.** Antes de qualquer deploy, apresentar versão, destino, mudanças, validações, backup e reversão; aguardar confirmação explícita.

`SERVER_ACCESS_MODE=READ_ONLY` pode documentar a intenção, mas não constitui controle de segurança. A restrição deve ser comprovada pelas permissões efetivas e pela implementação.

Não tentar gravar arquivos para testar permissões no acervo real. Validar negação de escrita em compartilhamento de laboratório equivalente e revisar as permissões efetivas da conta no ambiente real com o responsável pela infraestrutura.

## 6. Segurança da aplicação e operação local

- HTTPS na LAN com certificado confiável nos computadores do escritório; definir emissão e distribuição com a infraestrutura.
- Firewall limita acesso à aplicação à rede autorizada. PostgreSQL acessível apenas pelos componentes necessários; sem exposição pública ou encaminhamento de portas no roteador.
- Senhas protegidas com algoritmo apropriado, sessões com expiração e cookies seguros; proteção contra tentativas repetidas de login e contra CSRF quando aplicável.
- Consultas parametrizadas, validação de entrada e tratamento seguro de nomes e caminhos em HTML e cabeçalhos HTTP.
- Tipos ativos ou desconhecidos entregues como anexo. Não confiar apenas na extensão para visualização inline; usar cabeçalhos de segurança e impedir detecção indevida de conteúdo.
- Segredos fora do Git, do frontend e dos logs; exemplos de configuração apenas com valores fictícios.
- Não enviar documentos, nomes sensíveis, credenciais ou dados reais para Claude, Codex, telemetria ou serviços externos. Usar amostras anonimizadas e exemplos sintéticos no desenvolvimento.
- Auditar autenticação, mudanças de permissão, cadastros, classificação, abertura/download e indexação. Registrar ator, ação, alvo, resultado e data; nunca conteúdo integral de documentos ou senhas.
- A role do PostgreSQL usada pela aplicação é separada da role de migração. A role da aplicação não é dona de `audit_events` e tem nela somente `INSERT` e `SELECT`, sem `UPDATE`, `DELETE` ou `TRUNCATE`; o trigger append-only não protege contra o dono da tabela, `TRUNCATE` ou `DROP`. Validar esses privilégios no laboratório antes da API e do piloto. A infraestrutura provisiona as roles no ambiente real; acesso real e deploy exigem confirmação do responsável.
- Credenciais da fonte, logs e backups acessíveis apenas aos responsáveis. Retenção e capacidade devem ser definidas antes do piloto.
- Backup local do PostgreSQL e das configurações, com restauração testada em ambiente isolado. Backup dos documentos continua sob responsabilidade do processo existente do escritório.
- Proposta inicial: backup diário do banco, antes de migrações e em destino local separado da máquina da aplicação. Responsável, retenção e objetivos de recuperação devem ser aprovados conforme a infraestrutura.

## 7. Indexação: comportamento obrigatório

### 7.1. Coleta inicial

Coletar raiz, caminho relativo, nome, extensão, tamanho e data de modificação informada pelo sistema de arquivos. Registrar separadamente data de observação pelo indexador. Data de modificação não é data de emissão, competência ou validade jurídica.

As regras de classificação usam mapeamentos explícitos de pasta para associação e sugestões simples de categoria. Não incluir IA, OCR ou interpretação contábil nesta etapa.

### 7.2. Reexecução e consistência

- Indexação idempotente: repetir uma varredura sem mudanças não duplica registros.
- Identidade inicial baseada em raiz e chave normalizada do caminho relativo. Preservar o caminho original e respeitar a sensibilidade a maiúsculas do sistema de arquivos; não aplicar conversão global que una arquivos distintos.
- Alteração de tamanho ou data atualiza metadados, sem substituir classificação manual.
- Renomeação aparece inicialmente como caminho novo e caminho anterior não localizado; não alegar reconhecimento de identidade sem evidência.
- Hash é opcional e fora da rotina inicial. Nome ou tamanho iguais não provam duplicidade de conteúdo.
- Não excluir registros porque deixaram de aparecer. Marcar como não localizado somente após varredura completa e bem-sucedida do escopo correspondente.
- Em varredura parcial, cancelada, com falhas de acesso ou fonte offline, preservar disponibilidade anterior e indicar incerteza/desatualização. Não marcar toda a árvore como removida.
- Na abertura, revalidar existência e acesso. Se indisponível, retornar mensagem clara e preservar o histórico no catálogo.
- Evitar execuções concorrentes sobre a mesma raiz; suportar processamento em lotes e retomada segura ou reexecução idempotente.
- Registrar contagens de encontrados, novos, atualizados, não localizados, ignorados e erros. Uma execução com erros não pode aparecer como sucesso completo.

### 7.3. Casos de laboratório

Incluir acentos, nomes longos, espaços, caracteres especiais, subpastas profundas, arquivos vazios e grandes, nomes repetidos, PDFs, XML, planilhas, documentos de texto, temporários, acesso negado, interrupção da rede e arquivos alterados durante a leitura. Duplicatas devem permanecer preservadas.

## 8. Modelo de dados inicial proposto

Usar identificadores UUID, chaves estrangeiras e migrações versionadas. Datas de negócio usam `date`; instantes usam `timestamptz`, com apresentação em `America/Sao_Paulo`. Tabelas de cadastro têm criação, atualização e responsável quando aplicável.

| Entidade | Campos principais e finalidade |
|---|---|
| `users` | Identidade, nome, login único, hash de senha, perfil, ativo. |
| `associations` | Nome, nome de uso, CNPJ normalizado opcional, situação, observações. CNPJ informado deve ser único após revisão de inconsistências. |
| `user_associations` | Usuário e associação; par único que concede acesso operacional. Administrador tem acesso global auditado. |
| `amendments` | Associação obrigatória, referência, ano, órgão/origem, descrição, situação. Referência não é chave global. |
| `validity_periods` | Associação obrigatória, emenda opcional, identificação do instrumento, início, fim, observações. |
| `document_sources` | Nome da fonte, raiz configurada, política de normalização, ativo, estado da fonte, última execução completa. Credencial armazenada fora da tabela, por referência segura. |
| `source_mappings` | Fonte, prefixo de pasta, associação e vínculos opcionais, aprovação e autor. Regra mais específica prevalece; conflito sem resolução impede classificação automática. |
| `document_categories` | Nome único, descrição e ativo. |
| `documents` | Fonte, caminho relativo original, chave de caminho, nome, extensão, tamanho, modificação na origem, primeira/última observação, disponibilidade, categoria opcional e estado de classificação. Par fonte/chave de caminho único. |
| `document_links` | Documento, associação, emenda opcional e vigência opcional; origem manual ou mapeamento aprovado, autor e data. Permite documento compartilhado sem copiar o arquivo. |
| `document_suggestions` | Documento, vínculos/categoria sugeridos, regra e versão, estado pendente/aceita/rejeitada e revisor. Sugestão não concede acesso ao documento. |
| `tasks` | Pendência, associação, vínculos opcionais, título, descrição, responsável, prazo, estado e resolução. |
| `index_runs` | Fonte, escopo, início/fim, estado, contagens, motivo de interrupção e última posição processada quando utilizada. |
| `index_errors` | Execução, item afetado, código, descrição sanitizada e data. |
| `audit_events` | Ator humano ou serviço, ação, alvo, resultado, data e alterações relevantes sanitizadas. Sem alteração pela API comum. |

### 8.1. Integridade e autorização

- Emenda pertence a uma associação. Vigência ligada a emenda deve pertencer à mesma associação.
- Data final de vigência não pode preceder a inicial; períodos diferentes podem coexistir e não são automaticamente tratados como aditivos.
- Vínculos e pendências não podem combinar associações, emendas e vigências incompatíveis. Aplicar restrições no banco quando possível e validação transacional na API.
- Documento pode ter vários vínculos confirmados, mas sem duplicar uma mesma combinação; tratar corretamente campos opcionais nas restrições de unicidade.
- Usuário com acesso a uma associação vinculada pode ler o documento, mas não recebe metadados de outras associações às quais não tenha acesso. Contagens usam documentos distintos.
- Cadastro de vínculo a outra associação exige permissão no destino. Não permitir que usuário se conceda acesso por classificação.
- Não apagar cadastros referenciados em cascata; usar inativação ou impedir a exclusão. Arquivos originais nunca participam de exclusões do banco.
- Indexar chaves estrangeiras e campos usados nos filtros. Escolher índice de busca após medição, evitando otimização sem evidência.

## 9. Fora de escopo do MVP 0

- Conciliação bancária, validação financeira e prestação de contas.
- Geração, preenchimento ou validação de RP-10.
- Emissão ou consulta automática de NFS-e, integrações com TCU ou portais públicos.
- OCR, embeddings, busca semântica e classificação por IA.
- Identificação automática de documentos faltantes por regras contábeis.
- Detecção confiável e remoção de duplicatas.
- Upload, edição, renomeação, movimentação, exclusão, reorganização física ou sincronização bidirecional de arquivos.
- Importação financeira, migração integral das planilhas e cópia integral do servidor para o banco.
- WhatsApp, e-mail automático, acesso remoto, hospedagem externa e serviços operacionais em nuvem.
- Alta disponibilidade, aplicativo móvel e expansão para todo o acervo antes do piloto.

Necessidades futuras entram no backlog e não podem bloquear a primeira entrega. Qualquer proposta de escrita no servidor exige nova especificação, análise de risco, backup, reversão e aprovação explícita; não é uma opção a ativar no MVP 0.

## 10. Critérios de sucesso e aceite

O MVP 0 é aceito quando todos os critérios obrigatórios abaixo forem demonstrados:

1. Usuário autorizado executa o fluxo principal no navegador em rede local, sem dependência de internet.
2. Uma a três associações piloto têm cadastros e documentos consultáveis; emendas e vigências disponíveis estão corretamente vinculadas.
3. Busca e filtros localizam documentos conhecidos de uma amostra validada pelo escritório; sugestões e itens sem classificação são identificáveis.
4. Reindexação sem mudanças não duplica documentos e preserva vínculos manuais.
5. Arquivo novo, alterado e não localizado é tratado conforme a regra de varredura; falha de rede não provoca remoção em massa do catálogo.
6. Usuário sem permissão não obtém documentos, resultados, contagens ou metadados restritos, mesmo chamando a API diretamente.
7. Tentativas de traversal e escape por links são bloqueadas; o módulo não oferece escrita na origem. Permissões efetivas read-only são verificadas.
8. Pendências e dashboard apresentam dados reais e respeitam acesso e datas.
9. Backup do banco é restaurado com sucesso em ambiente isolado; responsável consegue suspender o indexador e consultar falhas.
10. Implantação piloto é autorizada e não causa impacto perceptível incompatível com o trabalho do servidor, conforme medição acordada com a infraestrutura.

### 10.1. Medição de valor e desempenho

Antes do piloto, selecionar pelo menos dez tarefas reais de localização de documentos. Registrar tempo atual, tempo usando o sistema e taxa de sucesso, sem inventar resultados.

Metas iniciais propostas, a confirmar após conhecer volume, rede e hardware:

- Reduzir em pelo menos 50% o tempo mediano de localização na amostra.
- Pesquisa paginada com percentil 95 de até 2 segundos no conjunto piloto e carga simultânea acordada.
- Abertura medida separadamente, pois depende do tamanho do arquivo e da rede.
- Registrar duração e impacto de cada varredura para definir frequência e limite de carga.

Esses números são metas de planejamento, não garantias verificadas. Documentar volume de arquivos, tamanho do catálogo, usuários simultâneos e ambiente de teste junto aos resultados.

## 11. Roadmap por entregas verificáveis

### Etapa 0 — Descoberta e planejamento

- Confirmar ambiente, acessos e amostra de pastas, sem varrer o servidor real indiscriminadamente.
- Validar esta especificação e registrar decisões de arquitetura.
- Codex prepara plano em tarefas pequenas, incluindo testes e critérios de aceite.
- Preparar laboratório representativo e anonimizado.
- Saída: arquitetura e plano revisáveis; nenhuma mudança no servidor crítico.

### Etapa 1 — Prova de conceito no laboratório

- Indexar uma raiz autorizada de teste, persistir metadados no PostgreSQL e listar no navegador.
- Comprovar somente leitura, idempotência e tratamento de erros.
- Saída: demonstração ponta a ponta usando dados de teste.

### Etapa 2 — MVP 0 funcional

- Login, autorização, cadastros, vínculos, pesquisa, filtros e abertura segura.
- Pendências, dashboard e auditoria básica.
- Saída: critérios funcionais e de segurança validados no laboratório.

### Etapa 3 — Piloto controlado

- Confirmar conta read-only, raízes, capacidade, backup e procedimento de reversão.
- Após confirmação de deploy, implantar para uma a três associações e poucos usuários.
- Medir tempo de busca, erros, desempenho e impacto no servidor; ajustar antes de ampliar.
- Saída: aceite dos usuários e evidência de ganho operacional.

### Etapa 4 — Expansão da organização

- Incluir novas associações gradualmente, melhorar mapeamentos e corrigir inconsistências com revisão humana.
- Saída: catálogo confiável e processo operacional documentado.

### Evoluções posteriores

Especificar separadamente conciliação, controle mensal, RP-10, prestação de contas e integrações. OCR e IA exigem decisão própria compatível com a restrição de processamento local. Mudanças dessa restrição nunca são implícitas.

Horizonte indicativo da conversa: demonstração nas primeiras 2–3 semanas e uso controlado em aproximadamente 4–8 semanas. Reestimar após descoberta; disponibilidade do desenvolvedor, qualidade da amostra e infraestrutura determinam o prazo. Não comprometer data para o sistema completo nesta especificação.

## 12. Regras de trabalho: responsável, Claude Code e Codex

### Responsável pelo projeto

- Define prioridades, esclarece regras reais do escritório e valida demonstrações.
- Aprova arquitetura, mudanças de escopo, acessos reais e cada implantação.
- Coordena com a infraestrutura permissões, backups e janela de operação.

### Codex — arquiteto e revisor

- Transforma necessidades em decisões documentadas, tarefas e prompts precisos.
- Define limites entre componentes, modelo de dados, segurança e critérios de aceite.
- Revisa diffs, testes, migrações, regressões, impacto operacional e aderência ao escopo.
- Relata problemas concretos com localização, impacto e correção esperada; distingue bloqueadores de sugestões.
- Não assume a implementação principal nem troca a stack sem decisão do responsável.

### Claude Code — implementador principal

- Lê esta especificação, instruções do repositório e tarefa aprovada antes de alterar código.
- Implementa uma tarefa pequena por vez, sem expandir escopo ou inventar regras contábeis.
- Escreve e executa testes adequados; documenta comandos, resultados e limitações reais.
- Entrega resumo, arquivos alterados, migrações, configuração e evidências de validação.
- Corrige os achados de revisão antes de avançar para tarefas dependentes.

### Ciclo obrigatório

```text
Necessidade validada pelo responsável
  → Codex: tarefa e critérios de aceite
  → Claude Code: implementação e testes
  → Codex: revisão
  → Claude Code: correções
  → Responsável: validação funcional
  → Confirmação explícita antes de deploy
```

Cada prompt de implementação deve identificar objetivo, referências ao contexto persistente, delta necessário, escopo permitido, exclusões, decisões aplicáveis, critérios de aceite, testes esperados e formato da entrega, conforme a política obrigatória da seção 15. Referenciar o conteúdo já disponível no repositório, sem reproduzi-lo integralmente. Dúvidas de domínio relevantes devem ser levadas ao responsável, sem preenchimento por suposição.

### Qualidade e mudanças

- Trabalhar em Git com alterações pequenas e revisáveis; não versionar documentos reais, credenciais, dumps ou logs sensíveis.
- Manter migrações versionadas e procedimento de recuperação; não alterar esquema de produção manualmente.
- Testar regras de autorização, caminhos, idempotência, interrupção e integridade com casos negativos, além do fluxo feliz.
- Usar testes de integração com PostgreSQL e compartilhamento de laboratório quando necessários para reproduzir comportamento real.
- Revisões devem verificar que nenhum teste toca o acervo de produção ou depende de segredos reais.
- Não declarar testes aprovados quando não executados. Informar bloqueios e cobertura não verificada.
- Atualizar esta especificação quando uma decisão mudar, registrando motivo, impacto e aprovação.
- Deploy e acesso ao acervo real são passos separados da implementação local e exigem os controles previstos neste documento.

## 13. Informações a levantar antes da integração real

Estas perguntas não impedem preparar o laboratório, mas bloqueiam as decisões dependentes:

- Sistema operacional do servidor de arquivos e da máquina/VM da aplicação; protocolo de compartilhamento e existência de domínio.
- Raízes autorizadas, estrutura representativa, volume de arquivos, tamanho total e ritmo de mudança.
- Hardware, capacidade livre, conectividade e usuários simultâneos esperados.
- Associações do piloto, responsáveis pelos cadastros e matriz de acesso dos funcionários.
- Significado usado pelo escritório para emenda, instrumento, vigência e eventual relação entre eles.
- Processo atual de backup, responsável por restauração e metas aceitáveis de perda de dados e indisponibilidade.
- Disponibilidade de conta de serviço, DNS local, certificados e janela para indexação.
- Política de retenção de logs, backups e cópias baixadas nos computadores.

## 14. Primeira tarefa para o Codex

> Leia PROJECT_SPEC.md e as instruções do repositório. Sem implementar o produto nem acessar o servidor real, proponha a arquitetura do MVP 0, registre as decisões de stack, desenhe a estrutura do repositório e detalhe modelo de dados, indexador read-only, autenticação, autorização, abertura segura de documentos, backup e estratégia de testes. Separe fatos conhecidos de perguntas de infraestrutura. Prepare um plano incremental com tarefas pequenas e critérios de aceite para Claude Code, começando pelo laboratório. Apresente o plano ao responsável antes da implementação.

## 15. Harness e Política de Economia de Tokens — obrigatória

### 15.1 Objetivo e prioridade

Claude Code e Codex devem minimizar tokens de entrada e saída sem reduzir qualidade, segurança, precisão ou cobertura de testes necessária.

O harness é o conjunto de instruções persistentes, referências, modelos de tarefa e verificações que mantém o trabalho consistente. Sua função é evitar prompts repetitivos e extensos, preservando contexto suficiente para implementar e revisar corretamente.

Ordem de prioridade: segurança do servidor e dos dados; correção e critérios de aceite; testes e auditabilidade; economia de tokens.

### 15.2 Papéis

**Claude Code — implementador principal**

- Implementar tarefas delimitadas por Codex e aprovadas dentro do escopo do projeto.
- Consultar os arquivos persistentes relevantes antes de alterar código.
- Executar os testes pertinentes e informar os resultados reais.
- Entregar resumo curto, arquivos afetados, referência ao diff e riscos ou pendências.
- Solicitar definição quando uma ambiguidade afetar segurança ou requisitos; não ampliar o escopo silenciosamente.

**Codex — arquiteto, revisor e gerador de prompts**

- Consolidar arquitetura e decisões nos arquivos do repositório.
- Transformar necessidades em tarefas curtas, delimitadas e verificáveis.
- Gerar prompts de implementação para Claude Code.
- Revisar diffs e arquivos afetados contra requisitos, segurança, regressões e testes.
- Consultar dependências e contexto adicional quando necessários à revisão.
- Retornar achados acionáveis e registrar limitações de validação.

Os papéis não dispensam a revisão humana nem autorizam deploy, mudança de escopo ou ampliação de permissões.

### 15.3 Contexto persistente no repositório

Manter requisitos neste `PROJECT_SPEC.md`. Ao preparar o repositório, criar ou aproveitar arquivos equivalentes para:

- `AGENTS.md`: regras compartilhadas, limites de segurança e comandos de validação.
- `CLAUDE.md`: instruções específicas do Claude Code, referenciando regras compartilhadas sem duplicá-las.
- `docs/ARCHITECTURE.md`: arquitetura, componentes e limites de acesso.
- `docs/DECISIONS.md`: decisões aprovadas e suas justificativas essenciais.
- `docs/tasks/`: tarefas, critérios de aceite e pendências relevantes.

Esta lista define uma organização de referência; não afirma que esses arquivos já existem. Manter uma fonte canônica para cada regra e usar referências nas demais. Atualizar a documentação afetada junto da mudança aprovada.

### 15.4 Regra do delta

Cada prompt deve transportar somente a mudança de contexto necessária à tarefa atual: objetivo, referências, restrições específicas, critérios de aceite e validação esperada.

- Não reenviar integralmente SPEC, arquitetura, histórico ou arquivos já disponíveis ao destinatário.
- Preferir caminhos e seções exatas, commits, diffs delimitados e arquivos afetados.
- Explicitar a base e a versão do diff para evitar revisão de código desatualizado.
- Fornecer trechos adicionais somente quando a referência não estiver acessível ou o conteúdo for necessário à decisão.
- Não presumir que agentes compartilham memória ou acesso ao mesmo checkout; verificar as referências de trabalho.
- Buscar contexto de forma progressiva, ampliando a leitura quando houver dependências, riscos ou dúvidas.
- Preservar mensagens de erro exatas e dados técnicos necessários; reduzir ruído, não evidência.

### 15.5 Modelo de prompt: Codex → Claude Code

```text
TASK: objetivo único e delimitado.
CONTEXT: caminhos/seções relevantes; branch ou commit de referência.
DELTA: comportamento atual → comportamento esperado.
SCOPE: arquivos/componentes previstos e limites da tarefa.
CONSTRAINTS: restrições relevantes; integração com arquivos READ-ONLY.
ACCEPTANCE: critérios observáveis de conclusão.
TESTS: validações necessárias e ambiente autorizado.
OUTPUT: resumo curto; arquivos/diff; testes e resultados; riscos/pendências.
```

Omitir campos sem informação útil. Não omitir critérios de aceite nem restrições de segurança aplicáveis. Referenciar regras persistentes; repetir uma restrição crítica quando isso evitar ambiguidade.

### 15.6 Modelo de solicitação: Claude Code → Codex

```text
REVIEW: tarefa e critérios de aceite de referência.
BASE/HEAD: commits ou identificação precisa do diff local.
CHANGES: resumo curto e arquivos afetados.
TESTS: verificações executadas, resultados e o que não foi testado.
RISKS: decisões, dúvidas ou limitações relevantes; “nenhum conhecido” se aplicável.
FOCUS: pontos que exigem atenção, sem limitar a revisão de segurança.
```

Não colar arquivos completos quando o revisor puder consultar o diff e o repositório. Não incluir dados reais de clientes ou segredos.

### 15.7 Respostas e revisão

Usar respostas curtas e estruturadas. Informar resultados, evidências e ações necessárias; evitar narrar cada passo, repetir requisitos ou explicar extensamente código já disponível.

Formato preferencial para achados:

```text
[severidade] arquivo:linha — problema; impacto; correção necessária.
Validação: testes executados e limitações.
Status: sem achados bloqueantes / ajustes necessários / revisão incompleta.
```

Revisar requisitos, permissões, integridade de dados, fronteira READ-ONLY, falhas, auditoria e regressões pertinentes. O diff é o ponto de partida, não um limite obrigatório de leitura. Ausência de achados não comprova segurança completa nem substitui testes.

### 15.8 Ciclo de trabalho

1. Codex define tarefa e referências curtas.
2. Claude Code consulta o contexto persistente, implementa e valida.
3. Claude Code entrega o delta e as evidências para revisão.
4. Codex revisa e devolve achados objetivos ou limitações.
5. Claude Code corrige e valida as mudanças necessárias.
6. Codex verifica as correções; decisões e pendências ficam registradas no repositório.
7. O responsável confirma qualquer deploy antes da execução.

Não repetir contexto estável em cada rodada. Aumentar o contexto quando necessário para resolver riscos ou incertezas. Não impor um teto de tokens que corte achados, falhas, testes ou instruções de segurança. Não alegar economia de tokens sem medição.

## 16. Histórico

- **v0.1 — 13/10/2026:** especificação inicial do MVP 0, arquitetura local, integração somente leitura, modelo conceitual, critérios de aceite e divisão de trabalho.

- **v0.2 — 14/10/2026:** política obrigatória de Harness e Economia de Tokens; contexto persistente, prompts por delta, modelos de implementação e revisão e prioridade da segurança sobre economia. Escopo funcional e decisões anteriores preservados.

- **v0.3 — 25/10/2026:** controle no PostgreSQL para `audit_events` (§6): role da aplicação separada da role de migração, sem ser dona da tabela e só com `INSERT` e `SELECT`. Motivo: garantir "sem alteração pela API comum" (§8), que o trigger append-only não garante sozinho. Impacto: API e piloto exigem roles separadas, validadas no laboratório e provisionadas pela infraestrutura no ambiente real. Origem: revisão técnica do Codex. Sem mudança funcional e sem autorização de deploy.
