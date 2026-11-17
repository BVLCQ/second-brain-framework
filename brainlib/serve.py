"""Ponte CLI do painel: `./brain serve` (fase 2 da UI).

O painel HTML aberto pela URL impressa no terminal (http://127.0.0.1:<porta>/#t=<token>)
executa exatamente as mesmas linhas que o TUI dispara — `tui/bridge.run_brain` — depois de
validar uma allowlist FECHADA de subcomandos. Fora da lista, 403. Sem token, 401.
Host diferente de 127.0.0.1, 403 (DNS rebinding). O noturno nunca serve.

`file://` continua sendo retrato somente-leitura (comandos são copiados p/ o terminal).
O token vive no fragmento da URL (não vai ao servidor) e é guardado no localStorage.
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, util

# (comando, subcomando | None) que o painel emite — nada além disso passa pela ponte.
# Tudo que muda o mundo exterior continua nos gates do próprio CLI (--quote, aprovações).
ALLOWED: dict[str, set[str] | None] = {
    "action": {"open", "update", "close", "reopen", "merge", "drop"},
    "ask": {"answer", "drop"},
    "focus": {"approve", "apply", "plan", "sync"},
    "memory": {"providers", "harness"},          # face Configurações: provedores + conectar/verificar harnesses
    "outbox": {"draft", "approve", "cancel"},
    "decision": {"add"},
    "delivery": None,                                   # posicional, sem subcomando
    "person": {"add", "alias", "update", "resolve"},   # resolve: só lê (quem é…?)
    "process": {"add", "update", "retire"},
    "area": {"add", "update"},
    "opportunity": {"status", "score", "update", "add", "promote", "evidence"},
    "doc": {"link", "unlink"},                     # documentos ligados a processo/oportunidade (Portfólio)
    "watch": {"add", "edit", "remove"},            # aba Fontes: o watch.toml é validado antes de gravar
    "plan": {"deliverable", "log", "add-goal", "add-project", "add-deliverable", "edit"},
    "progress": None,
    "publish": {"request", "approve", "cancel"},
    "share": None,
    "render": None,
    "search": None,
    "note": {"add"},
    "proposal": {"accept", "reject"},
    "feedback": {"add", "push", "sync"},          # porta 7: o dono registra/publica/confere pelo painel
    "doctor": None,                                 # cfg/saude 'testar online': leitura, sem escrita
}
DENY_HINT = "fora da allowlist da ponte — rode no terminal se for o caso"


class _State:
    def __init__(self, inst, token: str, port: int = 0):
        self.inst = inst
        self.token = token
        self.port = port
        self.lock = threading.Lock()                    # comandos serializados: ledger é append-only, não concorrente


def _allowed_argv(args: list[str]) -> bool:
    if not args:
        return False
    head = args[0]
    subs = ALLOWED.get(head, set())                     # ausente → negado
    if subs is None:
        return len(args) >= 1
    if not subs:
        return False
    return len(args) >= 2 and args[1] in subs


class _Handler(BaseHTTPRequestHandler):
    state: _State = None                                # type: ignore[assignment]
    timeout = 60                                        # socket: pedido travado não segura a thread p/ sempre

    # ── infra ─────────────────────────────────────────────────────────────
    def log_message(self, format, *a):                   # noqa: A002 — linha curta, sem o token
        print(f"[serve] {self.address_string()} {format % a}", flush=True)

    def _sec(self):
        """Cabeçalhos de segurança em TODA resposta: o painel vivo não pode ser
        embebido (clickjacking numa aba maliciosa dispararia escritas suas)."""
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _deny(self, code: int, msg: str):
        body = json.dumps({"ok": False, "error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._sec()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._sec()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._sec()
        self.end_headers()
        self.wfile.write(body)

    def _guard(self, token_required: bool = True) -> bool:
        """Host é 127.0.0.1 sempre (rebinding); token só no que não é o HTML de bootsnap.
        O painel lê o token do fragmento da URL (#t=… não vai ao servidor) — então as rotas de
        HTML carregam sem token (mesmo conteúdo que já está em FRESH/dashboard/) e a /api/* exige."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host != "127.0.0.1":
            self._deny(403, "host inesperado — a ponte só serve 127.0.0.1")
            return False
        if token_required:
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self.state.port}":
                self._deny(403, "origin de fora — a ponte só aceita o próprio painel")
                return False
        if token_required and not secrets.compare_digest(self.headers.get("X-Brain-Token") or "",
                                                         self.state.token):
            self._deny(401, "token ausente ou inválido — abra a URL que ./brain serve imprimiu")
            return False
        return True

    # ── rotas ─────────────────────────────────────────────────────────────
    def do_GET(self):                                   # noqa: N802
        try:
            path = self.path.split("?", 1)[0]
            if path == "/favicon.ico":                        # o navegador pede sempre; não é erro
                self.send_response(204)
                self._sec()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path in ("/", "/index.html", "/portfolio.html", "/onboarding", "/brain.svg"):
                if not self._guard(token_required=False):      # o HTML boota sem token; a /api/* exige
                    return
            elif not self._guard():
                return
            if path in ("/", "/index.html"):
                from . import render
                with self.state.lock:
                    m = render.view_model(self._brain())
                self._html(render.render_html(m))
            elif path == "/portfolio.html":
                from . import model, render, render_portfolio
                with self.state.lock:
                    m = model.build(self._brain())
                self._html(render.render_html(render_portfolio.html_payload(m), render.PORTFOLIO_ASSET))
            elif path == "/onboarding":
                from . import render
                self._html(render.ONBOARDING_ASSET.read_text(encoding="utf-8"))
            elif path == "/brain.svg":
                from . import launcher
                body = launcher.ICON_SVG.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self._sec()
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/onboard/state":
                from . import onboard
                with self.state.lock:
                    st = onboard.state(self._brain())
                self._json(200, {"ok": True, "state": st})
            elif path.startswith("/api/onboard/job/"):
                from . import onboard
                j = onboard.job(path.rsplit("/", 1)[1])
                self._json(200 if j else 404, {"ok": bool(j), "job": j})
            elif path == "/api/data":
                from . import render
                with self.state.lock:
                    m = render.view_model(self._brain())
                self._json(200, {"ok": True, "model": m})
            else:
                self._deny(404, "rota desconhecida")
        except Exception as e:                          # noqa: BLE001 — a ponte não morre por causa de um pedido
            print(f"[serve] erro interno: {e!r}", flush=True)
            self._deny(500, "erro interno — detalhe no terminal do serve")

    def do_POST(self):                                  # noqa: N802
        try:
            if not self._guard():
                return
            if self.path.split("?", 1)[0].startswith("/api/onboard/"):
                self._onboard_post(self.path.split("?", 1)[0].removeprefix("/api/onboard/"))
                return
            if self.path.split("?", 1)[0] != "/api/cmd":
                self._deny(404, "rota desconhecida")
                return
            if self.headers.get("Transfer-Encoding"):
                self._deny(411, "use Content-Length — a ponte não lê chunked")
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._deny(400, "Content-Length inválido")
                return
            if not 0 <= n <= 64 * 1024:
                self._deny(413 if n > 64 * 1024 else 400, "pedido fora do tamanho aceito")
                return
            try:
                req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._deny(400, "JSON inválido")
                return
            raw = str(req.get("cmd") or "").strip()
            if raw.startswith("brain "):
                raw = raw[5:].strip()
            if not raw or len(raw) > 4000:
                self._deny(400, "comando vazio ou grande demais")
                return
            try:
                args = shlex.split(raw)
            except ValueError:
                self._deny(400, "aspas sem fechar")
                return
            from .tui import bridge
            if not _allowed_argv(args):
                print(f"[serve] NEGADO: brain {shlex.join(args)}", flush=True)
                self._json(403, {"ok": False, "error": DENY_HINT, "display": "brain " + shlex.join(args)})
                return
            with self.state.lock:
                r = bridge.run_brain(self.state.inst, args, timeout=120)
            print(f"[serve] {bridge.display(args)} → rc={r.rc}", flush=True)
            self._json(200, {"ok": r.ok, "rc": r.rc, "out": (r.out or "").splitlines()[-40:],
                             "err": r.err, "display": bridge.display(args)})
        except Exception as e:                          # noqa: BLE001
            self._deny(500, f"erro interno: {e}")
            raise

    def _onboard_post(self, action: str):
        """Passos do onboarding (brainlib/onboard.py). O corpo NUNCA vai para o log: carrega API keys."""
        from urllib.parse import unquote
        from . import onboard
        if self.headers.get("Transfer-Encoding"):
            self._deny(411, "use Content-Length — a ponte não lê chunked")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._deny(400, "Content-Length inválido")
            return
        cap = onboard.UPLOAD_MAX if action == "upload" else 256 * 1024
        if not 0 <= n <= cap:
            self._deny(413 if n > cap else 400, "pedido fora do tamanho aceito")
            return
        body = self.rfile.read(n)
        try:
            with self.state.lock:
                b = self._brain()
                if action == "upload":
                    res = onboard.save_upload(b, unquote(self.headers.get("X-File-Name") or ""), body)
                else:
                    try:
                        data = json.loads(body.decode("utf-8") or "{}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        self._deny(400, "JSON inválido")
                        return
                    if not isinstance(data, dict):
                        self._deny(400, "JSON inválido")
                        return
                    res = onboard.run_action(b, action, data)
            print(f"[serve] onboarding: {action} → ok", flush=True)
            self._json(200, {"ok": True, **res})
        except util.BrainError as e:
            print(f"[serve] onboarding: {action} → recusado", flush=True)
            self._json(400, {"ok": False, "error": str(e)})

    def _brain(self):
        """Brain com a config relida do disco: o onboarding (e o painel) mudam o brain.toml com a ponte no ar —
        a instância guardada na partida ficaria com o dono e as fontes de antes."""
        from . import config
        from .core import Brain
        try:
            self.state.inst = config.reload(self.state.inst)
        except util.BrainError as e:
            print(f"[serve] config não recarregou: {e}", flush=True)
        return Brain(self.state.inst)


def live_url_file(inst) -> Path:
    """Onde a ponte no ar anota a URL com token (modo 0600, apagado ao encerrar).
    Quem abre o painel (render --open) usa isso para cair no MODO VIVO quando existe."""
    return inst.logs / "serve.json"


def stop_stale(inst) -> bool:
    """A ponte no ar é de outra versão do código (ficou rodando de antes de um `brain update`)? Encerra — quem chama
    sobe a nova. Só mata o pid anotado se o processo for mesmo um `brain serve`. True se encerrou uma."""
    import signal
    import subprocess
    import time
    f = live_url_file(inst)
    try:
        row = json.loads(f.read_text(encoding="utf-8"))
        pid = int(row["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if row.get("version") == __version__ or not live_panel_url(inst):
        return False
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    if "brain" not in cmd or " serve" not in cmd:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(40):                                   # até 4 s para liberar a porta
        if not live_panel_url(inst):
            return True
        time.sleep(0.1)
    return True


def live_panel_url(inst) -> str | None:
    """URL viva se (e só se) a ponte responde agora — arquivo velho não conta."""
    import socket
    f = live_url_file(inst)
    if not f.exists():
        return None
    try:
        row = json.loads(f.read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", int(row["port"])), timeout=0.3):
            return row["url"]
    except Exception:                                       # noqa: BLE001 — morto é morto
        return None


def serve(inst, port: int = 8787, open_browser: bool = False) -> int:
    if os.environ.get("BRAIN_NIGHTLY"):
        raise util.BrainError("o noturno nunca serve — a ponte CLI exige o dono presente", 3)
    token = secrets.token_urlsafe(24)
    _Handler.state = _State(inst, token, port)
    url = f"http://127.0.0.1:{port}/#t={token}"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.daemon_threads = True
    inst.logs.mkdir(parents=True, exist_ok=True)
    # 0600 já na criação: o arquivo carrega o token da ponte — write_text+chmod deixaria uma janela legível
    fd = os.open(live_url_file(inst), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"url": url, "port": port, "pid": os.getpid(), "version": __version__}))
    print(f"✓ ponte CLI no ar (Ctrl+C encerra)\n  {url}\n  file:// continua retrato: comandos só copiam")
    if open_browser:
        util.open_url(url)
    def _sair(*_a):
        raise KeyboardInterrupt                  # SIGTERM/SIGINT caem no mesmo caminho de limpeza

    import signal
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _sair)
        except (ValueError, OSError):           # não é a thread principal (testes): ignora
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ ponte encerrada")
    finally:
        httpd.server_close()
        try:
            live_url_file(inst).unlink()
        except FileNotFoundError:
            pass
    return 0
