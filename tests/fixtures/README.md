# Amostra sintética `servidor-teste/`

Simula um compartilhamento do servidor de arquivos para desenvolvimento e testes (PROJECT_SPEC.md §5.11 e §7.3). Todo conteúdo é fictício: nomes de associações contêm "Exemplo", arquivos de texto trazem a marca `ARQUIVO SINTÉTICO DE TESTE` e não há CNPJ, CPF, e-mail ou valor real.

## Regras

- `servidor-teste/` representa a raiz indexável. Não colocar ali README, manifesto ou outro arquivo auxiliar: tudo nela é "documento" para o indexador.
- Testes leem a amostra; nunca escrevem nela. Casos que exigem mutação copiam a amostra para um diretório temporário.
- Alterar a amostra somente por tarefa aprovada e regravar o manifesto no mesmo commit.

## Verificação

```sh
sh tests/fixtures/verify-fixture.sh           # confere lista, SHA-256, ausência de symlinks e heurística de dados pessoais
sh tests/fixtures/verify-fixture.sh --update  # regrava servidor-teste.sha256 após mudança aprovada
```

Requer `sh`, `find`, `sort`, `sha256sum`, `grep`, `cmp` e `diff` (GNU coreutils). O manifesto `servidor-teste.sha256` usa o formato de `sha256sum -c`. Data de modificação não entra no manifesto, pois o Git não a preserva.

## Estrutura e casos cobertos (55 arquivos)

| Caso | Onde |
|---|---|
| Organização por ano/emenda | `ASSOCIAÇÕES/Associação Exemplo Aurora/2023/…`, `…/2024/…` |
| Organização por categoria | `ASSOCIAÇÕES/Instituto Exemplo Ipê/Constituição`, `Certidoes`, `Planilhas` |
| Associação fora da pasta padrão, estrutura plana, sem acentos | `ASSOC GRUPO EXEMPLO SAO JOAO/` |
| Pasta sem organização | `Digitalizados/` |
| Pasta obsoleta e subpasta profunda (10 níveis de pasta) | `_ANTIGO - NÃO USAR/2019/a/…/h/arquivo-profundo.txt` |
| Mesma referência de emenda em associações diferentes (§4.2) | `Emenda 2024-0001` em Aurora e em Ipê |
| Nomes repetidos em pastas diferentes | `Plano de Trabalho.pdf` (4×), `Certidão FGTS.pdf` (2×) |
| Mesmo nome-base, extensões diferentes | `Plano de Trabalho.pdf` e `.docx`; `NF 001.pdf` e `.xml` |
| Cópias por nome (não provam duplicidade) | `estatuto.PDF`, `estatuto (1).pdf`, `estatuto - Cópia.pdf` |
| Nome de pasta sugerindo vigência/validade (não derivar, §4.2) | `Vigência 2024-2025 (prorrogada)/`, `CND Federal - válida até 31-12-2024.pdf` |
| Pasta de categoria com e sem acento | `Certidões/` (Aurora) e `Certidoes/` (Ipê) |
| Acentos, `ç`, `º`, travessão | vários; `Termo de Fomento nº 12-2023.pdf` |
| Mesmo nome visível em Unicode NFC e NFD | `Nomes especiais/Relatório de Execução (NFD).txt` / `(NFC).txt` |
| Caracteres especiais `& ( ) # % [ ] + , !` | `Nomes especiais/Ofício nº 15 & anexos …pdf` |
| Espaços duplos, vários pontos, sem extensão, oculto | `Nomes especiais/` |
| Extensão maiúscula | `estatuto.PDF`, `SCAN0001.PDF`, `ARQUIVO MAIÚSCULO.TXT` |
| Nome longo (205 caracteres no caminho relativo) | `Nomes especiais/Prestação de contas parcial …pdf` |
| Arquivos vazios | `Nomes especiais/vazio.pdf`, `vazio.txt` |
| Temporários e arquivos de sistema | `~$ano de Trabalho.docx`, `arquivo.tmp`, `Thumbs.db`, `desktop.ini` |
| PDF válido (1 página) | maioria dos `.pdf` |
| XML sintético (não é layout de NF-e) | `NF 00x.xml`, `nota fiscal sem número.xml` |
| Planilhas | `.xlsx` (OOXML válido), `.ods` (ODF válido), `.csv` |
| Documentos de texto | `.docx` (OOXML válido), `.odt` (ODF válido), `.txt` |
| Imagens | `.png`, `.jpg` (8×8, válidas) |
| Extensão divergente do conteúdo | `Controle antigo.xls` contém CSV |
| Legado com assinatura OLE, conteúdo inválido | `Modelo Ofício.doc`, `Thumbs.db` |
| Tipos ativos (entregar como anexo, nunca renderizar/executar) | `Modelos/leia-me.html`, `logo.svg` (com `<script>` inofensivo), `executar.bat` (sem comandos) |

## Casos dinâmicos (não versionados)

Estes casos não são portáveis no Git ou dependem de ambiente. Cada teste que precisar deles deve criá-los em diretório temporário, a partir de uma cópia da amostra:

- Link simbólico, junction ou reparse point apontando para fora da raiz ou para dentro dela (§5.5).
- Pasta vazia (o Git não versiona).
- Nomes que diferem só por maiúsculas no mesmo diretório (colidem em Windows/macOS).
- Arquivo grande (definir tamanho conforme limite de leitura configurado, §5.8).
- Acesso negado (permissão removida na cópia), fonte offline, interrupção de rede e arquivo alterado durante a leitura (§7.3).
- Arquivo novo, alterado e removido entre varreduras (§7.2).
