#!/usr/bin/env python3
"""Autorização OAuth do Google — roda UMA vez (interativa) e imprime o refresh token.

Fallback headless do `brain setup` (passo foco): o wizard absorveu este fluxo
(`brainlib/setup.google_refresh_token`) e grava direto no config/.env; este script
permanece para rodar fora do wizard (SSH, máquina remota) — aqui o token é impresso
no terminal para você colar.

Uso (na raiz da instância):
  python3 scripts/google_auth.py

Escopos pedidos — só as duas portas de escrita da constituição, nada de leitura
(leituras do Google passam pelos MCPs do seu agente):
  calendar.events.owned  → blocos de foco (cria/apaga SÓ eventos marcados pelo cérebro)
  drive.file             → backup (cria/apaga SÓ os próprios brain-backup-*.zip)

1. Lê GOOGLE_CLIENT_ID/SECRET do config/.env (client tipo "Desktop app").
2. Abre o navegador para você autorizar; recebe o código num servidor localhost efêmero.
3. Troca o código por um refresh token e o imprime NO TERMINAL (uma vez).
Cole em config/.env: GOOGLE_REFRESH_TOKEN=<valor>. Guia: guides/google-oauth.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brainlib import config, setup  # noqa: E402


def main() -> None:
    inst = config.load()
    env = config.load_env(inst)
    client_id, client_secret = env.get("GOOGLE_CLIENT_ID"), env.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("ERRO: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET ausentes em config/.env — veja guides/google-oauth.md")
    refresh = setup.google_refresh_token(client_id, client_secret, open_browser=True)
    print("\n=== COLE NO config/.env ===")
    print(f"GOOGLE_REFRESH_TOKEN={refresh}")
    print("(este terminal não grava nada; guarde em local seguro)")


if __name__ == "__main__":
    main()
