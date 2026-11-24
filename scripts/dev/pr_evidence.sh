#!/usr/bin/env bash
# Evidência de PR (prints e vídeo) em repositório público: anexos de um release RASCUNHO.
#
#   scripts/dev/pr_evidence.sh <número do PR> <arquivo>...
#
# O GitHub não tem API para anexar arquivo a issue ou PR. Prints e vídeos entram por um release
# rascunho chamado `evidence/pr-<n>`: rascunho não aparece na página de releases nem para quem
# está deslogado, e os links dos anexos só abrem para quem tem acesso de escrita ao repositório.
# A evidência fica fora da vista do público e o corpo do PR pode linká-la. Rodar de novo
# acrescenta ao mesmo rascunho (arquivo de mesmo nome é substituído). No fim o script imprime o
# trecho de Markdown pronto para o corpo do PR.
#
# Só o que é de demonstração: neste repositório público, print e vídeo saem apenas do vault de
# demonstração (a padaria fictícia) — nunca dado real de pessoas, empresas ou da sua instância.
#
# O nome do arquivo vira o link: use letras, números, ponto, hífen e sublinhado
# (ex.: antes-painel.png, depois-painel.png, fluxo.mp4).
set -euo pipefail

REPO="${BRAIN_REPO:-BVLCQ/second-brain-framework}"

if [ $# -lt 2 ] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed -e 's/^# \{0,1\}//' >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh não encontrado" >&2; exit 1; }
PR="$1"
shift
TAG="evidence/pr-$PR"

for f in "$@"; do
  [ -f "$f" ] || { echo "arquivo não encontrado: $f" >&2; exit 1; }
  [[ "$(basename "$f")" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "nome de arquivo fora do permitido: $(basename "$f")" >&2; exit 1; }
done

RID=$(gh api "repos/$REPO/releases?per_page=100" \
  --jq "[.[] | select(.draft and .tag_name == \"$TAG\")] | first | .id // empty")
if [ -z "$RID" ]; then
  RID=$(gh api -X POST "repos/$REPO/releases" \
    -f tag_name="$TAG" -f target_commitish=main \
    -f name="Evidência do PR #$PR" \
    -f body="Prints e vídeo do PR #$PR. Rascunho: visível só para quem mantém o repositório." \
    -F draft=true --jq .id)
  echo "rascunho criado: $TAG"
else
  echo "rascunho reutilizado: $TAG"
fi

UPLOAD=$(gh api "repos/$REPO/releases/$RID" --jq '.upload_url | sub("\\{.*"; "")')
for f in "$@"; do
  name="$(basename "$f")"
  old=$(gh api "repos/$REPO/releases/$RID/assets" --jq "[.[] | select(.name == \"$name\") | .id] | first // empty")
  [ -z "$old" ] || gh api -X DELETE "repos/$REPO/releases/assets/$old" >/dev/null
  gh api -X POST "$UPLOAD?name=$name" -H "Content-Type: application/octet-stream" --input "$f" \
    --jq '"anexado: \(.name) (\(.size) B)"'
done

echo
echo "Trecho para o corpo do PR:"
gh api "repos/$REPO/releases/$RID/assets" --jq '.[] | "- [\(.name)](\(.browser_download_url))"'
