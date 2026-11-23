"""Ponte CLI do painel: `./brain serve` (fase 2 da UI).

O painel HTML aberto pela URL impressa no terminal (http://127.0.0.1:<porta>/#t=<token>)
executa exatamente as mesmas linhas que o TUI dispara — `tui/bridge.run_brain` — depois de
validar uma allowlist FECHADA de subcomandos. Fora da lista, 403. Sem token, 401.
Host diferente de 127.0.0.1, 403 (DNS rebinding). O noturno nunca serve.

`file://` continua sendo retrato somente-leitura (comandos são copiados p/ o terminal).
O token vive no fragmento da URL (não vai ao servidor) e é guardado no localStorage.
"""
from __future__ import annotations

import asyncio
import email.parser
import email.policy
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, util

INBOX_UPLOAD_MAX = 50 * 1024 * 1024  # 50 MB por upload para a inbox via ponte

# (comando, subcomando | None) que o painel emite — nada além disso passa pela ponte.
# Tudo que muda o mundo exterior continua nos gates do próprio CLI (--quote, aprovações).
ALLOWED: dict[str, set[str] | None] = {
    "action": {"open", "update", "close", "reopen", "merge", "drop"},
    "ask": {"answer", "drop"},
    "focus": {"approve", "apply", "plan", "sync"},
    "memory": {"providers"},                 # face Configurações: provedores (harness saiu — canal MCP é CLI, `brain harness`)
    "outbox": {"draft", "approve", "cancel"},
    "decision": {"add", "supersede"},              # supersede: o mesmo formulário da TUI (forms.py)
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
    "feedback": {"add", "push", "sync", "withdraw", "retract"},  # porta 7: o dono registra/publica/retira/retrata/confere pelo painel
    "doctor": None,                                 # cfg/saude 'testar online': leitura, sem escrita
}
DENY_HINT = "fora da allowlist da ponte — rode no terminal se for o caso"


def _default_update_cmd(inst, on_line) -> int:
    from .tui.bridge import FRAMEWORK
    env = {**os.environ, "BRAIN_HOME": str(inst.root)}
    proc = subprocess.Popen(
        [sys.executable, str(FRAMEWORK / "brain"), "update"],
        cwd=str(inst.root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        on_line(raw_line.rstrip("\r\n"))
    return proc.wait()


def _default_restart(state: _State) -> None:
    from .tui.bridge import FRAMEWORK
    port = state.port or (state.httpd.server_address[1] if state.httpd is not None else 8787)
    env = {**os.environ, "BRAIN_HOME": str(state.inst.root), "BRAIN_SERVE_TOKEN": state.token}
    if state.httpd is not None:
        try:
            state.httpd.shutdown()
        finally:
            state.httpd.server_close()
    unregister(state.inst)
    log = state.inst.logs / "serve.log"
    state.inst.logs.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        subprocess.Popen(
            [sys.executable, str(FRAMEWORK / "brain"), "serve", "--port", str(port)],
            cwd=str(state.inst.root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=fh,
            start_new_session=True,
        )


class _State:
    def __init__(self, inst, token: str, port: int = 0, update_cmd_fn=None, restart_fn=None):
        self.inst = inst
        self.token = token
        self.port = port
        self.httpd = None
        self.lock = threading.Lock()                    # comandos serializados: ledger é append-only, não concorrente
        self.agent_lock = threading.Lock()              # estado das rodadas do agente (1 por vez)
        self.agent_jobs: dict[str, dict] = {}
        self.update_lock = threading.Lock()             # atualização do framework via ponte (1 por vez)
        self.update_jobs: dict[str, dict] = {}
        self.update_active: str | None = None
        self.update_cmd_fn = update_cmd_fn or _default_update_cmd
        self.restart_fn = restart_fn or (lambda: _default_restart(self))


ICON_ROUTES = {"/brain.svg": "ICON_SVG", "/brain-mark.svg": "ICON_MARK", "/brain-hero.svg": "ICON_HERO"}


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


def _valid_inbox_filename(name: str | None) -> bool:
    """Aceita apenas nomes simples de arquivo, sem separadores, controles ou reservados."""
    if not isinstance(name, str) or not name or not name.strip():
        return False
    if name in (".", "..", ".keep.md"):
        return False
    if "/" in name or "\\" in name:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return False
    return Path(name).name == name


def _parse_inbox_multipart(ctype: str, body: bytes) -> tuple[str | None, bytes, str, str] | None:
    """Decodifica multipart/form-data com stdlib email.parser (sem cgi)."""
    clean_ct = ctype.replace("\r", "").replace("\n", "")
    if "multipart/form-data" not in clean_ct.lower() or "boundary=" not in clean_ct.lower():
        return None
    hdr = f"Content-Type: {clean_ct}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", errors="replace")
    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(hdr + body)
    if not msg.is_multipart():
        return None
    has_file = False
    raw_filename: str | None = None
    file_bytes = b""
    mode = "copy"
    source_path = ""
    for part in msg.iter_parts():
        if part.is_multipart():
            continue
        field = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = b""
        if field == "file" and not has_file:
            has_file = True
            raw_cd = next((v for k, v in part.raw_items() if k.lower() == "content-disposition"), "")
            raw_filename = "" if (part.defects or "\\" in raw_cd) else part.get_filename()
            file_bytes = payload
        elif field == "mode":
            mode = payload.decode("utf-8", errors="replace").strip() or "copy"
        elif field == "source_path":
            source_path = payload.decode("utf-8", errors="replace").strip()
    if not has_file:
        return None
    return raw_filename, file_bytes, mode, source_path


def _write_inbox_exclusive(dest_dir: Path, filename: str, data: bytes) -> Path | None:
    """Grava arquivo na inbox com O_CREAT|O_EXCL e sufixo -2, -3... (brainlib/rawsort.py:75-77)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()
    if (dest_resolved / filename).resolve().parent != dest_resolved:
        return None
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = dest_resolved / filename
    idx = 2
    while True:
        if candidate.resolve().parent != dest_resolved:
            return None
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            candidate = dest_resolved / f"{stem}-{idx}{suffix}"
            idx += 1
            continue
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            try:
                candidate.unlink()
            except OSError:
                pass
            raise
        return candidate


def _try_move_source(source_path: str, inst) -> bool:
    """Remove o original apenas quando é arquivo regular dentro de HOME e fora do vault/instância."""
    if not source_path:
        return False
    p = Path(source_path)
    if not p.is_absolute() or p.is_symlink():
        return False
    try:
        rp = p.resolve()
        home = Path.home().resolve()
        in_home = rp.is_relative_to(home)
        in_inst = rp.is_relative_to(inst.root.resolve()) or rp.is_relative_to(inst.vault.resolve())
        if not rp.is_file() or rp.is_symlink() or not in_home or in_inst:
            return False
        p.unlink()
        return True
    except OSError:
        return False


# Mover por busca: quando o navegador não entrega o caminho do arrastado (nunca entrega),
# a ponte procura o original NO DISCO e apaga após a cópia — só sob conteúdo idêntico byte
# a byte. Localizar por nome usa o índice do sistema quando existe (Spotlight/mdfind no
# macOS — a HOME de uma máquina de dev tem milhões de arquivos; varrer tudo levaria minutos)
# e cai numa varredura podada (sem ocultos/Library, com teto) quando não existe.
# `[serve].move_search` no brain.toml: true (padrão) | false (desliga; fica a pasta concedida
# no navegador) | ["Pasta", …] (varre só essas raízes, podadas).
MOVE_SEARCH_MAX_ENTRIES = 250_000        # teto da varredura; além disso a busca volta "incompleta"
MOVE_SEARCH_PRUNE = {"Library"}          # sob HOME: nunca entra (dado de app, nunca fonte de arraste)
MOVE_SEARCH_FALLBACK_DIRS = ("Desktop", "Downloads", "Documents")   # topo da varredura quando o índice falha
MDFIND_TIMEOUT = 10                       # segundos; índice travado não segura o drop


def _mdfind_candidates(name: str) -> list[str]:
    """Caminhos com esse NOME EXATO dentro de HOME, pelo índice do sistema (macOS).
    mdfind -name casa por substring — filtra basename idêntico. Sem mdfind: []."""
    import subprocess

    mdf = shutil.which("mdfind")
    if not mdf:
        return []
    try:
        out = subprocess.run([mdf, "-0", "-name", name], capture_output=True,
                             timeout=MDFIND_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    sep = "\0" if b"\0" in out else "\n"
    paths = out.decode("utf-8", errors="replace").split(sep)
    home = Path.home().resolve()
    hits: list[str] = []
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen or p.name != name:
            continue
        seen.add(rp)
        try:
            if not rp.is_relative_to(home):
                continue
        except OSError:
            continue
        hits.append(str(rp))
        if len(hits) >= 500:
            break
    return hits


def _move_search_roots(inst) -> list[Path]:
    """Raízes da busca de originais. Toda raiz resolve DENTRO de HOME e fora da instância."""
    raw = inst.cfg.get("serve", {}).get("move_search", True)
    if raw is False:
        return []
    home = Path.home().resolve()
    if raw is True:
        roots = [home]
    elif isinstance(raw, list):
        roots = []
        for entry in raw:
            if not isinstance(entry, str) or not entry.strip():
                continue
            p = Path(entry).expanduser()
            p = p if p.is_absolute() else home / p
            try:
                rp = p.resolve()
            except OSError:
                continue
            if rp != home and rp.is_relative_to(home) and rp.is_dir():
                roots.append(rp)
    else:
        roots = [home]
    out: list[Path] = []
    for rp in roots:
        try:
            if rp.is_relative_to(inst.root.resolve()) or rp.is_relative_to(inst.vault.resolve()):
                continue
        except OSError:
            continue
        if rp not in out:
            out.append(rp)
    return out


def _verify_candidates(paths: list[str], name: str, data: bytes, inst) -> list[dict]:
    """Filtra candidatos por nome: arquivo regular, não-symlink, fora da instância,
    tamanho igual e conteúdo IDÊNTICO byte a byte ao que caiu."""
    home = Path.home().resolve()
    hits: list[dict] = []
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen or p.name != name:
            continue
        seen.add(rp)
        try:
            in_inst = rp.is_relative_to(inst.root.resolve()) or rp.is_relative_to(inst.vault.resolve())
            if in_inst or not rp.is_relative_to(home) or p.is_symlink() or not rp.is_file():
                continue
            if rp.stat().st_size != len(data) or rp.read_bytes() != data:
                continue        # homônimo com outro conteúdo não é o original
            hits.append({"path": str(rp), "mtime": int(rp.stat().st_mtime),
                         "size": rp.stat().st_size})
        except OSError:
            continue
    hits.sort(key=lambda h: h["path"])
    return hits[:20]


def _walk_roots(roots: list[Path], name: str, data: bytes, inst) -> tuple[list[dict], bool]:
    """Varredura podada de raízes dadas. Não desce em ocultos nem em Library;
    pula a árvore da instância; teto de entradas (além dele, volta incompleta)."""
    import os

    home = Path.home().resolve()
    names: list[str] = []
    skip_trees = []
    try:
        skip_trees.append(str(inst.root.resolve()))
    except OSError:
        pass
    visited = 0
    complete = True
    stack: list[str] = [str(r) for r in roots]
    while stack:
        d = stack.pop()
        if any(d.startswith(s) for s in skip_trees):
            continue
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith("."):
                continue
            visited += 1
            if visited > MOVE_SEARCH_MAX_ENTRIES:
                complete = False
                stack.clear()
                break
            try:
                if e.is_dir(follow_symlinks=False):
                    if Path(d).resolve() == home and e.name in MOVE_SEARCH_PRUNE:
                        continue
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False) and e.name == name:
                    names.append(e.path)
            except OSError:
                continue
    return _verify_candidates(names, name, data, inst), complete


def _walk_candidates(name: str, data: bytes, inst) -> tuple[list[dict], bool]:
    return _walk_roots(_move_search_roots(inst), name, data, inst)


def _find_originals(name: str, data: bytes, inst) -> tuple[list[dict], bool, bool]:
    """Candidatos de original: primeiro pelo índice do sistema (instantâneo, HOME toda);
    índice vazio ou fresco demais → varredura de topo nas pastas de uso (rápida) no modo
    padrão, ou das raízes escolhidas em `[serve].move_search = [...]`. Todo candidato
    passa pela conferência de conteúdo — nome igual não basta.
    Retorna (candidatos, busca_completa, busca_executada)."""
    raw = inst.cfg.get("serve", {}).get("move_search", True)
    if raw is False:
        return [], True, False
    if raw is True:
        hits = _verify_candidates(_mdfind_candidates(name), name, data, inst)
        if hits:
            return hits, True, True
        home = Path.home().resolve()
        roots = [home / d for d in MOVE_SEARCH_FALLBACK_DIRS if (home / d).is_dir()]
        hits, complete = _walk_roots(roots, name, data, inst)
        return hits, complete, True
    hits, complete = _walk_candidates(name, data, inst)
    return hits, complete, True


def _inbox_copy_bytes(inst, inbox_name: str) -> bytes | None:
    """Bytes da cópia que acabou de entrar na inbox — régua para qualquer remoção."""
    p = inst.inbox / inbox_name
    try:
        if not _valid_inbox_filename(inbox_name) or not p.is_file():
            return None
        return p.read_bytes()
    except OSError:
        return None


def _delete_original_paths(paths: list[str], data: bytes, inst) -> tuple[list[str], list[dict]]:
    """Apaga originais escolhidos no painel — cada caminho revalidado NA HORA:
    arquivo regular, não-symlink, dentro de HOME, fora da instância/vault e com
    conteúdo idêntico byte a byte à cópia da inbox. Devolve (apagados, recusas)."""
    home = Path.home().resolve()
    removed, refused = [], []
    for raw in paths:
        p = Path(raw)
        try:
            rp = p.resolve()
            in_inst = rp.is_relative_to(inst.root.resolve()) or rp.is_relative_to(inst.vault.resolve())
            if not p.is_absolute() or p.is_symlink() or not rp.is_relative_to(home) or in_inst:
                refused.append({"path": raw, "reason": "fora do permitido"})
                continue
            if not rp.is_file() or rp.read_bytes() != data:
                refused.append({"path": raw, "reason": "conteúdo não bate com a cópia da inbox"})
                continue
            rp.unlink()
            removed.append(str(rp))
        except OSError:
            refused.append({"path": raw, "reason": "erro de acesso"})
    return removed, refused


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
            if path in ("/", "/index.html", "/portfolio.html", "/onboarding", *ICON_ROUTES):
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
                # F8: o wizard mora no painel — a rota antiga vira atalho para o modo primeira vez.
                # Rollback (plano onboarding-unification F8): voltar a servir o ONBOARDING_ASSET.
                self.send_response(302)
                self._sec()
                self.send_header("Location", "/#onboarding")
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif path in ICON_ROUTES:
                from . import launcher
                body = getattr(launcher, ICON_ROUTES[path]).read_bytes()
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
            elif path.startswith("/api/agent/job/"):
                jid = path.rsplit("/", 1)[1]
                with self.state.agent_lock:
                    raw = self.state.agent_jobs.get(jid)
                    j = {k: (list(v) if k == "lines" else v) for k, v in raw.items() if not k.startswith("_")} if raw else None
                self._json(200 if j else 404, {"ok": bool(j), "job": j})
            elif path.startswith("/api/update/job/"):
                jid = path.rsplit("/", 1)[1]
                with self.state.update_lock:
                    raw = self.state.update_jobs.get(jid)
                    snap = {
                        "ok": True,
                        "id": raw["id"],
                        "status": raw["status"],
                        "lines": list(raw["lines"]),
                        "exit_code": raw["exit_code"],
                        "restarting": raw["restarting"],
                        "diverged": raw["diverged"],
                        "version_before": raw["version_before"],
                        "version_after": raw["version_after"],
                    } if raw else None
                self._json(200 if snap else 404, snap or {"ok": False, "error": "atualização não encontrada"})
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

    def _read_json_body(self, cap: int = 64 * 1024) -> dict | None:
        if self.headers.get("Transfer-Encoding"):
            self._deny(411, "use Content-Length — a ponte não lê chunked")
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._deny(400, "Content-Length inválido")
            return None
        if not 0 <= n <= cap:
            self._deny(413 if n > cap else 400, "pedido fora do tamanho aceito")
            return None
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._deny(400, "JSON inválido")
            return None
        if not isinstance(req, dict):
            self._deny(400, "JSON inválido")
            return None
        return req

    def do_POST(self):                                  # noqa: N802
        try:
            if not self._guard():
                return
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/onboard/"):
                self._onboard_post(path.removeprefix("/api/onboard/"))
                return
            if path == "/api/agent":
                self._agent_post()
                return
            if path == "/api/update":
                self._update_post()
                return
            if path == "/api/inbox/remove":
                self._inbox_remove_post()
                return
            if path == "/api/inbox":
                self._inbox_post()
                return
            if path != "/api/cmd":
                self._deny(404, "rota desconhecida")
                return
            req = self._read_json_body()
            if req is None:
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

    def _inbox_post(self):
        """Recebe arquivo arrastado no painel (multipart/form-data) e grava em vault/RAW/inbox/."""
        if util.is_nightly():
            self._deny(403, "o noturno nunca recebe arquivos pelo painel")
            return
        raw_cl = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding") or raw_cl is None:
            self._deny(411, "use Content-Length — a ponte não lê chunked")
            return
        try:
            n = int(raw_cl)
        except ValueError:
            self._deny(400, "Content-Length inválido")
            return
        if n < 0:
            self._deny(400, "Content-Length inválido")
            return
        if n > INBOX_UPLOAD_MAX:
            self._deny(413, "arquivo grande demais (máximo 50 MB)")
            return
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in ctype.lower():
            self._deny(400, "Content-Type deve ser multipart/form-data")
            return
        raw_body = self.rfile.read(n)
        if len(raw_body) != n:
            self._deny(400, "corpo incompleto")
            return
        parsed = _parse_inbox_multipart(ctype, raw_body)
        if parsed is None:
            self._deny(400, "multipart/form-data inválido ou campo file ausente")
            return
        raw_filename, file_bytes, mode, source_path = parsed
        if mode not in ("copy", "move"):
            self._deny(400, "mode inválido — use copy ou move")
            return
        if not _valid_inbox_filename(raw_filename):
            self._deny(400, "nome de arquivo inválido — só caminhos dentro da inbox são aceitos")
            return
        assert raw_filename is not None
        with self.state.lock:
            inst = self._brain().inst
            saved_path = _write_inbox_exclusive(inst.inbox, raw_filename, file_bytes)
            if saved_path is None:
                self._deny(400, "nome de arquivo inválido — só caminhos dentro da inbox são aceitos")
                return
            if mode == "move":
                moved = _try_move_source(source_path, inst)
                moved_from = source_path if moved else None
                candidates: list[dict] = []
                search = False
                search_complete = True
                if not moved:
                    # navegador não entrega o caminho: procura o original no disco.
                    # Único candidato idêntico → apaga; mais de um → o painel pergunta.
                    hits, search_complete, search = _find_originals(raw_filename, file_bytes, inst)
                    if len(hits) == 1:
                        removed, _refused = _delete_original_paths([hits[0]["path"]], file_bytes, inst)
                        moved = bool(removed)
                        moved_from = hits[0]["path"] if moved else None
                    elif len(hits) > 1:
                        candidates = hits
                fallback_copy = not moved
            else:
                moved = False
                moved_from = None
                candidates = []
                search = False
                search_complete = True
                fallback_copy = False
        print(f"[serve] inbox: {saved_path.name} ({mode})", flush=True)
        self._json(200, {"ok": True, "name": saved_path.name, "original": raw_filename,
                         "moved": moved, "moved_from": moved_from, "fallback_copy": fallback_copy,
                         "candidates": candidates, "search": search, "search_complete": search_complete})

    def _inbox_remove_post(self):
        """Apaga originais escolhidos no diálogo de duplicados — cada caminho é
        revalidado na hora (bytes idênticos à cópia da inbox, dentro de HOME, fora
        da instância). O noturno nunca apaga; sem token, 401 (guard do do_POST)."""
        if util.is_nightly():
            self._deny(403, "o noturno nunca remove originais pelo painel")
            return
        req = self._read_json_body()
        if req is None:
            return
        inbox_name = req.get("inbox_name")
        paths = req.get("paths")
        if not isinstance(inbox_name, str) or not _valid_inbox_filename(inbox_name):
            self._deny(400, "inbox_name inválido")
            return
        if not isinstance(paths, list) or not paths or len(paths) > 20 or \
                any(not isinstance(p, str) or not p for p in paths):
            self._deny(400, "paths deve ser uma lista de 1 a 20 caminhos")
            return
        with self.state.lock:
            inst = self._brain().inst
            data = _inbox_copy_bytes(inst, inbox_name)
            if data is None:
                self._deny(404, "cópia da inbox não encontrada — arraste de novo")
                return
            removed, refused = _delete_original_paths(paths, data, inst)
        print(f"[serve] inbox/remove: {len(removed)} apagado(s), {len(refused)} recusado(s)", flush=True)
        self._json(200, {"ok": True, "removed": removed, "refused": refused})

    def _agent_post(self):
        """Executa uma ação ⚡ do agente (store.SYS_OPS) pelo mesmo caminho da TUI (`tui/bridge`)."""
        if util.is_nightly():
            self._deny(403, "o noturno nunca executa ações do agente pelo painel")
            return
        req = self._read_json_body()
        if req is None:
            return
        raw_action = req.get("action")
        if not isinstance(raw_action, str) or not raw_action.strip():
            self._deny(400, "ação do agente ausente")
            return
        raw_arg = req.get("arg")
        if raw_arg is not None and not isinstance(raw_arg, str):
            self._deny(400, "arg deve ser texto")
            return
        arg = (raw_arg or "").strip()
        if len(arg) > 1000:
            self._deny(400, "arg grande demais")
            return
        from .tui import bridge, store
        ops: dict[str, tuple[str, dict]] = {}
        for op in store.SYS_OPS:
            if op.get("agent"):
                short = op["agent"].lstrip("/")
                ops[short] = (short, op)
                ops[op["agent"]] = (short, op)
                ops[op["id"]] = (short, op)
        hit = ops.get(raw_action.strip())
        if not hit:
            self._deny(400, f"ação do agente desconhecida: {raw_action.strip()}")
            return
        action_name, op = hit
        arg_spec = op.get("arg")
        if arg_spec and arg_spec[2] and not arg:
            self._deny(400, f"argumento obrigatório para {op['agent']}: {arg_spec[0]}")
            return
        prompt = f"{op['agent']} {arg}".strip() if arg else op["agent"]
        with self.state.lock:
            inst = self._brain().inst
        with self.state.agent_lock:
            now = time.time()
            for old in [k for k, j in self.state.agent_jobs.items()
                        if j.get("status") != "running" and now - j.get("_started", 0) > 3600]:
                self.state.agent_jobs.pop(old, None)

            runner_cfg = inst.cfg.get("runner", {}) if isinstance(inst.cfg, dict) else {}
            try:
                timeout_min = int(runner_cfg.get("timeout_min", 10))
            except (TypeError, ValueError):
                timeout_min = 10
            running_max_age = max(600, timeout_min * 60 + 300)

            for j in self.state.agent_jobs.values():
                if j.get("status") == "running" and now - j.get("_started", 0) > running_max_age:
                    j["status"] = "error"
                    j["rc"] = 124
                    j.setdefault("lines", []).append("expirado: GC da ponte (job preso)")

            if any(j["status"] == "running" for j in self.state.agent_jobs.values()):
                self._deny(409, "Já existe uma ação do agente em execução.")
                return
            run_id = bridge.new_run_id()
            argv = bridge.agent_argv(inst.cfg, prompt, run_id)
            if not argv or (inst.cfg["runner"].get("command") and not shutil.which(argv[0])):
                self._deny(503, "Runner não configurado em [runner] no brain.toml.")
                return
            job_id = secrets.token_urlsafe(12)
            job = {
                "id": job_id,
                "action": action_name,
                "status": "running",
                "lines": [],
                "rc": None,
                "_started": time.time(),
            }
            self.state.agent_jobs[job_id] = job

        def _worker():
            info = bridge.RunInfo(id=run_id)
            rc = 1

            def on_line(ln: str) -> None:
                if not ln:
                    return
                with self.state.agent_lock:
                    job["lines"].append(ln)
                    if len(job["lines"]) > 2000:
                        del job["lines"][:-2000]

            try:
                rc = asyncio.run(bridge.run_agent(inst, argv, on_line, info))
                try:
                    bridge.record_run(inst, info, argv, prompt)
                except Exception as e:  # noqa: BLE001 — falha no log nunca trava o job
                    on_line(f"aviso ao registrar rodada: {e}")
            except Exception as e:  # noqa: BLE001
                on_line(f"erro inesperado: {e}")
                rc = 1
            finally:
                with self.state.agent_lock:
                    job["rc"] = rc
                    job["status"] = "done" if rc == 0 else "error"

        threading.Thread(target=_worker, daemon=True, name=f"serve-agent-{action_name}").start()
        print(f"[serve] ⚡ {prompt} → job={job_id}", flush=True)
        self._json(200, {"ok": True, "id": job_id, "action": action_name, "status": "running"})

    def _update_post(self):
        # Sem bloqueio por BRAIN_NIGHTLY: `brain update` sincroniza só o código do framework
        # (não grava eventos como dono nem toca o mundo exterior); serve já exige dono no boot.
        from . import upstream
        from .tui.bridge import FRAMEWORK
        with self.state.lock:
            inst = self._brain().inst
        with self.state.update_lock:
            active = self.state.update_active
            if active and (self.state.update_jobs.get(active) or {}).get("status") == "running":
                self._json(409, {"ok": False, "error": "atualização já em andamento", "job": active})
                return
            jid = secrets.token_urlsafe(12)
            job = {
                "id": jid,
                "status": "running",
                "lines": [],
                "exit_code": None,
                "restarting": False,
                "diverged": False,
                "version_before": upstream._version(FRAMEWORK),
                "version_after": None,
            }
            self.state.update_jobs[jid] = job
            self.state.update_active = jid
            cmd_fn = self.state.update_cmd_fn or _default_update_cmd
            restart_fn = self.state.restart_fn or (lambda: _default_restart(self.state))

        def _worker():
            def on_line(ln: str) -> None:
                with self.state.update_lock:
                    job["lines"].append(ln)
                    if len(job["lines"]) > 400:
                        del job["lines"][:-400]

            rc = 1
            try:
                rc = int(cmd_fn(inst, on_line))
            except Exception as e:  # noqa: BLE001
                on_line(f"erro inesperado: {e}")
                rc = 1
            finally:
                with self.state.update_lock:
                    job["exit_code"] = rc
                    if rc == 0:
                        # Lê do disco: o módulo importado no daemon ainda carrega a versão pré-pull.
                        job["version_after"] = upstream._version(FRAMEWORK)
                        job["status"] = "done"
                        job["restarting"] = True
                    else:
                        job["status"] = "error"
                        job["diverged"] = (rc == 2)
                        job["restarting"] = False
                    if self.state.update_active == jid:
                        self.state.update_active = None
            if rc == 0:
                t = threading.Timer(1.2, restart_fn)
                t.daemon = True
                t.start()

        threading.Thread(target=_worker, daemon=True, name=f"serve-update-{jid}").start()
        print(f"[serve] ↻ update → job={jid}", flush=True)
        self._json(200, {"ok": True, "job": jid})

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


def register(inst, url: str, port: int) -> bool:
    """Anota esta ponte como A ponte da instância (é o que o app e o `render --open` procuram).
    Se outra ponte desta instância já está anotada e no ar, não toma o lugar dela: uma segunda ponte
    (outra porta, teste) sobrescrevendo o registro deixava a principal órfã — viva, ocupando a porta,
    e invisível para o app, que caía no retrato. False = não registrou."""
    f = live_url_file(inst)
    try:
        row = json.loads(f.read_text(encoding="utf-8"))
        if int(row.get("pid", -1)) != os.getpid() and live_panel_url(inst):
            return False
    except (OSError, ValueError, TypeError):
        pass
    inst.logs.mkdir(parents=True, exist_ok=True)
    # 0600 já na criação: o arquivo carrega o token da ponte — write_text+chmod deixaria uma janela legível
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)                 # arquivo que já existia mantém o modo antigo no O_CREAT: fecha antes do token
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"url": url, "port": port, "pid": os.getpid(), "version": __version__}))
    return True


def unregister(inst) -> None:
    """Apaga o registro só se ele for desta ponte — nunca o de outra que continua no ar."""
    f = live_url_file(inst)
    try:
        row = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(row, dict) and row.get("pid") == os.getpid():
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def serve(inst, port: int = 8787, open_browser: bool = False) -> int:
    if util.is_nightly():
        raise util.BrainError("o noturno nunca serve — a ponte CLI exige o dono presente", 3)
    # a ponte que se substitui passa o token adiante — a página recarregada continua válida
    token = (os.environ.pop("BRAIN_SERVE_TOKEN", "") or "").strip()
    if len(token) < 16:
        token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.daemon_threads = True
    actual_port = httpd.server_address[1]
    state = _State(inst, token, actual_port)
    state.httpd = httpd
    _Handler.state = state
    url = f"http://127.0.0.1:{actual_port}/#t={token}"
    registered = register(inst, url, actual_port)
    print(f"✓ ponte CLI no ar (Ctrl+C encerra)\n  {url}\n  file:// continua retrato: comandos só copiam")
    if not registered:
        print("  ⚠ outra ponte desta instância já está no ar: esta não vira a ponte do app (só esta URL)")
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
        unregister(inst)
    return 0
