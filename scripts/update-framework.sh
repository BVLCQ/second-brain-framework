#!/usr/bin/env bash
# Second Brain — atualizar o FRAMEWORK sem tocar nos SEUS DADOS.
#
#   bash scripts/update-framework.sh
#
# Garantias:
# - git pull --ff-only: só framework chega (as zonas estão no .gitignore e não
#   existem no remote — nenhum conflito possível com seus dados)
# - depois do pull: verifica que as zonas continuam lá e que o git status
#   segue limpo (nada seu staged/tracked)
# - se o upstream trouxer templates novos (estrutura/), eles ficam ao lado
#   dos seus (ex.: PROFILE/profile.template.md) — NUNCA sobrescreve
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Second Brain: atualizando framework =="

# 1. sanity: zonas presentes?
for z in RAW PROCESSED FRESH PROFILE PLANNING; do
  [ -d "$z" ] || { echo "AVISO: zona $z não encontrada (instância nova? rode a instalação)"; }
done

# 2. pull do framework (ff-only: sem merge, sem surpresa)
if git pull --ff-only; then
  echo "✓ framework atualizado"
else
  echo "AVISO: pull não-ff recusado — seu clone divergiu (commits locais no framework?)." >&2
  echo "  Corrija com: git stash && bash scripts/update-framework.sh && git stash pop" >&2
  exit 1
fi

# 3. templates novos do upstream chegam como estrutura/ — mover para a raiz
#    SOMENTE arquivos que não existem na raiz (templates ganam sufixo .template)
if [ -d estrutura ]; then
  find estrutura -type f | while read -r f; do
    rel="${f#estrutura/}"
    if [ -e "$rel" ]; then
      dest="${rel%.*}.template.${rel##*.}"
      mv "$f" "$dest"
      echo "  template novo (não sobrescreveu o seu): $dest"
    else
      mv "$f" "$rel" && echo "  novo: $rel"
    fi
  done
  find estrutura -type d -empty -delete 2>/dev/null || true
fi

# 4. verificação final: suas zonas intactas e git limpo
for z in RAW PROCESSED FRESH PROFILE PLANNING; do
  [ -d "$z" ] && echo "✓ $z/ intacta"
done
if [ -z "$(git status --porcelain)" ]; then
  echo "✓ git status limpo — nenhum dado seu tracked/staged"
else
  echo "⚠ git status NÃO está limpo — inspecione antes de qualquer commit:" >&2
  git status --short >&2
  exit 1
fi
echo "== pronto: framework atual, dados intactos =="
