#!/usr/bin/env python3
"""Sobe o decisor local. A chave é lida do arquivo 0600 e não entra na linha de comando.

BRAIN_DIR vem do LaunchAgent / unit. MLX escuta em 127.0.0.1 por padrão; o vLLM não,
então o host é explícito nos dois. No MLX a chave fica só na memória do processo.
No vLLM o CLI oficial recoloca a chave no argv do `vllm serve` — o porto continua
preso ao loopback.
"""
import os
import sys
from pathlib import Path

root = Path(os.environ["BRAIN_DIR"])
key = (root / ".decider" / "key").read_text(encoding="utf-8").strip()
kind = (root / ".decider" / "kind").read_text(encoding="utf-8").strip()
model = str(root / ".decider" / "model")
if not key:
    sys.exit("decider: sem chave")
argv = [model, "--host", "127.0.0.1", "--port", "8000", "--api-key", key]
if kind == "vllm":
    bin_ = str(root / ".decider" / "venv" / "bin" / "hindsight-decision-serve")
    os.execv(bin_, ["hindsight-decision-serve", *argv])
from hindsight_decision.mlx_server import main
main(argv)
