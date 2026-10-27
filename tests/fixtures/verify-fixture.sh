#!/bin/sh
# Verifica a amostra sintética contra o manifesto. Somente leitura.
# Uso: sh tests/fixtures/verify-fixture.sh [--update]
#   --update  regrava o manifesto (usar somente em mudança aprovada da amostra).
set -eu
LC_ALL=C
export LC_ALL

here=$(cd "$(dirname "$0")" && pwd)
root="$here/servidor-teste"
manifest="$here/servidor-teste.sha256"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cd "$root"

# Links simbólicos não fazem parte da amostra versionada (casos dinâmicos: README.md).
if [ -n "$(find . -type l)" ]; then
  echo "FALHA: link simbólico encontrado na amostra" >&2
  exit 1
fi

find . -type f -print | sed 's|^\./||' | sort >"$tmp/actual"

if [ "${1:-}" = "--update" ]; then
  while IFS= read -r f; do sha256sum -- "$f"; done <"$tmp/actual" >"$manifest"
  echo "manifesto atualizado: $(wc -l <"$manifest") arquivos"
  exit 0
fi

sed 's/^[0-9a-f]\{64\}  //' "$manifest" | sort >"$tmp/expected"
if ! cmp -s "$tmp/expected" "$tmp/actual"; then
  echo "FALHA: lista de arquivos diverge do manifesto (- esperado, + atual)" >&2
  diff "$tmp/expected" "$tmp/actual" >&2 || true
  exit 1
fi

if ! sha256sum --quiet --strict -c "$manifest"; then
  echo "FALHA: conteúdo diverge do manifesto" >&2
  exit 1
fi

# Heurística contra dados reais: padrões formatados de CNPJ/CPF e e-mail.
if grep -rlaE '[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2}|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' . >"$tmp/pii"; then
  echo "FALHA: padrão de CNPJ/CPF/e-mail encontrado:" >&2
  cat "$tmp/pii" >&2
  exit 1
fi

echo "OK: $(wc -l <"$tmp/actual") arquivos conferem com o manifesto"
