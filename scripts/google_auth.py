#!/usr/bin/env python3
"""Autorização OAuth do Google — roda UMA vez (interativa) e imprime o refresh token.

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

import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brainlib import config  # noqa: E402

SCOPES = ("https://www.googleapis.com/auth/calendar.events.owned "
          "https://www.googleapis.com/auth/drive.file")
PORT = 8917


class _Handler(BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):  # noqa: N802 — nome da stdlib
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Handler.code = (qs.get("code") or [None])[0]
        err = (qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<h2>✓ Autorizado — pode fechar esta aba e voltar ao terminal.</h2>" if _Handler.code
               else f"<h2>✗ Não autorizado ({err}) — rode de novo.</h2>")
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):  # noqa: A002 — assinatura da stdlib
        pass


def main() -> None:
    inst = config.load()
    env = config.load_env(inst)
    client_id, client_secret = env.get("GOOGLE_CLIENT_ID"), env.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("ERRO: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET ausentes em config/.env — veja guides/google-oauth.md")
    redirect = f"http://localhost:{PORT}"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "scope": SCOPES,
        "access_type": "offline", "prompt": "consent"})
    print("Abrindo o navegador (escopos: calendar.events.owned + drive.file)…")
    print(f"Se não abrir: {auth_url}\n")
    # Linux: xdg-open primeiro (`open` pode existir e não ser o launcher). macOS: cai em `open`.
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        subprocess.run([opener, auth_url], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("(não achei xdg-open/open — cole a URL acima no navegador)")
    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    for _ in range(600):
        if _Handler.code:
            break
        time.sleep(1)
    server.server_close()
    if not _Handler.code:
        sys.exit("ERRO: nenhum código recebido (timeout/abortado) — rode de novo")
    data = urllib.parse.urlencode({"code": _Handler.code, "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.loads(r.read().decode())
    refresh = tok.get("refresh_token")
    if not refresh:
        sys.exit("ERRO: o Google não devolveu refresh_token — rode de novo (prompt=consent garante)")
    print("\n=== COLE NO config/.env ===")
    print(f"GOOGLE_REFRESH_TOKEN={refresh}")
    print("(este terminal não grava nada; guarde em local seguro)")


if __name__ == "__main__":
    main()
