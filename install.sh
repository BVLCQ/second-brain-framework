#!/bin/sh
# Brain — instalação: do clone ao app aberto no navegador.
#
#   caminho 1 (curl, máquina nova):
#     curl -fsSL https://raw.githubusercontent.com/BVLCQ/second-brain-framework/main/install.sh | sh -
#   caminho 2 (dentro do clone):
#     sh install.sh
#
# O que faz: clona (se fora do repo), instala o que faltar na máquina (git ·
# Homebrew · mise · Python do mise.toml · OrbStack/Docker), cria o app Brain
# (Aplicativos) e abre a configuração guiada no navegador. Depois, é só abrir
# o Brain pelo ícone.
# Instalação assistida por IA: o mesmo wizard com --yes/--only + `./brain doctor`
# como régua (setup.md na raiz é a receita executável completa para agentes).
#
# Bootstrap silencioso e idempotente (plano guides/plans/install-bootstrap.md):
# o script não faz perguntas e instala só o que falta. As portas do SO — senha
# sudo da sessão e a janela da Apple das Command Line Tools — são do sistema:
# esperamos com timeout e, ao falhar, imprimimos a receita manual (setup.md §0–§1).
set -e

REPO_URL="https://github.com/BVLCQ/second-brain-framework"
DEST="${1:-$HOME/Apps/second-brain-framework}"

OS="$(uname -s)"
say() { printf '→ %s\n' "$1"; }
ok() { command -v "$1" >/dev/null 2>&1; }
works() { "$1" --version >/dev/null 2>&1; }  # pega o stub git da Apple sem CLT
SUDO=""
[ "$(id -u)" = "0" ] || SUDO="sudo"
tmpscript="$(mktemp)"
cleanup() {
    if [ -n "$tmpscript" ]; then
        rm -f "$tmpscript"
        tmpscript=""
    fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 129' HUP

is_same_repo() {
    _isr_url="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    _isr_url="${_isr_url%/}"
    _isr_url="${_isr_url%.git}"
    _isr_want="$(printf '%s' "$REPO_URL" | tr '[:upper:]' '[:lower:]')"
    _isr_want="${_isr_want%/}"
    _isr_want="${_isr_want%.git}"
    case "$_isr_url" in
        "$_isr_want"|"git@github.com:bvlcq/second-brain-framework"|"ssh://git@github.com/bvlcq/second-brain-framework")
            return 0 ;;
        *)
            return 1 ;;
    esac
}

python_help() {
    echo "  macOS:  brew install mise  &&  mise install   (na raiz do repo)"
    echo "  ou:     brew install python@3.12"
    echo "  depois rode de novo:  sh install.sh   (receita completa: setup.md §0–§1)"
}

# --- Homebrew (macOS): silencioso (ruling D1); CLT é pré-requisito da Apple --
ensure_brew() {
    ok brew && return 0
    # caminhos canônicos mesmo quando o shell da sessão não carregou o perfil
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; return 0; fi
    if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; return 0; fi
    if ! xcode-select -p >/dev/null 2>&1; then
        say "Command Line Tools da Apple — confirme na janela que abrir (uma vez só)…"
        xcode-select --install >/dev/null 2>&1 || true
        i=0
        while ! xcode-select -p >/dev/null 2>&1; do
            i=$((i + 1))
            if [ "$i" -gt 120 ]; then
                echo "✗ Command Line Tools não concluíram em ~10 min."
                echo "  Conclua a instalação da Apple e rode de novo:  sh install.sh"
                return 1
            fi
            sleep 5
        done
    fi
    say "Homebrew (instalador oficial — pode pedir a senha da sessão)…"
    if ! curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$tmpscript" || \
       ! NONINTERACTIVE=1 /bin/bash "$tmpscript"; then
        echo "⚠ Homebrew não instalado — receita manual: setup.md §0."
        return 1
    fi
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
    if ! ok brew; then
        echo "⚠ Homebrew não instalado — receita manual: setup.md §0."
        return 1
    fi
}

# --- git: vem ANTES do clone (no macOS, binário do Homebrew — ruling D2) -----
ensure_git() {
    works git && return 0
    if [ "$OS" = "Darwin" ]; then
        if ensure_brew && { say "git (Homebrew)…"; brew install -q git; }; then
            return 0
        fi
        echo "⚠ não consegui instalar o git — instale manualmente (receita: setup.md §1) e rode de novo:  sh install.sh"
        exit 1
    elif ok apt-get; then
        say "git (apt)…"
        if ! $SUDO apt-get update -qq || ! $SUDO apt-get install -y -qq git; then
            echo "⚠ não consegui instalar o git — instale manualmente (receita: setup.md §1) e rode de novo:  sh install.sh"
            exit 1
        fi
    elif ok dnf; then
        say "git (dnf)…"
        if ! $SUDO dnf install -y -q git; then
            echo "⚠ não consegui instalar o git — instale manualmente (receita: setup.md §1) e rode de novo:  sh install.sh"
            exit 1
        fi
    elif ok yum; then
        say "git (yum)…"
        if ! $SUDO yum install -y -q git; then
            echo "⚠ não consegui instalar o git — instale manualmente (receita: setup.md §1) e rode de novo:  sh install.sh"
            exit 1
        fi
    elif ok apk; then
        say "git (apk)…"
        if ! $SUDO apk add --quiet git; then
            echo "⚠ não consegui instalar o git — instale manualmente (receita: setup.md §1) e rode de novo:  sh install.sh"
            exit 1
        fi
    else
        echo "⚠ git ausente e nenhum gerenciador conhecido."
        echo "  Instale o git (receita: setup.md §1) e rode de novo:  sh install.sh"
        exit 1
    fi
}

ensure_git

if [ ! -f "./brain" ] || [ ! -d "./brainlib" ]; then
    if [ -d "$DEST/.git" ]; then
        existing_origin="$(git -C "$DEST" remote get-url origin 2>/dev/null || true)"
        if is_same_repo "$existing_origin"; then
            echo "✓ repo já existe em $DEST"
        else
            echo "⚠ já existe outro repositório git em $DEST (origin: ${existing_origin:-ausente})."
            echo "  Escolha outra pasta:  sh install.sh /caminho/da/instancia"
            echo "  ou mova/remova $DEST antes de rodar o instalador de novo."
            exit 1
        fi
    else
        echo "→ clonando em $DEST"
        if ! git clone --quiet "$REPO_URL" "$DEST"; then
            echo "⚠ não consegui clonar o repositório em $DEST — verifique a conexão ou o caminho e rode de novo:  sh install.sh"
            exit 1
        fi
    fi
    cd "$DEST"
fi

# /tmp ↔ /private/tmp: caminho canônico evita trust registrado num alias e recusado no outro
cd "$(pwd -P)"

# --- mise (o Python vem do pin do mise.toml — versão nunca hardcoded) --------
if ! ok mise; then
    if [ "$OS" = "Darwin" ]; then
        if ensure_brew; then
            say "mise (Homebrew)…"
            brew install -q mise || echo "⚠ mise não instalado — sigo se já houver Python 3.11+ na máquina."
        else
            echo "⚠ mise não instalado (Homebrew indisponível) — sigo se já houver Python 3.11+ na máquina."
        fi
    else
        say "mise (instalador oficial)…"
        if ! curl -fsSL https://mise.jdx.dev/install.sh -o "$tmpscript" || ! sh "$tmpscript"; then
            echo "⚠ mise não instalado — sigo se já houver Python 3.11+ na máquina."
        fi
    fi
    # sessão desta execução enxerga o mise mesmo sem perfil configurado
    case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH"; export PATH ;; esac
fi

# mise recusa o mise.toml de um clone novo ("not trusted") antes de qualquer Python rodar — confia no do próprio repo.
if ok mise && [ -f "$PWD/mise.toml" ]; then
    mise trust >/dev/null 2>&1 || mise trust "$PWD" >/dev/null 2>&1 || \
        echo "⚠ não consegui confiar no mise.toml — rode:  mise trust \"$PWD\"  e depois  sh install.sh"
fi

if works python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    :
elif ok mise; then
    say "Python (mise install — a versão vem do mise.toml)…"
    if ! mise install; then
        echo "⚠ não consegui instalar o Python 3.11+ com o mise."
        python_help
        exit 1
    fi
else
    echo "⚠ Python 3.11+ não encontrado."
    python_help
    exit 1
fi

# --- contêiner (ruling D3): OrbStack no macOS, Docker Engine no Linux/WSL2 ---
# Falha aqui NÃO bloqueia: memória é configuração do wizard, não pré-requisito.
if [ "$OS" = "Darwin" ]; then
    if ! ok docker && [ ! -d /Applications/OrbStack.app ]; then
        say "OrbStack (runtime Docker)…"
        if ensure_brew; then
            brew install -q --cask orbstack || echo "⚠ OrbStack não instalado — o passo Memória do wizard aponta o caminho."
        else
            echo "⚠ OrbStack não instalado — o passo Memória do wizard aponta o caminho."
        fi
    fi
    if ! ok docker && [ -d /Applications/OrbStack.app ]; then
        say "primeiro lançamento do OrbStack (completa o comando docker)…"
        open -a OrbStack >/dev/null 2>&1 || true
    fi
else
    if ! ok docker; then
        say "Docker Engine (instalador oficial)…"
        if ! curl -fsSL https://get.docker.com -o "$tmpscript" || ! sh "$tmpscript"; then
            echo "⚠ Docker não instalado — o passo Memória do wizard aponta o caminho."
        elif $SUDO usermod -aG docker "$USER" 2>/dev/null; then
            echo "ℹ grupo docker adicionado — vale após re-login"
        fi
    fi
fi

rm -f "$tmpscript"
tmpscript=""

# Do clone ao app: semeia a instância (nunca sobrescreve), cria o app Brain e abre a configuração guiada
# no navegador. O wizard de terminal continua existindo para quem prefere (ou para IAs): ./brain setup
if ! ./brain init >/dev/null; then
    echo "✗ ./brain init falhou (veja o erro acima)."
    ok mise && echo "  com mise:  mise trust \"$PWD\" && mise install  — depois:  sh install.sh"
    exit 1
fi
case "$OS" in
    Darwin|Linux) ./brain app install || echo "⚠ não consegui criar o app — abra com: ./brain open" ;;
esac
echo "→ abrindo a configuração do Brain no navegador…"
exec ./brain open --setup
