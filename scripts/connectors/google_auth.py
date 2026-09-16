#!/usr/bin/env python3
"""Autorização OAuth do Google — roda UMA vez (interativa), gera o refresh token.

Uso:
  python3 scripts/connectors/google_auth.py

O que faz:
  1. Lê GOOGLE_CLIENT_ID/SECRET do config/.env (tipo "Desktop app" — sem redirect URI pra configurar).
  2. Abre o navegador pra você autorizar (escopos READ-ONLY de gmail+drive).
  3. Recebe o código num servidor localhost efêmero (loopback — método padrão do Google p/ apps desktop).
  4. Troca o código por um refresh token e o imprime NO TERMINAL (uma vez).

Você então cola no config/.env:
  GOOGLE_REFRESH_TOKEN=<valor impresso>

Guia completo (criar o OAuth client, publicar em produção): guides/google-oauth.md
NUNCA commite o .env. O refresh token é de longo prazo se o app estiver
publicado ("In production") — em "Testing" expira em 7 dias.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import common  # noqa: E402

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly "
          "https://www.googleapis.com/auth/drive.readonly")
PORT = 8917  # porta do loopback; livre e fora dos rangos comuns


class _Handler(BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):  # noqa: N802 — nome da stdlib
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.code = (qs.get("code") or [None])[0]
        err = (qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = _Handler.code is not None
        self.wfile.write(
            ("<h2>✓ Autorizado — pode fechar esta aba e voltar ao terminal.</h2>" if ok
             else f"<h2>✗ Não autorizado ({err}) — rode de novo.</h2>").encode())

    def log_message(self, format, *args):  # noqa: A002 — assinatura da stdlib
        pass


def main() -> None:
    common.load_env()
    import os
    client_id, client_secret = os.environ["GOOGLE_CLIENT_ID"], os.environ["GOOGLE_CLIENT_SECRET"]
    redirect = f"http://localhost:{PORT}"
    auth_url = ("https://accounts.google.com/o/oauth2/v2/auth?"
                + urllib.parse.urlencode({
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": redirect,
                    "scope": SCOPES,
                    "access_type": "offline",   # pede refresh token
                    "prompt": "consent",        # força emissão mesmo se já autorizado
                }))
    print("Abrindo o navegador para autorização (escopos READ-ONLY de Gmail+Drive)…")
    print(f"Se não abrir: {auth_url}\n")
    import shutil
    import subprocess
    opener = shutil.which("open") or shutil.which("xdg-open")
    if opener:
        subprocess.run([opener, auth_url], check=False)
    else:
        print("(não achei open/xdg-open — cole a URL acima no navegador)")

    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    import time
    for _ in range(600):  # espera até 10 min
        if _Handler.code:
            break
        time.sleep(1)
    server.server_close()
    if not _Handler.code:
        common.die("nenhum código recebido (timeout/abortado) — rode de novo")

    data = urllib.parse.urlencode({
        "code": _Handler.code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.loads(r.read().decode())
    refresh = tok.get("refresh_token")
    if not refresh:
        common.die("Google não devolveu refresh_token — rode de novo (prompt=consent garante)")
    print("\n=== COLE NO config/.env ===")
    print(f"GOOGLE_REFRESH_TOKEN={refresh}")
    print("(guarde em local seguro; este terminal não grava nada)")


if __name__ == "__main__":
    main()
