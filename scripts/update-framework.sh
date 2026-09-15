#!/usr/bin/env bash
# Second Brain — atualizar o FRAMEWORK sem tocar nos SEUS DADOS.
#
#   bash scripts/update-framework.sh
#
# Garantias:
# - git pull --ff-only: só framework chega (seu vault/ é cegado pelo .gitignore
#   — uma única regra protege tudo: dados, config, estado, logs)
# - estrutura/vault/ segue no repo e atualiza junto; este script sincroniza:
#   arquivo que falta no seu vault → copia; template que mudou upstream →
#   chega como *.template.md AO LADO do seu (nunca sobrescreve)
# - verificação final: vault intacto + git status limpo
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Second Brain: atualizando framework =="

# 1. pull do framework (ff-only: sem merge, sem surpresa)
if git pull --ff-only; then
  echo "✓ framework atualizado"
else
  echo "AVISO: pull não-ff recusado — seu clone divergiu (commits locais no framework?)." >&2
  echo "  Corrija com: git stash && bash scripts/update-framework.sh && git stash pop" >&2
  exit 1
fi

# 2. sincronizar templates de zona (estrutura/vault/ → vault/), sem sobrescrever
if [ -d estrutura/vault ]; then
  find estrutura/vault -type f | while read -r f; do
    rel="vault/${f#estrutura/vault/}"
    if [ ! -e "$rel" ]; then
      mkdir -p "$(dirname "$rel")"
      cp "$f" "$rel" && echo "  novo: $rel"
    elif ! diff -q "$f" "$rel" >/dev/null 2>&1; then
      dest="${rel%.*}.template.${rel##*.}"
      cp "$f" "$dest"
      echo "  template mudou upstream — salvo AO LADO do seu: $dest"
    fi
  done
fi

# 3. verificação final: vault intacto e git limpo
for z in RAW PROCESSED FRESH PROFILE PLANNING; do
  [ -d "vault/$z" ] && echo "✓ vault/$z/ intacta" || echo "⚠ vault/$z/ ausente (instância nova?)"
done
if [ -z "$(git status --porcelain)" ]; then
  echo "✓ git status limpo — nenhum dado seu tracked/staged"
else
  echo "⚠ git status NÃO está limpo — inspecione antes de qualquer commit:" >&2
  git status --short >&2
  exit 1
fi
echo "== pronto: framework atual, dados intactos =="
