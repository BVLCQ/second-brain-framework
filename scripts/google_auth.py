#!/usr/bin/env python3
"""Autorização OAuth do Google — roda UMA vez (interativa) e grava o refresh token direto no config/.env.

Fallback headless do `brain setup` (passo foco): o wizard absorveu este fluxo
(`brainlib/setup.google_refresh_token`) e grava direto no config/.env; este script
permanece para rodar fora do wizard (SSH, máquina remota).

Uso (na raiz da instância):
  python3 scripts/google_auth.py            # grava config/.env (0600); o terminal mostra só a confirmação
  python3 scripts/google_auth.py --print    # OPT-IN: imprime o token (só para máquina sem o config/.env desta instância)

Escopos pedidos — só as duas portas de escrita da constituição, nada de leitura
(leituras do Google passam pelos MCPs do seu agente):
  calendar.events.owned  → blocos de foco (cria/apaga SÓ eventos marcados pelo cérebro)
  drive.file             → backup (cria/apaga SÓ os próprios brain-backup-*.zip)

1. Lê GOOGLE_CLIENT_ID/SECRET do config/.env (client tipo "Desktop app").
2. Abre o navegador para você autorizar; recebe o código num servidor localhost efêmero.
3. Troca o código por um refresh token e grava em config/.env (0600). O valor nunca passa
   pelo terminal: a tela mostra só a confirmação e a impressão digital curta (#137).
Guia: guides/google-oauth.md
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brainlib import config, setup, util  # noqa: E402


def fingerprint(token: str) -> str:
    """Impressão digital curta e não reversível — serve para conferir qual token está gravado, sem expor o valor."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Autorização OAuth do Google (calendar.events.owned + drive.file).")
    ap.add_argument("--print", action="store_true",
                    help="imprime o token no terminal — só para máquina remota que não tem o config/.env desta instância")
    args = ap.parse_args(argv)
    try:
        inst = config.load()
    except util.BrainError as e:
        sys.exit(f"ERRO: {e}")
    env = config.load_env(inst)
    client_id, client_secret = env.get("GOOGLE_CLIENT_ID"), env.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("ERRO: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET ausentes em config/.env — veja guides/google-oauth.md")
    refresh = setup.google_refresh_token(client_id, client_secret, open_browser=True)
    if args.print:
        print("\n=== ATENÇÃO: segredo de longa vida — o terminal vira uma cópia dele; apague o scrollback depois ===")
        print(f"GOOGLE_REFRESH_TOKEN={refresh}")
        return 0
    setup.set_env(inst, {"GOOGLE_REFRESH_TOKEN": refresh})
    print(f"\n✓ GOOGLE_REFRESH_TOKEN gravado em {inst.env_file} (0600) — impressão digital {fingerprint(refresh)}")
    print("(o valor não aparece no terminal; confira com `./brain doctor --online`)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
