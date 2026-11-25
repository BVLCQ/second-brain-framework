#!/bin/sh
# Sobe o decisor local. BRAIN_DIR vem do LaunchAgent / unit — este arquivo não leva caminho.
# A chave fica em $BRAIN_DIR/.decider/key (0600), nunca no plist.
set -u
ROOT="${BRAIN_DIR:?BRAIN_DIR ausente}"
KIND="$(cat "$ROOT/.decider/kind" 2>/dev/null || echo mlx)"
KEY="$(cat "$ROOT/.decider/key" 2>/dev/null || true)"
if [ -z "$KEY" ]; then
  echo "decider: sem chave em $ROOT/.decider/key" >&2
  exit 1
fi
if [ "$KIND" = "vllm" ]; then
  BIN="$ROOT/.decider/venv/bin/hindsight-decision-serve"
else
  BIN="$ROOT/.decider/venv/bin/hindsight-decision-serve-mlx"
fi
exec "$BIN" "$ROOT/.decider/model" --port 8000 --api-key "$KEY"
