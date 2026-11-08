"""Setup assistido — `brain setup` (guides/setup.md · plano guides/plans/setup-wizard.md).

Um motor de passos, três frentes (CLI agora; TUI e painel depois): cada passo é declarativo —
id, título, `status()` derivado de config/doctor (sem arquivo de estado novo), `run()`.
Estrutura, não vida: o CONTEÚDO (PROFILE, goals, pessoas) continua da entrevista `/init`.

Idempotente e re-executável: `brain setup` mostra o estado de cada passo (feito / pendente /
desligado) e pula o pronto; `--only id1,id2` re-visita; `--yes` roda não-interativo com defaults
(caminho das IAs: um agente pode conduzir a instalação e validar com `brain doctor`).

Regras herdadas da constituição: segredo entra mascarado (getpass), grava em `config/.env`
(0600, preservando chaves existentes), valida na hora o que dá para validar sem gastar
(ping GitHub, health do Hindsight), nunca ecoa valor em log/tela. Porta opcional é OFF por
padrão. O modo `full` de memória é porta de saída de dados: exige o "ok" literal do dono,
mesmo com --yes.
"""
from __future__ import annotations

import argparse
import getpass
import html
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from . import config, util

FRAMEWORK = Path(__file__).resolve().parent.parent


# ── UI (interativa × --yes) ─────────────────────────────────────────────────
class ConsoleUI:
    interactive = True

    def say(self, msg: str) -> None:
        print(msg)

    def ask(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        try:
            r = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            r = ""
        return r or default

    def choice(self, prompt: str, options: list[str], default: str) -> str:
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}" + ("  ← default" if o == default else ""))
        r = self.ask(prompt, default)
        if r in options:
            return r
        if r.isdigit() and 1 <= int(r) <= len(options):
            return options[int(r) - 1]
        return default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        d = "S/n" if default else "s/N"
        r = self.ask(f"{prompt} ({d})", "s" if default else "n")
        return r.lower() in ("s", "sim", "y", "yes")

    def secret(self, prompt: str) -> str:
        return getpass.getpass(prompt + " (não aparece na tela): ")


class AutoUI(ConsoleUI):
    """--yes: defaults sensatos, zero interação. Segredo e gate literal do full seguem exigindo o dono."""

    interactive = False

    def ask(self, prompt: str, default: str = "") -> str:
        print(f"{prompt}: {default}")
        return default

    def choice(self, prompt: str, options: list[str], default: str) -> str:
        print(f"{prompt}: {default}")
        return default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        print(f"{prompt}: {'s' if default else 'n'}")
        return default

    def secret(self, prompt: str) -> str:
        raise util.BrainError(f"{prompt}: segredo não pode ser pedido em modo --yes — grave no config/.env "
                              "e rode de novo (ou rode o setup interativo)", code=4)


# ── helpers ─────────────────────────────────────────────────────────────────
def set_env(inst, updates: dict[str, str]) -> list[str]:
    """Grava chaves no config/.env preservando as existentes (0600). Nunca imprime valores."""
    path = inst.env_file
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    have = {}
    out = []
    for ln in lines:
        k, sep, v = ln.partition("=")
        if sep and not k.strip().startswith("#"):
            have[k.strip()] = ln
            out.append(ln)
        else:
            out.append(ln)
    changed = []
    for k, v in updates.items():
        if v is None or v == "":
            continue
        if k in have:
            if have[k] != f"{k}={v}":
                out[out.index(have[k])] = f"{k}={v}"
                changed.append(k)
        else:
            out.append(f"{k}={v}")
            changed.append(k)
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        util.atomic_write(path, "\n".join(out) + "\n")
        os.chmod(path, 0o600)
    return changed


def brain_command_status(root: Path) -> str | None:
    """Caminho do `brain` no PATH se ele resolve para o brain desta instância; senão None."""
    which = shutil.which("brain")
    if not which:
        return None
    try:
        if Path(which).resolve() == (root / "brain").resolve():
            return which
    except OSError:
        return None
    return None


def install_brain_command(root: Path, ui: ConsoleUI) -> str:
    """Cria o comando `brain` (symlink num diretório do PATH). Devolve o caminho criado."""
    home_local = Path.home() / ".local" / "bin"
    candidates = [home_local] + [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    target = next((c for c in candidates if c.is_dir() and os.access(c, os.W_OK)), None)
    if target is None:
        home_local.mkdir(parents=True, exist_ok=True)
        target = home_local
    link = target / "brain"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(root / "brain")
    hint = "" if str(target) in os.environ.get("PATH", "") else f" — adicione {target} ao PATH"
    ui.say(f"✓ comando `brain` → {link}{hint}")
    return str(link)


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 127, str(e)


def docker_available() -> bool:
    return _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)[0] == 0


def hindsight_health(url: str, timeout: int = 4) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def wait_hindsight(url: str, seconds: int = 120) -> bool:
    for _ in range(seconds):
        if hindsight_health(url) is not None:
            return True
        time.sleep(2)
    return False


def compose_up(mode: str, ui: ConsoleUI, env_file: Path | None = None) -> bool:
    """Sobe o Hindsight (OrbStack/docker). embed = base; full = base + override com --env-file."""
    cmd = ["docker", "compose"]
    if mode == "full" and env_file is not None:
        cmd += ["--env-file", str(env_file)]
    cmd += ["-f", str(FRAMEWORK / "services" / "compose.yaml")]
    if mode == "full":
        cmd += ["-f", str(FRAMEWORK / "services" / "compose.full.yaml")]
    cmd += ["up", "-d"]
    code, out = _run(cmd, cwd=FRAMEWORK, timeout=300)
    if code != 0:
        ui.say(f"✗ docker compose falhou: {out[:300]}")
        return False
    return True


def lmstudio_up() -> bool:
    """O LM Studio (embeddings bge-m3) está respondendo em :1234?"""
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def github_token_ok(token: str) -> bool:
    req = urllib.request.Request("https://api.github.com/user", headers={"Authorization": f"Bearer {token}",
                                                                        "User-Agent": "brain-setup"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def nightly_installed() -> bool:
    try:
        from . import runner
        if runner._use_launchd():
            return runner._launchd_plist().exists()
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return runner.MARK in (r.stdout or "")
    except Exception:                                   # noqa: BLE001 — status é informativo
        return False


# ── OAuth Google (lógica absorvida do scripts/google_auth.py — só as portas de escrita) ──
SCOPES = ("https://www.googleapis.com/auth/calendar.events.owned "
          "https://www.googleapis.com/auth/drive.file")
OAUTH_PORT = 8917


class _OAuthHandler(BaseHTTPRequestHandler):
    code: str | None = None
    denied: str | None = None
    expected_state: str = ""

    def do_GET(self):  # noqa: N802 — nome da stdlib
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (qs.get("code") or [None])[0]
        err = (qs.get("error") or [None])[0]
        same = secrets.compare_digest((qs.get("state") or [""])[0], _OAuthHandler.expected_state)
        ok = bool(code) and same
        if ok:
            _OAuthHandler.code = code
        elif same and err:
            _OAuthHandler.denied = err
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<h2>✓ Autorizado — pode fechar esta aba e voltar ao terminal.</h2>" if ok
               else f"<h2>✗ Não autorizado ({html.escape(str(err or 'sem código/state'))} — rode de novo.</h2>")
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):  # noqa: A002 — assinatura da stdlib
        pass


def google_refresh_token(client_id: str, client_secret: str, open_browser: bool = True,
                         wait_s: int = 300) -> str:
    """Fluxo OAuth loopback (calendar.events.owned + drive.file). Devolve o refresh token —
    o chamador grava no .env; o valor não é impresso."""
    redirect = f"http://localhost:{OAUTH_PORT}"
    _OAuthHandler.code = _OAuthHandler.denied = None
    _OAuthHandler.expected_state = secrets.token_urlsafe(24)
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": _OAuthHandler.expected_state})
    if open_browser:
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.run([opener, auth_url], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Abrindo o navegador para autorizar (escopos: calendar.events.owned + drive.file)…")
    print(f"Se não abrir: {auth_url}\n")
    server = HTTPServer(("127.0.0.1", OAUTH_PORT), _OAuthHandler)
    threading.Thread(target=lambda: (setattr(server, "timeout", 1), _pump(server, wait_s)), daemon=True).start()
    deadline = time.time() + wait_s
    while not (_OAuthHandler.code or _OAuthHandler.denied) and time.time() < deadline:
        time.sleep(1)
    server.server_close()
    if not _OAuthHandler.code:
        raise util.BrainError(f"OAuth: nenhum código recebido ({_OAuthHandler.denied or 'timeout'}) — rode de novo",
                              code=3)
    data = urllib.parse.urlencode({"code": _OAuthHandler.code, "client_id": client_id,
                                   "client_secret": client_secret, "redirect_uri": redirect,
                                   "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.loads(r.read().decode())
    if not tok.get("refresh_token"):
        raise util.BrainError("OAuth: o Google não devolveu refresh_token — rode de novo (prompt=consent)", code=3)
    return tok["refresh_token"]


def _pump(server: HTTPServer, seconds: int) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        server.handle_request()


# ── os passos ───────────────────────────────────────────────────────────────
def _sections_in_file(inst) -> set[str]:
    import re
    path = inst.config_dir / "brain.toml"
    if not path.exists():
        return set()
    return {m.group(1) for m in re.finditer(r"^\[(\w+)\]", path.read_text(encoding="utf-8"), re.M)}


def _st_instancia(brain) -> str:
    inst = brain.inst
    if not (inst.config_dir / "brain.toml").exists():
        return "pending"
    zones = [inst.vault / z for z in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH")]
    if not all(z.exists() for z in zones):
        return "pending"
    if "(demo)" in inst.cfg["owner"]["name"]:
        return "warn"
    return "done"


def _run_instancia(brain, ui) -> None:
    from . import cli as _cli
    inst = brain.inst
    if "(demo)" in inst.cfg["owner"]["name"] and ui.confirm("Esta instância é o DEMO — arquivar o vault "
                                                            "atual e nascer de novo? (o demo é regenerável)", False):
        stamp = time.strftime("%Y-%m-%d")
        archived = inst.vault.with_name(inst.vault.name + f"-demo-{stamp}")
        n = 2
        while archived.exists():
            archived = inst.vault.with_name(f"{inst.vault.name}-demo-{stamp}-{n}")
            n += 1
        inst.vault.rename(archived)
        # o config também é do demo (dono "Você (demo)", portas fictícias): arquiva junto para o
        # init semear do zero. O .env NÃO vai — segredo do dono, independe do demo.
        (archived / "config-do-demo").mkdir(exist_ok=True)
        for name in ("brain.toml", "watch.toml"):
            src = inst.config_dir / name
            if src.exists():
                src.rename(archived / "config-do-demo" / name)
        ui.say(f"demo arquivado em {archived.name} (+ config do demo)")
    if not (inst.config_dir / "brain.toml").exists() or "(demo)" in inst.cfg["owner"]["name"]:
        owner_id = ui.ask("Seu id (slug, ex.: brian)", util.slugify(inst.cfg["owner"]["id"], 32))
        owner_name = ui.ask("Seu nome", owner_id)
        args = argparse.Namespace(owner_id=owner_id, owner_name=owner_name, alias=None, email=None)
        _cli.cmd_init(args, brain)
    else:
        ui.say("✓ instância já semeada")


def _st_identidade(brain) -> str:
    return "done" if brain.owner in brain.state.people else "pending"


def _run_identidade(brain, ui) -> None:
    if brain.owner in brain.state.people:
        ui.say("✓ dono já registrado no ledger")
        return
    name = ui.ask("Nome do dono (para o ledger)", brain.inst.cfg["owner"]["name"])
    brain.record_one({"type": "person.added", "id": brain.owner, "by": "owner",
                      "data": {"name": name, "aliases": [], "relation": "dono do cérebro"}})
    ui.say(f"✓ pessoa {brain.owner} registrada")


def _st_rotina(brain) -> str:
    return "done" if "work" in _sections_in_file(brain.inst) else "pending"


def _run_rotina(brain, ui) -> None:
    cfg = brain.inst.cfg
    tz = ui.ask("Fuso (ex.: America/Sao_Paulo)", cfg["timezone"])
    start = ui.ask("Início do expediente", cfg["work"]["start"])
    end = ui.ask("Fim do expediente", cfg["work"]["end"])
    config.set_keys(brain.inst, "owner", {"timezone": tz})
    config.set_keys(brain.inst, "work", {"start": start, "end": end})
    brain.inst = config.load(brain.inst.root)
    brain.reload()
    ui.say(f"✓ rotina: {tz} · {start}–{end} (almoço e detalhes finos: config/brain.toml [work])")


def _st_comando(brain) -> str:
    return "done" if brain_command_status(brain.inst.root) else "pending"


def _run_comando(brain, ui) -> None:
    if brain_command_status(brain.inst.root):
        ui.say(f"✓ `brain` já no PATH ({brain_command_status(brain.inst.root)})")
        return
    install_brain_command(brain.inst.root, ui)


def _st_foco(brain) -> str:
    cfg = brain.inst.cfg
    if cfg["focus"]["mode"] != "google":
        return "done"          # ics = zero config
    env = config.load_env(brain.inst)
    ok = all(env.get(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"))
    return "done" if ok else "pending"


def _run_foco(brain, ui) -> None:
    mode = ui.choice("Foco: modo do calendário", ["ics", "google"], brain.inst.cfg["focus"]["mode"])
    if mode != "google":
        config.set_keys(brain.inst, "focus", {"mode": "ics"})
        brain.inst = config.load(brain.inst.root)
        ui.say("✓ foco em modo ics (arquivo local, zero configuração)")
        return
    env = config.load_env(brain.inst)
    client_id = env.get("GOOGLE_CLIENT_ID") or ui.ask("GOOGLE_CLIENT_ID (console.cloud.google.com, client Desktop)")
    secret = env.get("GOOGLE_CLIENT_SECRET") or ui.secret("GOOGLE_CLIENT_SECRET")
    set_env(brain.inst, {"GOOGLE_CLIENT_ID": client_id, "GOOGLE_CLIENT_SECRET": secret})
    if env.get("GOOGLE_REFRESH_TOKEN"):
        ui.say("✓ GOOGLE_REFRESH_TOKEN já existe no .env — OAuth pulado")
    else:
        refresh = google_refresh_token(client_id, secret, open_browser=ui.interactive)
        set_env(brain.inst, {"GOOGLE_REFRESH_TOKEN": refresh})
        ui.say("✓ refresh token gravado no config/.env (não impresso)")
    config.set_keys(brain.inst, "focus", {"mode": "google"})
    brain.inst = config.load(brain.inst.root)
    brain.reload()
    ui.say("✓ foco em modo google (porta 1) — valide com `brain focus plan`")


def _st_noturno(brain) -> str:
    return "done" if nightly_installed() else "pending"


def _run_noturno(brain, ui) -> None:
    if nightly_installed():
        ui.say("✓ noturno já agendado")
        return
    hh = ui.ask("Horário do noturno (HH:MM)", "05:30")
    code, out = _run([sys.executable, str(FRAMEWORK / "brain"), "schedule", "install", "--time", hh],
                     cwd=brain.inst.root)
    ui.say(out if code == 0 else f"✗ {out[:200]}")


def _st_tui(brain) -> str:
    return "done" if (FRAMEWORK / ".venv-tui" / "bin" / "python").exists() else "pending"


def _run_tui(brain, ui) -> None:
    if _st_tui(brain) == "done":
        ui.say("✓ TUI pronta (.venv-tui)")
        return
    ui.say("instalando o venv do TUI (versões e hashes travados)…")
    code, out = _run([sys.executable, str(FRAMEWORK / "brain"), "tui", "--setup"], timeout=600)
    ui.say(("✓ TUI instalada — `brain tui` abre" if code == 0 else f"✗ {out[:300]}"))


def _st_memoria(brain) -> str:
    from . import memory
    m = memory.mode(brain.inst.cfg["memory"])
    return "off" if m == "none" else "done"


def _providers_step(brain, ui, slots: list[str]) -> bool:
    """Escolha de provedores por slot (plano memory-providers.md) — wizard e re-edição usam o mesmo
    caminho do `brain memory providers set`. Devolve True se o .env mudou (container a recriar)."""
    from . import providers as prov
    st = prov.stack(brain)
    env_keys = config.load_env(brain.inst)
    labels = {"llm": "LLM (extração · consolidação · mental models)",
              "embeddings": "embeddings", "reranker": "reranker"}
    changed = False
    for slot in slots:
        cur = st[slot]["provider"]
        reg = prov.PROVIDERS[slot]
        opts = list(reg)
        default = cur if cur in opts else ("off" if slot == "reranker" else
                                           "local" if slot == "embeddings" else "anthropic")
        p = ui.choice(f"Provedor de {labels[slot]}", opts, default)
        info = reg[p]
        if p in ("local", "off"):
            res = prov.set_slot(brain, slot, p)
            ui.say(f"✓ {slot}: {info['label']}")
            changed = changed or bool(res["env"])
            continue
        if slot != "llm":
            ui.say(f"  ☁ nuvem: o texto do vault vai à API do provedor para "
                   f"{'vetorizar' if slot == 'embeddings' else 'reranquear'} — mesmo gate de egress do plano §4.3")
        key_env = info.get("key_env", "")
        key = ""
        if key_env and not env_keys.get(key_env):
            key = ui.secret(f"API key ({key_env})")
        rec = info.get("models") or (info.get("model") and {"default": info["model"]}) or {}
        models, model, base_url = None, "", ""
        if slot == "llm" and rec and ui.confirm("Usar os modelos recomendados por operação (cenário B do plano)?", True):
            models = dict(rec)
        elif slot == "llm":
            model = ui.ask("Modelo default (vazio = padrão do provedor)", info.get("model", ""))
            cheap = ui.ask("Modelo BARATO p/ extração+consolidação (vazio = default)", "")
            if cheap:
                models = {"retain": cheap, "consolidation": cheap}
        elif p == "custom":
            model = ui.ask("Modelo", "")
        if p == "custom" or (slot == "llm" and p in ("zai", "fireworks")):
            base_url = ui.ask("Base URL", info.get("base_url", ""))
        res = prov.set_slot(brain, slot, p, model=model, models=models, base_url=base_url, key=key)
        ui.say(f"✓ {slot} → {res['label']}" + (" (chave gravada no config/.env)" if key else ""))
        if res["rebuild_needed"]:
            ui.say("⚠ embeddings mudaram: vetores antigos são incompatíveis — `brain memory rebuild` "
                   "re-deriva tudo do vault depois do wizard")
        changed = changed or bool(res["env"])
    return changed


def _run_memoria(brain, ui, mode_hint: str | None = None) -> None:
    from . import memory
    mem = brain.inst.cfg["memory"]
    url = mem["url"]
    cur = memory.mode(mem)
    mode = mode_hint or ui.choice("Memória: modo", ["none", "embed", "full"], cur if cur != "none" else "embed")
    if mode == "none":
        memory._apply_mode(brain, "none")
        return
    if not docker_available() and hindsight_health(url) is None:
        ui.say("⚠ Docker/OrbStack não encontrado e Hindsight fora do ar — instale o OrbStack "
               "(orbstack.dev) e rode `brain setup --only memoria` de novo. Os demais passos seguem.")
        if not ui.interactive:
            return
    if mode == "full":
        gate = ui.ask('Modo full: texto do vault (reuniões, Slack, documentos) irá para a API de LLM '
                      'com a SUA chave (plano da memória §4.3). Digite "ok" para aceitar', "")
        if gate.strip().lower() != "ok":
            ui.say("✗ sem o \"ok\" literal o modo full não é gravado — nada mudou")
            return
    env_file = brain.inst.env_file if brain.inst.env_file.exists() else None
    slots = ["llm", "embeddings", "reranker"] if mode == "full" else ["embeddings", "reranker"]
    env_changed = _providers_step(brain, ui, slots)
    mem = brain.inst.cfg["memory"]                       # set_slot recarregou a config
    if hindsight_health(url) is None:
        ui.say("subindo o Hindsight (docker compose)…")
        if compose_up(mode, ui, env_file=env_file) and not wait_hindsight(url, 120):
            ui.say(f"✗ Hindsight não respondeu em {url} — veja `docker logs hindsight`")
            return
        ui.say("✓ Hindsight no ar")
    elif env_changed:
        ui.say("recriando o Hindsight com os provedores do config/.env…")
        if compose_up(mode, ui, env_file=env_file) and not wait_hindsight(url, 120):
            ui.say("⚠ recriação falhou — rode você: docker compose -f services/compose.yaml "
                   + ("-f services/compose.full.yaml " if mode == "full" else "")
                   + "--env-file config/.env up -d")
        else:
            ui.say("✓ Hindsight recriado com os provedores escolhidos")
    if mode == "embed":
        if mem["embeddings_provider"] == "local" and not lmstudio_up():
            ui.say("⚠ LM Studio não responde em :1234 — suba-o com o modelo text-embedding-bge-m3 "
                   "(guides/memory.md); o sync só vai funcionar com ele no ar")
        memory._apply_mode(brain, "embed")
        banks = memory.setup(brain)
        ui.say(f"✓ memória embed pronta ({', '.join(banks)})")
        code, out = _run([sys.executable, str(FRAMEWORK / "brain"), "memory", "sync", "--limit", "3"],
                         cwd=brain.inst.root, timeout=180)
        ui.say(("✓ sync de validação: " + out.splitlines()[-1]) if code == 0 else f"⚠ sync de validação: {out[:200]}")
    else:
        memory._apply_mode(brain, "full")
        memory.setup(brain)
        ui.say(f"✓ memória full pronta (banco único {mem['bank']}) — valide o custo com `brain memory cost`")
    _harness_step(brain, ui)


def _harness_step(brain, ui) -> None:
    """Sub-passo Harnesses (plano memory-harness-wizard.md §4.1): o servidor do cérebro
    também guarda a memória dos agentes de código, em banco próprio (fora do rebuild)."""
    from . import harness, memory as _memory
    if not getattr(ui, "interactive", False):
        return                                   # conectar é opt-in do dono — sem pergunta, sem ação
    det = harness.detect()
    opts = [k for k, on in det.items() if on]
    if not opts:
        return
    mem = brain.inst.cfg["memory"]
    ui.say(f"harnesses detectados: {', '.join(opts)} — memória dos agentes no banco "
           f"'{mem['harness_bank']}' (nunca tocada pelo `memory rebuild`)")
    for name in opts:
        label = harness.AGENTS.get(name, "Hermes")
        if not ui.confirm(f"Conectar {label} no Hindsight do cérebro?", False):
            continue
        if name == harness.HERMES:
            r = harness.wire_hermes(brain)
            ui.say(f"✓ config do Hermes escrita ({r['config']})")
            ui.say("✓ memory.provider hindsight gravado" if r.get("cli")
                   else "⚠ " + (r.get("hint") or "rode: hermes config set memory.provider hindsight"))
            if r.get("plugin_recipe"):
                ui.say("⚠ plugin do Hindsight ausente — rode você mesmo (pede confirmação interativa): "
                       "hermes plugins install hindsight — vale na PRÓXIMA sessão do Hermes")
        else:
            for r in harness.install(brain, [name]):
                ui.say(f"✓ {harness.AGENTS[r['agent']]} conectado (instalador oficial)" if r["ok"]
                       else f"✗ {r['agent']}: {r['hint']}")
    wired = brain.inst.cfg["memory"].get("harnesses") or []
    if wired:
        try:
            v = harness.verify(brain, _memory.client(brain))
            if v["bank_exists"]:
                ui.say(f"✓ banco dos agentes '{v['bank']}' no servidor · recall ping "
                       + ("ok" if v["ping"] else "sem resposta (banco vazio é normal no começo)"))
            else:
                ui.say(f"⚠ banco '{v['bank']}' ainda não existe no servidor — criado no primeiro uso; "
                       "`brain memory harness verify` confere depois")
        except util.BrainError as e:
            ui.say(f"⚠ verificação dos harnesses: {e}")


def _st_portas(brain) -> str:
    cfg = brain.inst.cfg
    env = config.load_env(brain.inst)
    on = []
    if cfg["backup"]["enabled"]:
        on.append("backup")
    if env.get("GITHUB_TOKEN"):
        on.append("feedback")
    if cfg["outbound"]["allow"]:
        on.append("outbox")
    if cfg["publish"]["destinations"]:
        on.append("publish")
    if cfg["oppdrive"]["enabled"]:
        on.append("oppdrive")
    return "done" if on else "off"


def _run_portas(brain, ui) -> None:
    env = config.load_env(brain.inst)
    if ui.confirm("Porta backup (Google Drive — OAuth do foco reaproveitado)?", False):
        folder = ui.ask("GOOGLE_BACKUP_FOLDER_ID (id da pasta no Drive)", env.get("GOOGLE_BACKUP_FOLDER_ID", ""))
        if folder:
            set_env(brain.inst, {"GOOGLE_BACKUP_FOLDER_ID": folder})
            config.set_keys(brain.inst, "backup", {"enabled": True})
            brain.inst = config.load(brain.inst.root)
            ui.say("✓ backup ligado (porta 4)")
    if ui.confirm("Porta feedback (issues no GitHub — token fine-grained)?", False):
        token = env.get("GITHUB_TOKEN") or ui.secret("GITHUB_TOKEN")
        if token:
            if github_token_ok(token):
                set_env(brain.inst, {"GITHUB_TOKEN": token})
                ui.say("✓ token validado (GET /user = 200); feedback ligado (porta 7)")
            else:
                ui.say("✗ token não validou (GET /user ≠ 200) — confira o escopo (issues: RW no repo do framework)")
    if ui.confirm("Configurar destinatários do outbox/publish agora?", False):
        allow = ui.ask("[outbound].allow (ids de pessoa ou #canal, separados por vírgula)", "")
        dest = ui.ask("[publish].destinations (ex.: slack:#seu-canal; vazio pula)", "")
        if allow:
            config.set_keys(brain.inst, "outbound", {"allow": [a.strip() for a in allow.split(",") if a.strip()]})
        if dest:
            config.set_keys(brain.inst, "publish", {"destinations": [d.strip() for d in dest.split(",") if d.strip()]})
        brain.inst = config.load(brain.inst.root)
        ui.say("✓ portas outbox/publish configuradas (aprovação por mensagem continua valendo)")
    ui.say("(oppdrive: porta 6 — ligue depois editando [oppdrive] no config/brain.toml, guides/user-guide.md)")


def _st_fontes(brain) -> str:
    from . import watch
    try:
        n = len(watch.list_sources(brain))
    except Exception:                                   # noqa: BLE001 — status é informativo
        n = 0
    return "done" if n else "off"


def _run_fontes(brain, ui) -> None:
    ui.say("Fontes observáveis: `brain watch add <key> --kind <gcal|gmail|slack|drive|jira|github> "
           "--window <janela>` (config/watch.toml — o universo do /update).")
    ui.say("Os CONECTORES ligam no seu agente (Hermes: manage_connections; claude: config dele) — "
           "a leitura é MCP do agente, não daqui.")
    if ui.interactive and ui.confirm("Adicionar uma fonte agora?", False):
        _run([sys.executable, str(FRAMEWORK / "brain"), "watch", "add"], cwd=brain.inst.root)  # interativo


def _st_runner(brain) -> str:
    return "done" if "runner" in _sections_in_file(brain.inst) else "pending"


def _run_runner(brain, ui) -> None:
    agent = ui.choice("Runner do agente (⚡ da TUI e noturno)", ["auto", "claude", "cursor", "codex", "agy", "none"],
                      brain.inst.cfg["runner"]["agent"])
    config.set_keys(brain.inst, "runner", {"agent": agent})
    brain.inst = config.load(brain.inst.root)
    ui.say(f"✓ runner: {agent}")


def _run_fechamento(brain, ui) -> None:
    code, out = _run([sys.executable, str(FRAMEWORK / "brain"), "render"], cwd=brain.inst.root, timeout=300)
    ui.say("✓ views renderizadas (painel: `brain render --open`)" if code == 0 else f"⚠ render: {out[:200]}")
    code, out = _run([sys.executable, str(FRAMEWORK / "brain"), "doctor"], cwd=brain.inst.root, timeout=120)
    ui.say(out[-1200:] if out else "(doctor sem saída)")
    ui.say("Próximo passo é com o seu agente: entrevista /init (PROFILE + PLANNING) — é lá que a vida entra.")


STEPS: list[dict] = [
    {"id": "instancia", "title": "Instância (vault + config)", "status": _st_instancia, "run": _run_instancia},
    {"id": "identidade", "title": "Identidade do dono (ledger)", "status": _st_identidade, "run": _run_identidade},
    {"id": "rotina", "title": "Rotina (fuso, expediente)", "status": _st_rotina, "run": _run_rotina},
    {"id": "comando", "title": "Comando `brain` no PATH", "status": _st_comando, "run": _run_comando},
    {"id": "foco", "title": "Foco (ics | google)", "status": _st_foco, "run": _run_foco},
    {"id": "noturno", "title": "Noturno (agendamento)", "status": _st_noturno, "run": _run_noturno},
    {"id": "tui", "title": "TUI (venv Textual)", "status": _st_tui, "run": _run_tui},
    {"id": "memoria", "title": "Memória (none | embed | full)", "status": _st_memoria, "run": _run_memoria},
    {"id": "portas", "title": "Portas opcionais (backup, feedback, outbox…)", "status": _st_portas, "run": _run_portas},
    {"id": "fontes", "title": "Fontes observáveis (watch)", "status": _st_fontes, "run": _run_fontes},
    {"id": "runner", "title": "Runner do agente", "status": _st_runner, "run": _run_runner},
    {"id": "fechamento", "title": "Fechamento (render + doctor)", "status": lambda b: "pending", "run": _run_fechamento},
]

ICON = {"done": "✓", "pending": "○", "off": "–", "warn": "⚠"}


def run(brain, only: list[str] | None = None, auto: bool = False, mode: str | None = None) -> None:
    ui = AutoUI() if auto else ConsoleUI()
    only = [o.strip() for o in only] if only else None
    ids = [s["id"] for s in STEPS]
    if only:
        bad = [o for o in only if o not in ids]
        if bad:
            raise util.BrainError(f"passo(s) desconhecido(s): {', '.join(bad)} — válidos: {', '.join(ids)}", code=4)
    ui.say("Setup assistido — estado de cada passo:\n")
    for s in STEPS:
        ui.say(f"  {ICON.get(s['status'](brain), '·')} {s['id']:<12} {s['title']}")
    ui.say("")
    todo = [s for s in STEPS if (only is not None and s["id"] in only)
            or (only is None and s["status"](brain) in ("pending", "warn"))]
    if not todo:
        ui.say("✓ tudo configurado — nada pendente. Re-visite com `brain setup --only <passo>`.")
        return
    for s in todo:
        ui.say(f"── {s['id']}: {s['title']} " + "─" * max(1, 34 - len(s["id"]) - len(s["title"])))
        if s["id"] == "memoria":
            s["run"](brain, ui, mode_hint=mode)
        else:
            s["run"](brain, ui)
        ui.say("")


def cli(args, brain) -> None:
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("setup é decisão do dono, presente — nunca no noturno", code=4)
    run(brain, only=util.split_csv(args.only) or None, auto=args.yes, mode=args.mode)
