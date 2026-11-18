#!/bin/sh
# Brain — entrada sem terminal (Finder / macOS).
#
# Duplo clique no Finder inicia o Brain.
# A janela que abre roda sozinha; nada é digitado.
# O curl continua valendo pra quem vive no terminal:
#   curl -fsSL https://raw.githubusercontent.com/BVLCQ/second-brain-framework/main/install.sh | sh -
# ou:
#   sh install.sh

set -e
cd "$(dirname "$0")"

REPO_URL="https://github.com/BVLCQ/second-brain-framework"

# ZIP do GitHub não traz .git (automático): inicializa o repositório e configura o origin
# para que o `brain update` e os checks de sincronização funcionem.
if [ ! -d ".git" ]; then
    git init -q
    if git remote | grep -q "^origin$"; then
        git remote set-url origin "$REPO_URL"
    else
        git remote add origin "$REPO_URL"
    fi
    git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
    git fetch --quiet || true
    echo "✓ pasta baixada como ZIP virou repositório git (origin configurado — o \`brain update\` funciona)"
fi

sh install.sh
