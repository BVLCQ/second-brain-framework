#!/bin/sh
# Sobe o decisor local. BRAIN_DIR vem do LaunchAgent / unit — este arquivo não leva caminho.
# A chave fica em $BRAIN_DIR/.decider/key (0600). O Python lê o arquivo; a chave não vai no argv deste processo.
set -u
ROOT="${BRAIN_DIR:?BRAIN_DIR ausente}"
exec "$ROOT/.decider/venv/bin/python" "$ROOT/services/decider_serve.py"
