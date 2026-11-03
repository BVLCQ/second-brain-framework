#!/bin/sh
# Segundo Cérebro — bootstrap do clone ao wizard.
#
#   caminho 1 (curl, máquina nova):
#     curl -fsSL https://raw.githubusercontent.com/BVLCQ/second-brain-framework/main/install.sh | sh -
#   caminho 2 (dentro do clone):
#     sh install.sh
#
# O que faz: clona (se fora do repo), confere o Python, e entrega ao wizard
# `./brain setup` — que pergunta tudo, valida na hora e é re-executável.
# Instalação assistida por IA: o mesmo wizard com --yes/--only + `./brain doctor`
# como régua (setup.md na raiz é a receita executável completa para agentes).
set -e

REPO_URL="https://github.com/BVLCQ/second-brain-framework"
DEST="${1:-$HOME/Apps/second-brain-framework}"

if [ ! -f "./brain" ] || [ ! -d "./brainlib" ]; then
    if [ -d "$DEST/.git" ]; then
        echo "✓ repo já existe em $DEST"
    else
        echo "→ clonando em $DEST"
        git clone --quiet "$REPO_URL" "$DEST"
    fi
    cd "$DEST"
fi

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    :
elif command -v mise >/dev/null 2>&1; then
    :   # o brain se reexecuta pelo mise sozinho (guarda no topo do script)
else
    echo "⚠ Python 3.11+ não encontrado."
    echo "  macOS:  brew install mise  &&  mise install   (na raiz do repo)"
    echo "  ou:     brew install python@3.12"
    echo "  depois rode de novo:  sh install.sh"
    exit 1
fi

echo "→ abrindo o wizard (re-executável; Ctrl-C não estraga nada):"
exec ./brain setup
