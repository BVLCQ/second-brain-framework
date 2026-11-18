#!/bin/sh
# Brain — instalação: do clone ao app aberto no navegador.
#
#   caminho 1 (curl, máquina nova):
#     curl -fsSL https://raw.githubusercontent.com/BVLCQ/second-brain-framework/main/install.sh | sh -
#   caminho 2 (dentro do clone):
#     sh install.sh
#
# O que faz: clona (se fora do repo), confere o Python, cria o app Brain (Aplicativos) e abre a
# configuração guiada no navegador. Depois, é só abrir o Brain pelo ícone.
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

# mise recusa o mise.toml de um clone novo ("not trusted") antes de qualquer Python rodar — confia no do próprio repo.
if command -v mise >/dev/null 2>&1 && [ -f "$PWD/mise.toml" ]; then
    mise trust "$PWD/mise.toml" >/dev/null 2>&1 || \
        echo "⚠ não consegui confiar no mise.toml — rode:  mise trust \"$PWD\"  e depois  sh install.sh"
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

# Do clone ao app: semeia a instância (nunca sobrescreve), cria o app Brain e abre a configuração guiada
# no navegador. O wizard de terminal continua existindo para quem prefere (ou para IAs): ./brain setup
if ! ./brain init >/dev/null; then
    echo "✗ ./brain init falhou (veja o erro acima)."
    command -v mise >/dev/null 2>&1 && echo "  com mise:  mise trust \"$PWD\" && mise install  — depois:  sh install.sh"
    exit 1
fi
case "$(uname -s)" in
    Darwin|Linux) ./brain app install || echo "⚠ não consegui criar o app — abra com: ./brain open" ;;
esac
echo "→ abrindo a configuração do Brain no navegador…"
exec ./brain open --setup
