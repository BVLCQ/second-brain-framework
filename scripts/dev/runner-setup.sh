#!/usr/bin/env bash
# Runner do GitHub Actions deste repositório, na máquina do mantenedor: um container por worker
# (Docker — OrbStack no macOS), com acesso ao Docker do host para criar os containers dos jobs.
# O CI roda aqui e não consome minutos do GitHub.
#
#   scripts/dev/runner-setup.sh --tag m3                registra (se preciso) e sobe os workers
#   scripts/dev/runner-setup.sh --tag m3 --workers 2    quantos jobs rodam em paralelo nesta máquina
#   scripts/dev/runner-setup.sh --tag m3 --remove       descadastra os workers desta máquina e apaga tudo
#
# Pré-requisitos: Docker rodando; `gh` autenticado como administrador do repositório; a lista
# privada de termos em ~/.config/brain/public-denylist (modo 0600, um termo por linha) — ela vai
# para o volume nomeado `brain-public-denylist`, que só o job data-gate monta, como só leitura,
# e nunca vai ao repositório.
#
# É idempotente: rode de novo depois de reiniciar a máquina, de subir a versão da imagem
# (RUNNER_IMAGE) ou de mudar o número de workers. O token de registro (validade de 1h) só é
# necessário na primeira vez de cada worker; o registro fica salvo no diretório do worker.
#
# O runner é registrado só neste repositório, e o workflow só roda nele código que veio de dentro
# do repositório (PR de fork fica sem CI). Mantenha as duas coisas juntas: registrar este runner
# em outro repositório expõe a máquina ao código que esse repositório receber.
set -euo pipefail

REPO="${BRAIN_REPO:-BVLCQ/second-brain-framework}"
IMAGE="${RUNNER_IMAGE:-myoung34/github-runner:2.338.2-ubuntu-noble}"
WORKERS=2
TAG="$(hostname -s | tr '[:upper:]' '[:lower:]')"
REMOVE=0
BASE="$HOME/.github-runner"
DENYLIST="$HOME/.config/brain/public-denylist"
VOLUME="brain-public-denylist"

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed -e 's/^# \{0,1\}//' >&2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --remove) REMOVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; usage; exit 2 ;;
  esac
done

[[ "$TAG" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "--tag: só letras minúsculas, números e hífen (ex.: m3, m4)" >&2; exit 2; }
[[ "$WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "--workers: um número inteiro a partir de 1" >&2; exit 2; }

worker_dir() { echo "$BASE/brain-$TAG-$1"; }
worker_name() { echo "brain-$TAG-$1"; }
container_name() { echo "brain-runner-$TAG-$1"; }

gh_runners() {  # id, nome e estado de cada runner deste repositório que nasceu desta máquina
  gh api "repos/$REPO/actions/runners?per_page=100" \
    --jq ".runners[] | select(.name | startswith(\"brain-$TAG-\")) | \"\(.id) \(.name) \(.status)\""
}

fill_denylist_volume() {
  [ -s "$DENYLIST" ] || { echo "lista privada ausente ou vazia em $DENYLIST" >&2; exit 1; }
  docker volume create "$VOLUME" >/dev/null
  # o conteúdo atravessa por arquivo montado: não passa por argumento, variável nem log
  docker run --rm -v "$VOLUME:/destino" -v "$DENYLIST:/origem/lista:ro" python:3.12 \
    sh -c 'cp /origem/lista /destino/denylist && chmod 644 /destino/denylist'
}

remove_workers() {
  local line id name
  while read -r id name _; do
    [ -n "$id" ] || continue
    gh api -X DELETE "repos/$REPO/actions/runners/$id" >/dev/null && echo "descadastrado: $name"
  done < <(gh_runners)
  local d n
  for d in "$BASE"/brain-"$TAG"-[0-9]*; do
    [ -d "$d" ] || continue
    n="${d##*-}"
    docker rm -f "$(container_name "$n")" >/dev/null 2>&1 || true
    rm -rf "$d"
    echo "removido: $(container_name "$n") e $d"
  done
}

up_workers() {
  fill_denylist_volume
  local n d token="" need_token=0
  for n in $(seq 1 "$WORKERS"); do
    [ -f "$(worker_dir "$n")/runner/.runner" ] || need_token=1
  done
  if [ "$need_token" = 1 ]; then
    token=$(gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq .token) \
      || { echo "sem token de registro: o gh precisa estar autenticado como administrador de $REPO" >&2; exit 1; }
    [ -n "$token" ] || { echo "token de registro veio vazio" >&2; exit 1; }
  fi
  for n in $(seq 1 "$WORKERS"); do
    d="$(worker_dir "$n")"
    mkdir -p "$d/_work" "$d/runner"
    chmod 700 "$d" "$d/runner" # runner/ guarda o registro do worker (credencial dele): só o dono
    docker rm -f "$(container_name "$n")" >/dev/null 2>&1 || true
    local args=(
      docker run -d --name "$(container_name "$n")" --restart=always
      -e "REPO_URL=https://github.com/$REPO"
      -e "RUNNER_NAME=$(worker_name "$n")"
      -e LABELS=brain
      -e "RUNNER_WORKDIR=$d/_work"
      -e "CONFIGURED_ACTIONS_RUNNER_FILES_DIR=$d/runner"
      -e UNSET_CONFIG_VARS=true
      -e DISABLE_AUTO_UPDATE=true
      # com o registro salvo em disco, o container só sobe se prometer não descadastrar ao sair
      -e DISABLE_AUTOMATIC_DEREGISTRATION=true
      -v /var/run/docker.sock:/var/run/docker.sock
      -v "$d:$d"
    )
    if [ ! -f "$d/runner/.runner" ]; then
      (umask 077; printf 'RUNNER_TOKEN=%s\n' "$token" > "$d/registro.env")
      args+=(--env-file "$d/registro.env")
    fi
    "${args[@]}" "$IMAGE" >/dev/null
    rm -f "$d/registro.env"
    echo "no ar: $(worker_name "$n") ($(container_name "$n"))"
  done
}

if [ "$REMOVE" = 1 ]; then
  remove_workers
  exit 0
fi

command -v docker >/dev/null || { echo "docker não encontrado" >&2; exit 1; }
command -v gh >/dev/null || { echo "gh não encontrado" >&2; exit 1; }
gh api "repos/$REPO" --jq '.permissions.admin' | grep -qx true \
  || { echo "o gh autenticado não é administrador de $REPO" >&2; exit 1; }

up_workers

echo "aguardando os workers se conectarem a ${REPO}..."
online_ok=1
for _ in $(seq 1 15); do
  sleep 4
  [ "$(gh_runners | grep -c ' online$')" -ge "$WORKERS" ] && { online_ok=0; break; }
done
gh_runners | awk '{printf "  %s: %s\n", $2, $3}'
[ "$online_ok" = 0 ] || { echo "nem todos os workers ficaram online; veja o log do container: docker logs <nome>" >&2; exit 1; }
