"""Setup assistido — `brain setup` (guides/setup.md).

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
import hashlib
import html
import json
import os
import re
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

from . import config, gates, util

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
def set_env(inst, updates: dict[str, str], *, unset: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Grava chaves no config/.env preservando as existentes (0600). `unset` remove chaves obsoletas. Nunca imprime valores."""
    path = inst.env_file
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str | None] = list(lines)
    indices: dict[str, list[int]] = {}
    for idx, ln in enumerate(lines):
        k, sep, _ = ln.partition("=")
        ks = k.strip()
        if sep and ks and not ks.startswith("#"):
            indices.setdefault(ks, []).append(idx)
    changed: list[str] = []
    for k in unset:
        if k in indices and k not in updates:
            for idx in indices.pop(k):
                out[idx] = None
            changed.append(k)
    for k, v in updates.items():
        if not isinstance(k, str) or any(c in k for c in ("\n", "\r", "\x00")) or not _ENV_KEY_RE.match(k):
            raise util.BrainError(f"config/.env: chave inválida ({k!r})", code=4)
        if v is None or v == "":
            continue
        sv = str(v)
        if any(c in sv for c in ("\n", "\r", "\x00")):
            raise util.BrainError(f"config/.env: valor inválido para {k!r} (contém quebra de linha ou caractere nulo)", code=4)
        new_line = f"{k}={sv}"
        if k in indices:
            idxs = indices[k]
            last_idx = idxs[-1]
            had_dupes = len(idxs) > 1
            if had_dupes or out[last_idx] != new_line:
                for prev in idxs[:-1]:
                    out[prev] = None
                out[last_idx] = new_line
                indices[k] = [last_idx]
                changed.append(k)
        else:
            out.append(new_line)
            indices[k] = [len(out) - 1]
            changed.append(k)
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        final_lines = [ln for ln in out if ln is not None]
        util.atomic_write(path, "\n".join(final_lines) + "\n")
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


def _brain_link_target(create: bool = False) -> tuple[Path | None, Path | None]:
    home_local = Path.home() / ".local" / "bin"
    candidates = [home_local] + [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    target = next((c for c in candidates if c.is_dir() and os.access(c, os.W_OK)), None)
    if target is None and create:
        home_local.mkdir(parents=True, exist_ok=True)
        target = home_local
    return (target, target / "brain") if target is not None else (None, None)


def brain_command_other(root: Path) -> Path | None:
    """Se o symlink `brain` no destino do PATH aponta para outra instância existente, devolve a raiz dela."""
    _, link = _brain_link_target(create=False)
    if link is None or not link.is_symlink():
        return None
    try:
        cur = link.resolve()
    except OSError:
        return None
    if cur.exists() and cur != (root / "brain").resolve():
        return cur.parent
    return None


def install_brain_command(root: Path, ui: ConsoleUI, *, replace: bool = False) -> str | None:
    """Cria o comando `brain` (symlink num diretório do PATH). Devolve o caminho criado, ou None se
    apontava para outra instância e `replace=False`."""
    target, link = _brain_link_target(create=True)
    cur = link.resolve() if link.is_symlink() else None
    other = cur.parent if (cur and cur.exists() and cur != (root / "brain").resolve()) else None
    if other and other.exists() and not replace:
        return None
    if link.exists() and not link.is_symlink():
        ui.say(
            f"⚠ {link} já existe e não é link simbólico — não vou apagar; "
            "remova ou mova o arquivo e rode `brain setup --only comando`"
        )
        return None
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


DOCKER_INSTALL_URL = "https://get.docker.com"            # Linux/WSL: script oficial do Docker Engine
_ORB_APP = Path("/Applications/OrbStack.app")
_ORB_XBIN_DOCKER = _ORB_APP / "Contents" / "MacOS" / "xbin" / "docker"


def docker_installed(which=shutil.which, exists=None) -> bool:
    """Existe um runtime de contêiner nesta máquina? (docker no PATH, xbin do OrbStack ou o app —
    instalado ≠ daemon no ar; o app nunca aberto ainda não criou os symlinks do PATH.)"""
    if which("docker"):
        return True
    for p in (_ORB_XBIN_DOCKER, _ORB_APP):
        if exists is not None:
            if exists(p):
                return True
        elif p.exists():
            return True
    return False


def docker_state(up: bool | None = None, which=shutil.which, exists=None) -> str:
    """`up` (daemon responde) · `installed` (existe, daemon parado) · `missing` (o Brain instala)."""
    if up is None:
        up = docker_available()
    if up:
        return "up"
    return "installed" if docker_installed(which, exists) else "missing"


def docker_ensure(ui, run=_run, which=shutil.which, fetch=None,
                  pins: dict[str, str] | None = None) -> bool:
    """Traz o runtime de contêiner ao estado que o Brain precisa — instala se faltar e sobe o
    daemon — narrando cada passo (mesma regra do LM Studio: o dono fica ciente, não executa).
    macOS: OrbStack (cask oficial do Homebrew; `orb start` sobe). Linux/WSL: Docker Engine
    (script oficial get.docker.com; systemd/service sobe o daemon). Outra plataforma: receita
    honesta, nada executado."""
    if docker_available():
        return True
    installed = docker_installed(which)
    if util.on_macos():
        if not installed:
            brew = which("brew")
            if not brew:
                ui.say("✗ sem Homebrew para instalar o OrbStack — instale o Homebrew (brew.sh) "
                       "ou o OrbStack (orbstack.dev) e rode `brain setup --only memoria` de novo")
                return False
            ui.say("instalando o OrbStack pelo Homebrew (cask oficial — baixa o app)…")
            code, out = run([brew, "install", "--cask", "orbstack"], timeout=1800)
            if code != 0:
                ui.say(f"✗ instalação do OrbStack falhou: {out[:200]} — baixe em https://orbstack.dev")
                return False
            ui.say("✓ OrbStack instalado")
        ui.say("subindo o OrbStack (a primeira abertura leva alguns segundos)…")
        orb = which("orb") or (_ORB_APP / "Contents" / "MacOS" / "OrbStack")
        code, out = run([str(orb), "start"], timeout=120)
        if code != 0:
            code, out = run(["open", "-a", "OrbStack"], timeout=60)
        if code != 0 and not docker_available():
            ui.say(f"✗ não consegui subir o OrbStack: {out[:200]} — abra o app uma vez e rode "
                   "`brain setup --only memoria` de novo")
            return False
    elif util.on_linux():
        if not installed:
            ui.say("instalando o Docker Engine (script oficial get.docker.com — pode pedir a "
                   "senha do sistema)…")
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                script = Path(td) / "get-docker.sh"
                err = _fetch_verified(DOCKER_INSTALL_URL, script, "docker",
                                      timeout=120, fetch=fetch, pins=pins)
                if err:
                    ui.say(f"✗ não consegui baixar/verificar o instalador do Docker ({err}) — manual: "
                           "curl -fsSL https://get.docker.com | sh")
                    return False
                code, out = run(["sh", str(script)], timeout=1800)
            if code != 0:
                ui.say(f"✗ instalação do Docker falhou: {out[:200]} — manual: "
                       "curl -fsSL https://get.docker.com | sh")
                return False
            ui.say("✓ Docker Engine instalado")
        ui.say("subindo o daemon do Docker…")
        code, out = run(["systemctl", "start", "docker"], timeout=60)
        if code != 0:
            code, out = run(["service", "docker", "start"], timeout=60)
        if code != 0 and not docker_available():
            ui.say(f"✗ daemon não subiu: {out[:200]} — `sudo systemctl start docker` (ou "
                   "`sudo service docker start`) e rode `brain setup --only memoria` de novo")
            return False
    else:
        ui.say("✗ plataforma sem runtime de contêiner suportado — no Windows, use o Brain "
               "dentro do WSL2 (guides/plans/platform-support.md)")
        return False
    for _ in range(30):                                   # boot do daemon: até ~60 s
        if docker_available():
            break
        time.sleep(2)
    if not docker_available():
        ui.say("✗ o runtime não respondeu ao `docker version` — veja o app/daemon no sistema")
        return False
    ui.say("✓ runtime de contêiner no ar")
    return True


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


LMS_INSTALL_URL = "https://lmstudio.ai/install.sh"      # instalador oficial (runtime headless + lms)
# o catálogo de staff picks já não resolve "text-embedding-bge-m3" por nome (verificado ao vivo):
# o fallback aponta para a conversão GGUF canônica — o `lms` registra como text-embedding-bge-m3.
LMS_GET_FALLBACK = {"text-embedding-bge-m3": "https://huggingface.co/gpustack/bge-m3-GGUF"}
_LMS_APP_DIRS = (Path("/Applications"), Path.home() / "Applications")


def lms_bin(which=shutil.which) -> str | None:
    """Caminho do `lms`: PATH primeiro, depois o binário que acompanha o app (~/.lmstudio/bin)."""
    w = which("lms")
    if w:
        return w
    p = Path.home() / ".lmstudio" / "bin" / "lms"
    try:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    except OSError:
        pass
    return None


def lmstudio_installed(which=shutil.which, exists=None) -> bool:
    """O LM Studio existe nesta máquina? (binário `lms` OU o app instalado — instalado ≠ no ar.)"""
    if lms_bin(which):
        return True
    for d in _LMS_APP_DIRS:
        app = d / "LM Studio.app"
        if exists is not None:
            if exists(app):
                return True
        elif app.exists():
            return True
    return False


def lmstudio_state(up: bool | None = None, which=shutil.which, exists=None) -> str:
    """`up` (servidor respondendo em :1234) · `installed` (existe, servidor desligado) ·
    `missing` (não existe — o Brain pode instalar). Instalado dizendo "falta" é o defeito
    que fez nascer este probe: a máquina do dono tem o app e o assistente mandava baixar."""
    if up is None:
        up = lmstudio_up()
    if up:
        return "up"
    return "installed" if lmstudio_installed(which, exists) else "missing"


def lmstudio_model_present(bin_: str, model: str, run=_run) -> bool:
    code, out = run([bin_, "ls"], timeout=30)
    return code == 0 and model in out


INSTALLER_PINS_PATH = FRAMEWORK / "scripts" / "installer-pins.json"


def _load_installer_pins(path: Path | None = None) -> dict[str, str]:
    """Carrega mapa {nome: sha256} de scripts/installer-pins.json."""
    p = path or INSTALLER_PINS_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pins = raw.get("pins") if isinstance(raw, dict) else None
    if not isinstance(pins, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in pins.items():
        if isinstance(v, dict) and isinstance(v.get("sha256"), str) and v["sha256"].strip():
            out[str(k)] = v["sha256"].strip().lower()
        elif isinstance(v, str) and v.strip():
            out[str(k)] = v.strip().lower()
    return out


def _fetch(url: str, dest: Path, timeout: int = 120) -> str | None:
    """Baixa a url para dest (arquivo temporário, nunca `curl | sh`). Devolve erro ou None."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return str(e)


def _fetch_verified(url: str, dest: Path, pin_name: str, *, timeout: int = 120,
                    fetch=None, pins: dict[str, str] | None = None) -> str | None:
    """Baixa url para dest e confere sha256 contra scripts/installer-pins.json antes de executar."""
    downloader = _fetch if fetch is None else fetch
    err = downloader(url, dest, timeout=timeout)
    if err:
        return err
    try:
        got = hashlib.sha256(dest.read_bytes()).hexdigest().lower()
    except OSError as e:
        return f"não consegui ler o instalador baixado ({e})"
    pin_table = _load_installer_pins() if pins is None else pins
    entry = pin_table.get(pin_name)
    expected = (entry.get("sha256") if isinstance(entry, dict) else entry) or ""
    expected = str(expected).strip().lower()
    if not expected:
        return f"pin sha256 ausente para '{pin_name}' (esperado: <ausente>, obtido: {got})"
    if got != expected:
        return f"sha256 divergente para '{pin_name}' (esperado: {expected}, obtido: {got})"
    return None


def lmstudio_ensure(ui, model: str = "", run=_run, which=shutil.which,
                    fetch=None, pins: dict[str, str] | None = None) -> bool:
    """Traz o LM Studio ao estado que o Brain especifica — instalação, servidor :1234 e modelo
    de embeddings — narrando cada passo (o dono fica ciente, não executa nada à mão). Devolve
    True quando o servidor responde com o modelo no disco (carregar é best-effort: o JIT cobre).
    Regra da máquina nua: no WSL o LM Studio mora no host Windows — nada de instalar aqui."""
    from . import providers as prov
    model = model or prov.PROVIDERS["embeddings"]["local"].get("model", "text-embedding-bge-m3")
    bin_ = lms_bin(which)
    if bin_ is None:
        installed = lmstudio_installed(which)
        if util.in_wsl() and not installed:
            ui.say("✗ LM Studio no WSL mora no host Windows — instale-o lá (lmstudio.ai), ligue o "
                   "servidor dele e confira a URL em guides/plans/platform-support.md")
            return False
        ui.say("baixando o LM Studio (instalador oficial — runtime local, sem interface)…"
               if not installed else
               "o LM Studio está instalado sem o CLI — baixando o CLI oficial (mesmos modelos)…")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "install.sh"
            err = _fetch_verified(LMS_INSTALL_URL, script, "lmstudio", fetch=fetch, pins=pins)
            if err:
                ui.say(f"✗ não consegui baixar/verificar o instalador do LM Studio ({err}) — baixe em "
                       "https://lmstudio.ai e rode `brain setup --only memoria` de novo")
                return False
            code, out = run(["bash", str(script)], timeout=900)
            if code != 0:
                ui.say(f"✗ instalador do LM Studio falhou: {out[:200]} — baixe em https://lmstudio.ai")
                return False
        bin_ = lms_bin(which)
        if bin_ is None:
            ui.say("✗ o `lms` não apareceu depois da instalação — abra o LM Studio uma vez e "
                   "rode `brain setup --only memoria` de novo")
            return False
        ui.say("✓ LM Studio instalado" if not installed else "✓ CLI do LM Studio instalado")
    if not lmstudio_up():
        ui.say("subindo o servidor do LM Studio (:1234)…")
        code, out = run([bin_, "server", "start"], timeout=120)
        if code != 0 and not lmstudio_up():
            ui.say(f"✗ `lms server start` falhou: {out[:200]}")
            return False
        for _ in range(15):                                   # boot do servidor: até ~30 s
            if lmstudio_up():
                break
            time.sleep(2)
        if not lmstudio_up():
            ui.say("✗ o servidor do LM Studio não respondeu em :1234 — rode `lms server start` "
                   "no terminal para ver o erro")
            return False
        ui.say("✓ servidor do LM Studio no ar (:1234)")
    if not lmstudio_model_present(bin_, model, run):
        ui.say(f"baixando o modelo de embeddings {model} (~600 MB, uma única vez)…")
        got, out = False, ""
        for target in [model] + ([LMS_GET_FALLBACK[model]] if model in LMS_GET_FALLBACK else []):
            code, out = run([bin_, "get", target, "-y"], timeout=1800)
            if code == 0 and lmstudio_model_present(bin_, model, run):
                got = True
                break
        if not got:
            ui.say(f"✗ não consegui baixar o modelo {model}: {out[:200]}")
            return False
        ui.say(f"✓ modelo {model} no disco")
    code, _ = run([bin_, "load", model, "-y"], timeout=300)
    if code == 0:
        ui.say(f"✓ modelo {model} carregado")
    else:
        ui.say(f"• modelo {model} não veio carregado agora — o LM Studio o carrega sozinho na "
               "primeira chamada (JIT)")
    return True


def github_token_ok(token: str) -> bool:
    req = urllib.request.Request("https://api.github.com/user", headers={"Authorization": f"Bearer {token}",
                                                                        "User-Agent": "brain-setup"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def github_repo_access(token: str, repo: str) -> tuple[bool, str]:
    """O token enxerga o repo do framework e ele aceita issues? → (ok, motivo). Criar uma issue de teste
    seria publicar: o que dá para checar sem isso é leitura do repo (200) e `has_issues`."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "brain-setup"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return False, ("o token não enxerga o repositório (404): na criação, escolha o dono do repo e marque "
                       "este repo" if e.code == 404 else f"GitHub respondeu {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return False, f"sem contato com o GitHub ({e})"
    if data.get("archived"):
        return False, "o repositório está arquivado — não aceita issues"
    if data.get("has_issues") is False:
        return False, "o repositório está com Issues desligadas"
    return True, "repo visível e com Issues ligadas"


def nightly_installed(root: Path) -> bool:
    try:
        from . import runner
        return runner.scheduled_here(root)
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
                         wait_s: int = 300, say=print) -> str:
    """Fluxo OAuth loopback (calendar.events.owned + drive.file). Devolve o refresh token —
    o chamador grava no .env; o valor não é impresso. `say` narra (CLI imprime; wizard vira log de job)."""
    import errno
    redirect = f"http://localhost:{OAUTH_PORT}"
    _OAuthHandler.code = _OAuthHandler.denied = None
    _OAuthHandler.expected_state = secrets.token_urlsafe(24)
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": _OAuthHandler.expected_state})
    try:
        server = HTTPServer(("127.0.0.1", OAUTH_PORT), _OAuthHandler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            raise util.BrainError(
                f"OAuth: a porta local {OAUTH_PORT} já está em uso — feche o processo que a ocupa "
                f"(ex.: `lsof -i :{OAUTH_PORT}`) e rode de novo",
                code=3,
            ) from e
        raise util.BrainError(
            f"OAuth: não consegui abrir o servidor local na porta {OAUTH_PORT} ({e.strerror or e}) — rode de novo",
            code=3,
        ) from e
    try:
        if open_browser:
            opener = shutil.which("xdg-open") or shutil.which("open")
            if opener:
                try:
                    subprocess.run([opener, auth_url], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        say(f"Abrindo o navegador para autorizar (escopos: calendar.events.owned + drive.file)…")
        say(f"Se não abrir: {auth_url}")
        threading.Thread(target=lambda: (setattr(server, "timeout", 1), _pump(server, wait_s)), daemon=True).start()
        deadline = time.time() + wait_s
        while not (_OAuthHandler.code or _OAuthHandler.denied) and time.time() < deadline:
            time.sleep(1)
    finally:
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
        # só o nome: o id é gerado dele (a instância é de uma pessoa só — id é detalhe interno)
        owner_name = ui.ask("Seu nome", _system_full_name())
        args = argparse.Namespace(owner_id=None, owner_name=owner_name, alias=None, email=None)
        _cli.cmd_init(args, brain)
    else:
        ui.say("✓ instância já semeada")


def _system_full_name() -> str:
    """Nome de partida da pergunta "Seu nome": o nome completo da conta do sistema (macOS/Linux), senão o login."""
    try:
        import pwd
        full = pwd.getpwnam(getpass.getuser()).pw_gecos.split(",")[0].strip()
    except Exception:  # noqa: BLE001 — sem pwd (Windows) ou conta sem gecos: cai no login
        full = ""
    return full or getpass.getuser()


def _st_identidade(brain) -> str:
    return "done" if brain.owner in brain.state.people else "pending"


def _run_identidade(brain, ui) -> None:
    if brain.owner in brain.state.people:
        ui.say("✓ dono já registrado no ledger")
        return
    cur = brain.inst.cfg["owner"]["name"]
    name = ui.ask("Seu nome", _system_full_name() if cur == "Dono do cérebro" else cur)
    if brain.owner == "eu":                      # id-placeholder do template (init sem nome): gera o id do nome
        config.set_keys(brain.inst, "owner", {"id": util.owner_slug(name), "name": name})
        brain.inst = config.load(brain.inst.root)
        brain.reload()
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


def _st_framework(brain) -> str:
    """Clone git em dia com o upstream: regra de fetch do origin + hook pre-push (a varredura antes do push)."""
    from . import upstream
    inst = brain.inst
    if upstream.fetch_refspec_state(inst) == "sem-git":
        return "off"                                    # instância sem git: nada a sincronizar
    if upstream.fetch_refspec_state(inst) == "ausente" or upstream.hook_state(inst) == "ausente":
        return "pending"
    return "done"


def _run_framework(brain, ui) -> None:
    from . import upstream
    inst = brain.inst
    refspec = upstream.ensure_fetch_refspec(inst)
    ui.say({"corrigido": "✓ regra de fetch do origin restaurada (git fetch volta a atualizar o origin/<ramo>)",
            "ok": "✓ regra de fetch do origin presente", "sem-origin": "⚠ sem remote `origin` — nada a buscar (git remote add origin <url>)",
            "sem-git": "– sem git: nada a sincronizar"}[refspec])
    state = upstream.hook(inst, "install")
    ui.say({"instalado": "✓ hook pre-push instalado (a varredura roda antes de cada push)",
            "de-outro": "⚠ já existe um pre-push que não é do brain — a varredura não roda no push",
            "sem-git": "– sem git: sem hook"}.get(state, f"hook pre-push: {state}"))


def _st_comando(brain) -> str:
    if brain_command_status(brain.inst.root):
        return "done"
    return "warn" if brain_command_other(brain.inst.root) else "pending"


def _run_comando(brain, ui) -> None:
    if brain_command_status(brain.inst.root):
        ui.say(f"✓ `brain` já no PATH ({brain_command_status(brain.inst.root)})")
        return
    other = brain_command_other(brain.inst.root)
    if other and other.exists():
        if ui.interactive and ui.confirm(f"O comando `brain` aponta para outra instância ({other}). Trocar para esta?", False):
            install_brain_command(brain.inst.root, ui, replace=True)
        else:
            ui.say(f"⚠ o comando `brain` continua apontando para {other} — para trocar, rode `brain setup --only comando` num terminal")
        return
    install_brain_command(brain.inst.root, ui)


def _st_painel(brain) -> str:
    from . import launcher
    if sys.platform not in launcher.SUPPORTED:
        return "off"                                    # sem ícone nesta plataforma: `render --open` segue valendo
    return "done" if launcher.is_installed(brain.inst.root) else "pending"


def _run_painel(brain, ui) -> None:
    from . import launcher
    if sys.platform not in launcher.SUPPORTED:
        ui.say("ícone do painel: só macOS/Linux — use `brain render --open`")
        return
    if launcher.is_installed(brain.inst.root):
        ui.say("✓ ícone do painel já instalado (reinstale com `brain app install` se mudou a pasta)")
        return
    other = launcher.other_owner(brain.inst.root)
    if other:
        replace = bool(ui.interactive and ui.confirm(
            f"O app Brain abre outra instância ({other}). Trocar para esta?", False))
        target = launcher.install(brain.inst, replace_other=replace)
        if replace:
            ui.say(f"✓ ícone criado: {target}")
        return
    if ui.confirm("Criar o app Brain (clique duplo abre o Brain, sem terminal)?", True):
        ui.say(f"✓ ícone criado: {launcher.install(brain.inst)}")
        # mesma moeda do passo "A máquina" do wizard: app instalado, prega no Dock/desktop —
        # idempotente e cosmetico (nunca derruba o passo); as duas superfícies não podem divergir
        try:
            ui.say(launcher.pin_shortcut())
        except (util.BrainError, OSError, subprocess.SubprocessError) as e:
            ui.say(f"– atalho de um clique: {e}")


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
    return "done" if nightly_installed(brain.inst.root) else "pending"


def _run_noturno(brain, ui) -> None:
    if nightly_installed(brain.inst.root):
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


def _providers_step(brain, ui, slots: list[str], going_full: bool | None = None) -> bool:
    """Escolha de provedores por slot (plano memory-providers.md) — wizard e re-edição usam o mesmo
    caminho do `brain memory providers set`. Devolve True se o .env mudou (container a recriar)."""
    from . import providers as prov
    st = prov.stack(brain)
    env_keys = config.load_env(brain.inst)
    labels = {"llm": "LLM (extração · consolidação · mental models)",
              "embeddings": "embeddings", "reranker": "reranker",
              "decision": "decisão (juiz rápido System-1 — opcional)"}
    changed = False
    # full é só-nuvem: embeddings locais não entram no menu. No fluxo headless a lista pode vir só com o LLM
    # ou só com os embeddings (`only`): por isso o chamador diz se está indo ao full, em vez de deduzir da lista.
    going_full = "llm" in slots if going_full is None else going_full
    # modelo/endpoint que o payload (painel, formulário, CLI) trouxe para ESTE slot — hook só da UI roteirizada; no
    # wizard interativo o padrão segue vazio (`custom` não tem registro) e o dono digita
    preset = getattr(ui, "preset", None) or (lambda _slot: {})
    for slot in slots:
        pre = preset(slot)
        cur = st[slot]["provider"]
        reg = prov.PROVIDERS[slot]
        opts = [k for k, _ in prov.menu_providers(
            slot, include_custom=True, include_unavailable=False,
            mode="full" if going_full else "embed",
        )]
        if slot == "embeddings" and going_full and cur == "local":
            ui.say("  ☁ modo full é só-nuvem: embeddings locais (bge-m3 no LM Studio) ficam para o embed")
        default = cur if cur in opts else ("off" if slot in ("reranker", "decision") else
                                           "fireworks" if (slot == "embeddings" and going_full) else
                                           "local" if slot == "embeddings" else "anthropic")
        p = ui.choice(f"Provedor de {labels[slot]}", opts, default)
        info = reg[p]
        if slot == "llm" and info.get("docker_auth") == "manual":
            if info.get("setup_hint"):
                ui.say(f"  ⚠ {info['setup_hint']}")
            if info.get("auth_command"):
                ui.say(f"  comando: {info['auth_command']}")
        if p == "off" or (p == "local" and not info.get("key_env")):
            res = prov.set_slot(brain, slot, p)
            ui.say(f"✓ {slot}: {info['label']}")
            changed = changed or bool(res["env"])
            continue
        if slot != "llm" and not info.get("local"):
            ui.say(f"  ☁ nuvem: o texto do vault vai à API do provedor para "
                   f"{'vetorizar' if slot == 'embeddings' else 'julgar' if slot == 'decision' else 'reranquear'}"
                   " — mesmo gate de egress do plano §4.3")
        key_env = info.get("key_env", "")
        key = ""
        # wizard interativo só pede quando falta; no roteiro (payload do formulário/CLI) a chave digitada
        # SUBSTITUI a gravada — "vazio = mantém a do .env" é o combinado dos formulários
        replace = getattr(ui, "replace_key", None) or (lambda _env: False)      # hook só da UI roteirizada
        if key_env and not (env_keys.get(key_env) and not replace(key_env)):
            key = ui.secret(f"API key ({key_env})")
        rec = info.get("models") or (info.get("model") and {"default": info["model"]}) or {}
        models, model, base_url, recall, candidates = None, "", "", None, 0
        if slot == "llm" and rec and ui.confirm("Usar os modelos recomendados por operação (cenário B do plano)?", True):
            models = dict(rec)
        elif slot == "llm":
            model = ui.ask("Modelo default (vazio = padrão do provedor)", info.get("model", ""))
            cheap = ui.ask("Modelo BARATO p/ extração+consolidação (vazio = default)", "")
            if cheap:
                models = {"retain": cheap, "consolidation": cheap}
        elif p == "custom":                       # slot que não é o LLM: a pergunta nomeia o slot…
            model = ui.ask(f"Modelo ({slot})", pre.get("model", ""))      # …para a UI roteirizada não responder com o modelo do LLM
        if p == "custom" or (slot == "llm" and p in ("zai", "fireworks")) or (slot == "decision" and p == "local"):
            base_url = ui.ask("Base URL" if slot == "llm" else f"Base URL ({slot})",
                              pre.get("base_url") or info.get("base_url", ""))
        if slot == "decision" and p == "hindsight":
            if ui.confirm("Usar o decisor também no recall?", False):
                recall = "on"
                raw_cands = ui.ask("Teto de candidatos no recall (--candidates)", "")
                candidates = int(raw_cands) if str(raw_cands).strip().isdigit() else 0
            else:
                recall = "off"
        res = prov.set_slot(brain, slot, p, model=model, models=models, base_url=base_url,
                            candidates=candidates, key=key, recall=recall)
        ui.say(f"✓ {slot} → {res['label']}" + (" (chave gravada no config/.env)" if key else ""))
        if res["rebuild_needed"]:
            ui.say("⚠ embeddings mudaram: vetores antigos são incompatíveis — `brain memory rebuild` "
                   "re-deriva tudo do vault depois do wizard")
        changed = changed or bool(res["env"])
    return changed


def _redact_token(text: str) -> str:
    return re.sub(r"sk-ant-\S{6,}", "sk-ant-…", text)


def _auth_claude_token(brain, ui) -> bool:
    """claude-code: `claude setup-token` na máquina vira token de longo prazo no config/.env
    (server-held token documentado do Hindsight) — o container lê pelo env_file."""
    claude = shutil.which("claude")
    if not claude:
        ui.say("✗ Claude Code CLI não encontrado na máquina — instale (`npm install -g @anthropics/claude-code` "
               "ou `brew install anthropic/claude-code/claude-code`), entre na sua conta e rode de novo")
        return False
    ui.say("gerando o token de longo prazo (claude setup-token)…")
    code, out = _run([claude, "setup-token"], timeout=180)
    m = re.search(r"sk-ant-[A-Za-z0-9_\-]{16,}", out or "")
    if code != 0 or not m:
        ui.say("✗ o CLI não devolveu token — normalmente falta login: rode `claude` uma vez, entre na sua "
               "conta no navegador e tente de novo (saída do CLI abaixo)")
        for ln in (out or "").strip().splitlines()[-5:]:
            ui.say("  " + _redact_token(ln))
        return False
    set_env(brain.inst, {"HINDSIGHT_API_LLM_API_KEY": m.group(0)})
    ui.say("✓ token gravado no config/.env (HINDSIGHT_API_LLM_API_KEY, 0600) — nunca volta para a tela")
    from . import memory
    _full = " -f services/compose.full.yaml" if memory.mode(brain.inst.cfg["memory"]) == "full" else ""
    ui.say(f"  para valer no servidor: docker compose -f services/compose.yaml{_full} "
           "--env-file config/.env up -d")
    return True


def _stream_exec(cmd: list[str], ui, timeout: int = 420) -> int:
    """Roda um comando narrando cada linha (device-code login: a URL/código precisa aparecer
    ENQUANTO o processo espera a aprovação). Devolve o código de saída; -1 no timeout."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as e:
        ui.say(f"✗ não consegui rodar {cmd[0]}: {e}")
        return -1
    try:
        assert proc.stdout is not None
        for ln in proc.stdout:
            ln = ln.rstrip()
            if ln:
                ui.say("  " + ln)
        proc.wait(timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        ui.say(f"✗ timeout ({timeout}s) — login não completou")
        return -1


def _auth_xai_device(brain, ui) -> bool:
    """xai-oauth: login por código de dispositivo DENTRO do container — o store (com o refresh
    token que gira a cada renovação) precisa do volume hindsight-auth, então o servidor é
    recriado ANTES do login; a aprovação acontece no navegador de qualquer aparelho."""
    if not docker_available():
        ui.say("✗ Docker/OrbStack não encontrado — o login roda dentro do servidor de memória (container)")
        return False
    from . import memory
    mem = brain.inst.cfg["memory"]
    env_file = brain.inst.env_file if brain.inst.env_file.exists() else None
    ui.say("subindo o servidor de memória com o volume de credenciais…")
    mode = memory.mode(mem)
    if not compose_up(mode, ui, env_file=env_file) or not wait_hindsight(mem["url"], 120):
        ui.say(f"✗ Hindsight não respondeu em {mem['url']} — veja `docker logs hindsight`")
        return False
    ui.say("iniciando o login — abra a URL acima no navegador e aprove com a sua conta xAI")
    code = _stream_exec(["docker", "exec", "hindsight", "/app/api/.venv/bin/python", "-m",
                         "hindsight_api.engine.providers.xai_oauth_auth", "login"], ui)
    if code != 0:
        ui.say("✗ login não completou — manual: docker exec -it hindsight /app/api/.venv/bin/python "
               "-m hindsight_api.engine.providers.xai_oauth_auth login")
        return False
    ui.say("✓ login gravado no servidor (volume hindsight-auth) — o access token renova sozinho")
    return True


def run_llm_auth(brain, ui, provider: str) -> bool:
    """Autentica o provedor de assinatura do slot LLM — o MESMO fluxo no botão Autenticar do
    painel e no `brain memory auth` (job visível: cada passo narrado, segredo nunca ecoa).
    Devolve True com a credencial pronta; False narra o caminho exato do que faltou."""
    from . import providers as prov
    reg = prov.PROVIDERS["llm"].get(provider)
    subs = [p for p, v in prov.PROVIDERS["llm"].items() if v.get("family") == "subscription"]
    if util.is_nightly():
        raise util.BrainError("autenticar provedor é ato do dono presente — nunca no noturno", code=4)
    if not reg or reg.get("family") != "subscription":
        ui.say(f"✗ {provider!r} não é provedor de assinatura — use um de: {', '.join(subs)}")
        return False
    flow = prov.AUTH_FLOWS.get(provider, "")
    if flow == "claude-token":
        return _auth_claude_token(brain, ui)
    if flow == "xai-device":
        return _auth_xai_device(brain, ui)
    ui.say(f"• {reg['label']}: ainda sem fluxo automático nesta instalação — {reg.get('setup_hint', '')}")
    if reg.get("auth_command"):
        ui.say(f"  comando: {reg['auth_command']}")
    return False


def _local_emb_model(brain) -> str:
    """Modelo de embeddings que o stack local deve servir (override do config/.env vence)."""
    from . import providers as prov
    env = config.load_env(brain.inst)
    return str(env.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL")
               or prov.PROVIDERS["embeddings"]["local"].get("model", "text-embedding-bge-m3"))


def _run_memoria(brain, ui, mode_hint: str | None = None, only: list[str] | None = None,
                 env_dirty: bool = False) -> None:
    """Passo Memória. `only` limita os slots de provedor que o roteiro regrava (fluxo headless: o que o
    payload endereçou + os que ainda não têm escolha que sirva ao modo); None = todos os slots do modo.
    `env_dirty`: o .env já mudou antes do passo (chave trocada) — o container é recriado do mesmo jeito."""
    from . import memory
    mem = brain.inst.cfg["memory"]
    url = mem["url"]
    cur = memory.mode(mem)
    mode = mode_hint or ui.choice("Memória: modo", ["none", "embed", "full"], cur if cur != "none" else "embed")
    if mode == "none":
        memory._apply_mode(brain, "none")
        return
    if not docker_available() and hindsight_health(url) is None:
        ui.say("Docker/OrbStack — o Brain instala e sobe sozinho:")
        if not docker_ensure(ui):
            ui.say("⚠ runtime de contêiner indisponível e Hindsight fora do ar — o que faltou "
                   "está narrado acima; `brain setup --only memoria` tenta de novo. Os demais passos seguem.")
            if not ui.interactive:
                return
    gate = ""
    if mode == "full":
        gate = ui.ask('Modo full: texto do vault (reuniões, Slack, documentos) irá para a API de LLM '
                      'com a SUA chave (plano da memória §4.3). Digite "ok" para aceitar', "")
        if gate.strip().lower() not in gates.ACCEPTED_WORDS:
            ui.say("✗ sem o \"ok\" literal o modo full não é gravado — nada mudou")
            return
    env_file = brain.inst.env_file if brain.inst.env_file.exists() else None
    # decisor ligado no recall: o reranker fica inerte. No wizard ele sai da lista; no roteiro (`only`) o payload pode
    # nomeá-lo — e ainda assim o slot não é regravado (o .env atual é preservado)
    skip_rer = bool(getattr(ui, "decision_recall", False))
    full_slots = ["llm", "embeddings", "decision"] if skip_rer else ["llm", "embeddings", "reranker", "decision"]
    slots = only if only is not None else (full_slots if mode == "full" else ["embeddings", "reranker"])
    if skip_rer:
        slots = [s for s in slots if s != "reranker"]
    env_changed = env_dirty or _providers_step(brain, ui, slots, going_full=mode == "full")
    mem = brain.inst.cfg["memory"]                       # set_slot recarregou a config
    if mode == "embed" and mem.get("embeddings_provider") == "local" and not lmstudio_up():
        # o Hindsight pinga as embeddings no boot: o LM Studio precisa estar pronto ANTES do up -d
        if lmstudio_ensure(ui, model=_local_emb_model(brain)):
            ui.say("✓ LM Studio pronto para o Brain")
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
            ui.say("⚠ LM Studio ainda não responde em :1234 — o que faltou está narrado acima; "
                   "`brain setup --only memoria` tenta de novo (detalhes em guides/memory.md)")
        memory._apply_mode(brain, "embed")
        banks = memory.setup(brain)
        ui.say(f"✓ memória embed pronta ({', '.join(banks)})")
        code, out = _run([sys.executable, str(FRAMEWORK / "brain"), "memory", "sync", "--limit", "3"],
                         cwd=brain.inst.root, timeout=180)
        ui.say(("✓ sync de validação: " + out.splitlines()[-1]) if code == 0 else f"⚠ sync de validação: {out[:200]}")
    else:
        memory._apply_mode(brain, "full", approval=gate)
        memory.setup(brain)
        ui.say(f"✓ memória full pronta (banco único {mem['bank']})")
        try:
            memory.client(brain).health_llm(mem["bank"])
            ui.say("✓ LLM verificado no servidor (health/llm) — valide o custo com `brain memory cost`")
        except util.BrainError as e:
            ui.say(f"⚠ verificação do LLM falhou: {e} — confira chave/provedor (docker logs hindsight)")


class _SayOnly:
    """Adaptador do wizard roteirizado quando não há _Job (CLI headless): ui.say vira print."""

    def __init__(self, say=print):
        self.say = say


class ScriptedMemoriaUI:
    """UI roteirizada do passo `memoria` — painel (via job) e CLI/TUI headless (`memory setup --provider …`).
    A chave chega POR VARIÁVEL DE AMBIENTE — o prompt do wizard carrega o nome (ex.: `API key
    (HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY)`), e provedores diferentes pedem chaves diferentes."""

    interactive = False

    def __init__(self, out, choices: dict[str, str], keys: dict[str, str], model: str, consent: bool,
                 base_url: str = "", models_override: bool = False,
                 slot_models: dict[str, dict[str, str]] | None = None,
                 decision_recall: bool = False, decision_candidates: int = 0, decision_base_url: str = ""):
        self.out, self.choices, self.keys = out, choices, keys
        self.model, self.consent, self.base_url = model, consent, base_url
        self.models_override = models_override
        self.slot_models = slot_models or {}       # slot → {model, base_url}: o que o payload trouxe para ELE
        self.decision_recall = decision_recall
        self.decision_candidates = decision_candidates
        self.decision_base_url = decision_base_url

    def say(self, msg: str) -> None:
        self.out.say(msg)

    def preset(self, slot: str) -> dict:
        """Modelo e endpoint do payload para ESTE slot — padrão das perguntas que o passo de provedores faz a um
        `custom` (embeddings, reranker). `model`/`base_url` da classe são do LLM e não servem para os outros."""
        return self.slot_models.get(slot) or {}

    def ask(self, prompt: str, default: str = "") -> str:
        if prompt.startswith("Modo full"):
            return "ok" if self.consent else ""
        if (prompt.startswith("Modelo default") or prompt == "Modelo") and self.model:
            return self.model                      # openai/zai/custom: modelo explícito do dono
        if prompt.startswith("Teto de candidatos") and self.decision_candidates:
            return str(self.decision_candidates)
        if prompt.startswith("Base URL"):
            if self.decision_base_url and default == prov_default_decision_url():
                return self.decision_base_url               # slot decisão (local): o endpoint veio no payload
            if prompt == "Base URL" and self.base_url:      # só o prompt do LLM; o dos outros slots nomeia o slot
                return self.base_url
        return default

    def choice(self, prompt: str, options: list[str], default: str) -> str:
        # o rótulo do passo diz "decisão": casando só "decision", a escolha do payload para o slot era ignorada
        for slot, word in (("LLM", "LLM"), ("embeddings", "embeddings"), ("reranker", "reranker"),
                           ("decision", "decisão")):
            if (word in prompt or slot in prompt) and self.choices.get(slot) in options:
                return self.choices[slot]
        return default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        # modelo digitado pelo dono: a tabela por operação (cenário B) fica de fora —
        # o modelo explícito vira o default de todas as operações
        if self.models_override and "cenário B" in prompt:
            return False
        if "recall" in prompt.lower():
            return bool(self.decision_recall)
        return default

    def secret(self, prompt: str) -> str:
        for env, key in self.keys.items():
            if env in prompt and key:
                return key
        raise util.BrainError("falta a API key — preencha a chave do provedor correspondente", code=4)

    def replace_key(self, key_env: str) -> bool:
        """Chave veio no payload para esta variável: SUBSTITUI a gravada no .env (vazio = mantém)."""
        return bool(self.keys.get(key_env))


def prov_default_decision_url() -> str:
    from . import providers as prov
    return prov.PROVIDERS["decision"].get("local", {}).get("base_url", "")


def _key_ok(v) -> str:
    k = str(v or "").strip()
    if k and (len(k) > 400 or any(ch.isspace() for ch in k)):
        raise util.BrainError("API key inválida", code=4)
    return k


def validate_memory_setup(data: dict) -> dict:
    """Valida o payload do passo Memória — UMA fonte para painel (job), TUI (form memory.mode) e CLI.
    Aceita formato aninhado (slots do navegador) e formato plano legado; devolve ambos no contrato."""
    from . import providers as prov
    mode = {"lite": "embed"}.get(str(data.get("mode")), str(data.get("mode")))
    if mode not in ("none", "embed", "full"):
        raise util.BrainError("modo de memória inválido", code=4)

    llm_in = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    raw_emb = data.get("embeddings")
    emb_in = raw_emb if isinstance(raw_emb, dict) else {}
    raw_rer = data.get("reranker")
    rer_in = raw_rer if isinstance(raw_rer, dict) else {}

    provider = str(llm_in.get("provider") or data.get("provider") or "anthropic").strip()
    if provider not in prov.PROVIDERS["llm"]:
        raise util.BrainError("provedor de LLM inválido", code=4)
    llm_reg = prov.PROVIDERS["llm"][provider]
    model = str(llm_in.get("model") or data.get("model") or llm_reg.get("model", "")).strip()
    llm_base_url = str(llm_in.get("base_url") or data.get("base_url") or llm_reg.get("base_url", "")).strip()
    if mode == "full":
        if provider == "custom" and not model:
            raise util.BrainError("provedor custom precisa do nome do modelo", code=4)
        if provider == "custom" and not llm_base_url:
            raise util.BrainError("provedor custom precisa de base_url", code=4)

    emb_default = "local" if mode == "embed" else "fireworks"
    emb_flat = "" if isinstance(raw_emb, dict) else str(raw_emb or data.get("emb") or "")
    emb = str(emb_in.get("provider") or emb_flat or emb_default).strip()
    if mode == "full" and emb == "local":
        raise util.BrainError("no modo full os embeddings são de nuvem — fireworks ou openai", code=4)
    if emb not in prov.PROVIDERS["embeddings"]:
        raise util.BrainError("provedor de embeddings inválido (embed: local ou nuvem)", code=4)
    emb_reg = prov.PROVIDERS["embeddings"][emb]
    emb_model = str(emb_in.get("model") or emb_reg.get("model", "")).strip()
    emb_base_url = str(emb_in.get("base_url") or emb_reg.get("base_url", "")).strip()
    if mode != "none" and emb == "custom" and not (emb_model and emb_base_url):
        raise util.BrainError("embeddings custom exige model e base_url", code=4)

    rer_flat = "" if isinstance(raw_rer, dict) else str(raw_rer or data.get("rer") or "")
    rer = str(rer_in.get("provider") or rer_flat or "off").strip()
    if rer not in prov.PROVIDERS["reranker"]:
        raise util.BrainError("reranker inválido", code=4)
    # embeddings e reranker `custom` não têm modelo nem endpoint no registro: valem os que o payload traz para o slot
    rer_reg = prov.PROVIDERS["reranker"][rer]
    rer_model = str(rer_in.get("model") or rer_reg.get("model", "")).strip()
    rer_base_url = str(rer_in.get("base_url") or rer_reg.get("base_url", "")).strip()

    raw_dec = data.get("decision")
    dec_in = raw_dec if isinstance(raw_dec, dict) else {}
    dec_flat = "" if isinstance(raw_dec, dict) else str(raw_dec or data.get("dec") or "")
    dec = str(dec_in.get("provider") or dec_flat or "off").strip()          # opcional: pular = só os tokens do LLM
    if dec not in prov.PROVIDERS["decision"]:
        raise util.BrainError("decisão inválida (off|hindsight|local)", code=4)
    if mode != "full" and dec != "off":
        raise util.BrainError("o slot decisão só vale no modo full (no embed não há LLM nem decisor)", code=4)
    dec_reg = prov.PROVIDERS["decision"][dec]
    dec_model = str(dec_in.get("model") or dec_reg.get("model", "")).strip()
    dec_base_url = str(dec_in.get("base_url") or dec_reg.get("base_url", "")).strip()
    dec_rec_raw = dec_in.get("recall") if "recall" in dec_in else data.get("decision_recall")
    dec_rec = prov._parse_recall(dec_rec_raw)
    dec_recall = bool(dec_rec)                 # o que o payload disse — False TAMBÉM quando ele não falou do recall
    recall_named = dec_rec is not None         # aninhado (`decision.recall`) ou plano legado (`decision_recall`)
    dec_cands_raw = dec_in.get("candidates") if "candidates" in dec_in else data.get("decision_candidates")
    try:
        dec_cands = int(dec_cands_raw) if dec_cands_raw not in (None, "") else 0
    except (TypeError, ValueError) as e:
        raise util.BrainError("teto de candidatos inválido (use um inteiro positivo)", code=4) from e
    cands_named = dec_cands_raw not in (None, "", 0, "0")     # 0 não é pedido: com o recall ligado é recusado abaixo
    if dec_recall:
        if mode != "full" or dec != "hindsight":
            raise util.BrainError(
                "decisor no recall só está disponível no modo full com o provedor hindsight (não disponível no local)",
                code=4,
            )
        if dec_cands <= 0:
            raise util.BrainError("ligar o decisor no recall exige o teto de candidatos (--candidates N)", code=4)

    consent = bool(data.get("consent")) or str(data.get("approval") or "").strip().lower() in gates.ACCEPTED_WORDS
    if mode == "full" and not consent:
        raise util.BrainError('o modo full precisa do seu aceite ("ok"/consent): o texto do vault vai para a API',
                              code=4)
    if mode == "full" and util.is_nightly():
        raise util.BrainError("o noturno não liga o modo full (gate de egress pede o dono presente)", code=4)

    k_top = _key_ok(data.get("key"))
    k_llm = _key_ok(llm_in.get("key"))
    k_emb = _key_ok(emb_in.get("key")) or _key_ok(data.get("emb_key"))
    k_rer = _key_ok(rer_in.get("key")) or _key_ok(data.get("reranker_key")) or _key_ok(data.get("rer_key"))
    k_dec = _key_ok(dec_in.get("key")) or _key_ok(data.get("dec_key"))

    if mode == "embed":
        emb_key = k_emb or k_top
        key = k_top or emb_key
        llm_key = k_llm
    else:
        llm_key = k_llm or k_top
        emb_key = k_emb
        key = llm_key

    # O que o chamador ENDEREÇOU por slot, e o que ele NOMEOU nele. O payload só muda o que ele diz: slot não
    # endereçado mantém o que já está gravado; sem provedor nomeado vale o atual (configure_memory).
    named = {"llm": bool(llm_in.get("provider") or data.get("provider")),
             "embeddings": bool(emb_in.get("provider") or emb_flat),
             "reranker": bool(rer_in.get("provider") or rer_flat),
             "decision": bool(dec_in.get("provider") or dec_flat)}
    model_given = {"llm": bool(llm_in.get("model") or data.get("model") or llm_in.get("base_url")
                               or data.get("base_url")),
                   "embeddings": bool(emb_in.get("model") or emb_in.get("base_url")),
                   "reranker": bool(rer_in.get("model") or rer_in.get("base_url")),
                   # decisão: além de modelo/endpoint, o payload pode trazer o decisor no recall (ligar ou
                   # desligar, teto de candidatos) SEM mudar o provedor — aí o slot não fica como está,
                   # senão o pedido era engolido (kept). Nos DOIS formatos: as chaves planas legadas
                   # (`decision_recall`/`decision_candidates`) ficavam de fora e o pedido não chegava ao roteiro
                   "decision": bool(dec_in.get("model") or dec_in.get("base_url")
                                    or recall_named or cands_named)}
    given = {"llm": named["llm"] or model_given["llm"] or bool(llm_key),
             "embeddings": named["embeddings"] or model_given["embeddings"] or bool(emb_key),
             "reranker": named["reranker"] or model_given["reranker"] or bool(k_rer),
             "decision": named["decision"] or model_given["decision"] or bool(k_dec)}

    slots: dict[str, dict] = {}
    if mode == "full":
        slots["llm"] = {"provider": provider, "key": llm_key, "model": model, "base_url": llm_base_url}
    slots["embeddings"] = {"provider": emb, "key": emb_key, "model": emb_model, "base_url": emb_base_url}
    slots["reranker"] = {"provider": rer, "key": k_rer, "model": rer_model, "base_url": rer_base_url}
    if mode == "full":
        slots["decision"] = {"provider": dec, "key": k_dec, "model": dec_model, "base_url": dec_base_url,
                             "recall": dec_recall, "candidates": dec_cands}

    return {"mode": mode, "provider": provider, "emb": emb, "rer": rer, "dec": dec,
            "dec_recall": dec_recall, "dec_candidates": dec_cands, "dec_base_url": dec_base_url,
            "recall_named": recall_named, "cands_named": cands_named,
            "model": model, "consent": consent,
            "key": key, "emb_key": emb_key, "rer_key": k_rer, "dec_key": k_dec, "slots": slots,
            "given": given, "named": named, "model_given": model_given}


def _headless_slots(brain, mode: str, given: dict) -> list[str]:
    """Slots que o roteiro do fluxo headless regrava: os que o payload endereçou mais os que ainda não têm
    escolha que sirva ao modo (provedor inválido ou chave ausente — caem no padrão, como sempre caíram).
    Os demais ficam como estão: provedor, modelo e chave. Sem isso, `memory setup --provider X` voltava os
    outros slots para o padrão."""
    from . import providers as prov
    st = prov.stack(brain)
    env = config.load_env(brain.inst)
    out: list[str] = []
    for slot in ("llm", "embeddings", "reranker", "decision"):
        if mode != "full" and slot in ("llm", "decision"):
            continue
        if given.get(slot):
            out.append(slot)
            continue
        cur = st[slot]["provider"]
        reg = prov.PROVIDERS[slot].get(cur) or {}
        if not reg or (mode == "full" and slot == "embeddings" and cur == "local") \
                or (reg.get("key_env") and not env.get(reg["key_env"])):
            out.append(slot)
    return out


def configure_memory(brain, data: dict, say=print) -> str:
    """Fluxo headless do passo Memória: valida, monta as chaves por variável de ambiente e roda o
    wizard com o roteiro (proveedores → compose → modo → bancos → health/llm). Devolve o modo final."""
    from . import memory, providers as prov
    v = validate_memory_setup(data)
    mode, provider, emb, rer = v["mode"], v["provider"], v["emb"], v["rer"]
    if mode == "none":
        memory._apply_mode(brain, "none")
        return "none"
    st = prov.stack(brain)
    env_now = config.load_env(brain.inst)
    kept: set[str] = set()
    for slot, s in v["slots"].items():
        cur = st[slot]["provider"]
        reg = prov.PROVIDERS[slot].get(cur) or {}
        if not reg or (mode == "full" and slot == "embeddings" and cur == "local"):
            continue                # sem escolha que sirva ao modo: o payload manda (padrão do modo, como antes)
        if s["provider"] != cur and v["named"][slot]:
            continue                # provedor outro, nomeado no payload: o passo de provedores aplica
        s["provider"] = cur         # sem provedor nomeado (ou o mesmo): vale o atual
        if not v["model_given"][slot] and (not reg.get("key_env") or env_now.get(reg["key_env"]) or s.get("key")):
            kept.add(slot)          # mesma escolha: nem passa pelo passo de provedores — só a chave (se veio) muda
    # Recall EFETIVO do decisor: o que o payload nomeou (aninhado ou plano legado); do que ele não nomeou, vale o
    # gravado — como qualquer campo de um slot mantido. As guardas liam só o payload (`v["dec_recall"]`), que vale
    # False quando ele não fala de recall: um save do painel que regravava o slot de decisão DESLIGAVA o recall e
    # zerava o teto, e o reranker — inerte com o recall ligado — era regravado ou tinha a chave trocada.
    salvo = st["decision"]
    dec_final = v["slots"].get("decision", {}).get("provider", "off")
    recall_efet = bool(v["dec_recall"]) if v["recall_named"] else bool(
        salvo["recall"] and salvo["provider"] == dec_final)
    cands_efet = int(v["dec_candidates"]) if v["cands_named"] else (int(salvo["candidates"]) if recall_efet else 0)
    if v["cands_named"] and not recall_efet:
        raise util.BrainError("o teto de candidatos só vale com o recall do decisor ligado — ligue `recall` no mesmo "
                              "payload (antes o valor era aceito e descartado em silêncio)", code=4)
    provider = v["slots"].get("llm", {}).get("provider", provider)
    emb, rer = v["slots"]["embeddings"]["provider"], v["slots"]["reranker"]["provider"]
    key, emb_key, rer_key = v["key"], v["emb_key"], v["rer_key"]
    # fireworks embeddings+reranker = mesma conta: a chave de um serve no outro quando sobra
    fw_shared = (rer_key or (emb_key if emb == "fireworks" else "")
                 or (key if (mode == "embed" and emb == "fireworks") else "")
                 or (key if (mode == "full" and provider == "fireworks") else ""))
    keys: dict[str, str] = {}
    cur_env = config.load_env(brain.inst)
    todo = [x for x in _headless_slots(brain, mode, v["given"]) if x not in kept]
    for slot, s in v["slots"].items():
        if slot not in todo:
            continue                                    # fica como está: só a chave, se veio no payload
        if slot == "reranker" and recall_efet:
            continue                    # recall do decisor ligado: reranker fica inerte e o .env atual é preservado
        p = s["provider"]
        reg = prov.PROVIDERS[slot][p]
        key_env = reg.get("key_env", "")
        if not key_env or p == "off":
            continue
        k = s.get("key", "")
        if not k and slot == "embeddings" and mode == "full" and provider == emb and key:
            k = key                     # mesma conta (ex.: OpenAI ou Fireworks em LLM + embeddings)
        elif not k and slot == "reranker" and p == "fireworks" and fw_shared:
            k = fw_shared
        if k:
            keys[key_env] = k
        if not (keys.get(key_env) or cur_env.get(key_env)):
            raise util.BrainError(
                f"cole a chave de {slot} ({key_env}) — ou escolha um provedor local", code=4)
    # chave que veio para um slot que fica como está: entra no .env sozinha (o wizard só escreve chave no
    # passo de provedores) — e o container é recriado, como em qualquer troca de chave
    rotate: dict[str, str] = {}
    for slot in kept:
        if slot == "reranker" and recall_efet:
            continue                        # recall do decisor ligado: o .env do reranker fica como está
        key_env = prov.PROVIDERS[slot][v["slots"][slot]["provider"]].get("key_env", "")
        k = v["slots"][slot].get("key", "")
        if key_env and k and k != cur_env.get(key_env):
            rotate[key_env] = k
    if rotate:
        prov._guard_env_updates(rotate)
        set_env(brain.inst, rotate)
    llm_base = v["slots"].get("llm", {}).get("base_url", "")
    dec = v["slots"].get("decision", {}).get("provider", "off")
    # modelo/endpoint que a UI roteirizada responde por slot (embeddings e reranker `custom` pedem os dois): só o que
    # o payload disse PARA o slot — slot sem modelo no payload fica como está ou é recusado antes do passo de provedores
    slot_models = {slot: {"model": str(data[slot].get("model") or "").strip(),
                          "base_url": str(data[slot].get("base_url") or "").strip()}
                   for slot in ("embeddings", "reranker") if isinstance(data.get(slot), dict)}
    ui = ScriptedMemoriaUI(_SayOnly(say), {"LLM": provider, "embeddings": emb, "reranker": rer, "decision": dec},
                           keys, v["model"], v["consent"], base_url=llm_base,
                           models_override=bool(v["model"]),
                           decision_recall=recall_efet,
                           decision_candidates=cands_efet,
                           decision_base_url=str(v.get("dec_base_url") or ""),
                           slot_models=slot_models)
    _run_memoria(brain, ui, mode_hint=mode, only=todo, env_dirty=bool(rotate))
    final = memory.mode(config.reload(brain.inst).cfg["memory"])
    if final == "none":
        raise util.BrainError("a memória não ligou — veja o que faltou acima", code=4)
    return final


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
    if ui.confirm("Porta feedback (sugestões e bugs do cérebro viram issues no GitHub do framework)?", False):
        repo = brain.inst.cfg["feedback"]["repo"]
        if not env.get("GITHUB_TOKEN"):
            ui.say(f"  Crie um token em https://github.com/settings/personal-access-tokens/new (fine-grained):\n"
                   f"   · Resource owner: o dono de {repo} · Repository access: só {repo}\n"
                   f"   · Permissions › Issues: Read and write (Metadata: Read vem junto) · validade a gosto\n"
                   f"   Sem ser colaborador do repo, o fine-grained não escreve em repo público: use um token clássico\n"
                   f"   com o escopo public_repo. O valor vai só para config/.env — nunca para o chat.")
        token = env.get("GITHUB_TOKEN") or ui.secret("GITHUB_TOKEN")
        if token:
            if not github_token_ok(token):
                ui.say("✗ token não validou (GET /user ≠ 200) — confira se copiou inteiro e se não expirou")
            else:
                set_env(brain.inst, {"GITHUB_TOKEN": token})
                ok, why = github_repo_access(token, repo)
                ui.say("✓ token válido e gravado em config/.env — feedback ligado (porta 7)")
                ui.say(f"  {'✓' if ok else '⚠'} {repo}: {why}" +
                       ("" if ok else " — a primeira issue vai dizer se falta permissão (`brain feedback push`)"))
                ui.say("  (permissão de escrever issue só se prova criando uma; ela não é testada aqui)")
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
    from . import runner
    cur = brain.inst.cfg["runner"]["agent"]
    agent = ui.choice("Runner do agente (⚡ da TUI e noturno)", ["auto", *runner.AUTO_ORDER, "none"], cur)
    if agent in runner.PRESETS:
        binary = runner.PRESETS[agent][0]
        if not shutil.which(binary):
            ui.say(f"⚠ o comando `{binary}` não está no PATH desta máquina")
            if not (ui.interactive and ui.confirm("Gravar mesmo assim?", False)):
                ui.say(f"runner mantido: {cur}")
                return
        elif ui.interactive:
            ui.say(f"conferindo se o {agent} está logado (sonda rápida, até 60 s)…")
            pr = runner.probe(agent, brain.inst.cfg, cwd=brain.inst.root)
            if pr["ok"]:
                ui.say(f"✓ {agent} respondeu")
            else:
                ui.say(f"⚠ {agent} não respondeu: {pr['reason']}"
                       + (f" — faça o login: {runner.LOGIN_HINT[agent]}" if pr["auth"] else ""))
                if not ui.confirm("Gravar mesmo assim? (o noturno tenta o próximo agente se este falhar)", False):
                    ui.say(f"runner mantido: {cur}")
                    return
        else:
            ui.say("sonda de login pulada (modo não interativo) — confira com `brain doctor --online`")
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
    {"id": "framework", "title": "Framework (git: regra de fetch + hook pre-push)", "status": _st_framework, "run": _run_framework},
    {"id": "comando", "title": "Comando `brain` no PATH", "status": _st_comando, "run": _run_comando},
    {"id": "painel", "title": "Ícone do painel (clique duplo)", "status": _st_painel, "run": _run_painel},
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

# O onboarding no navegador e o wizard de terminal compartilham o MESMO registro de passos
# (plano guides/plans/onboarding-unification.md F2): um id, um título — duas renderizações.
# Grupo é só cosmético (a barra lateral do /onboarding agrupa por ele).
WEB_STEPS: list[tuple[str, str, str]] = [
    ("inicio", "Boas-vindas", "Você"),
    ("voce", "Você e sua rotina", "Você"),
    ("sobre", "Sobre você", "Você"),
    ("agente", "Seu agente", "Conexões"),
    ("conectores", "Conectores e fontes", "Conexões"),
    ("memoria", "Memória", "Conexões"),
    ("chaves", "Chaves e portas", "Conexões"),
    ("maquina", "A máquina", "O cérebro"),
    ("planejamento", "Goals e projetos", "Começando"),
    ("conversa", "A conversa", "Começando"),
    ("pronto", "Pronto", "Começando"),
]


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
    if util.is_nightly():
        raise util.BrainError("setup é decisão do dono, presente — nunca no noturno", code=4)
    run(brain, only=util.split_csv(args.only) or None, auto=args.yes, mode=args.mode)
