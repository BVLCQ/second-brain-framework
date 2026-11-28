"""Servidor local do decisor hs-decide-1-flash (`/v1/systemone`).

Apple Silicon → MLX. Linux com GPU NVIDIA → vLLM. Nenhuma das duas → recusa,
nada é instalado. O venv e os pesos ficam em `<inst>/.decider/` (gitignored).
A chave local vive em `BRAIN_DECISION_LOCAL_API_KEY`, separada da chave `hsk_`.

Pins vêm do model card e do `serving/pyproject.toml` (hindsight-decision 0.5.0,
vllm==0.32.0, mlx-lm>=0.32.2,<0.33). Não são uma medição de latência desta máquina.
"""
from __future__ import annotations

import json
import os
import platform
import plistlib
import secrets
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import util

MODEL = "hs-decide-1-flash"
HF_REPO = "hindsight-ai/hs-decide-1-flash"
VLLM_PIN = "vllm==0.32.0"
HUB_PIN = "huggingface-hub>=1.0,<2"
PORT = 8000
HOST_URL = f"http://127.0.0.1:{PORT}"
CONTAINER_URL = f"http://host.docker.internal:{PORT}"
LOCAL_KEY_ENV = "BRAIN_DECISION_LOCAL_API_KEY"
CLOUD_STASH_ENV = "HINDSIGHT_API_DECISION_CLOUD_API_KEY"
WIRE_KEY_ENV = "HINDSIGHT_API_DECISION_MODEL_API_KEY"
LABEL = "com.segundo-cerebro.decider"
SMOKE_PATH = "/v1/systemone"

REFUSE = (
    "decisor local precisa de Apple Silicon (MLX) ou de Linux com GPU NVIDIA (vLLM). "
    "Nesta máquina nenhum dos dois está disponível — nada foi instalado. "
    "Use o provedor de nuvem (hindsight) ou deixe desligado (off)."
)
NIGHTLY_REFUSE = (
    "o noturno não instala o decisor local — só confere e religa o que já está instalado"
)

_FRAMEWORK = Path(__file__).resolve().parent.parent


def platform_kind(*, system: str | None = None, machine: str | None = None,
                  nvidia: bool | None = None) -> str | None:
    """`mlx` · `vllm` · None. `nvidia` injeta a sonda de GPU (testes não chamam nvidia-smi)."""
    system = sys.platform if system is None else system
    machine = platform.machine() if machine is None else machine
    if system == "darwin" and machine in ("arm64", "aarch64"):
        return "mlx"
    if system == "linux":
        has = _nvidia_present() if nvidia is None else nvidia
        if has:
            return "vllm"
    return None


def _nvidia_present() -> bool:
    return shutil.which("nvidia-smi") is not None or Path("/dev/nvidia0").exists()


def home(inst) -> Path:
    return Path(inst.root) / ".decider"


def installed(inst) -> bool:
    h = home(inst)
    return (h / "venv").is_dir() and (h / "model").is_dir() and (h / "kind").is_file()


def _py_ok(path: str) -> bool:
    import subprocess
    try:
        out = subprocess.run([path, "-c", "import sys; print(sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return False
        major, minor = out.stdout.strip().strip("()").split(",")[:2]
        return int(major) > 3 or (int(major) == 3 and int(minor) >= 12)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def python_for_venv(which=shutil.which) -> str | None:
    """Python ≥3.12 para criar o venv. Não usa o Python do sistema se for mais velho."""
    candidates = [
        str(_FRAMEWORK / ".venv-tui" / "bin" / "python"),
        which("python3.13") if which else None,
        which("python3.12") if which else None,
        which("python3") if which else None,
        sys.executable,
        # a ponte do painel roda com PATH enxuto do launchd: sem isto, Homebrew/mise ficam invisíveis
        *(f"{d}/python3.{v}" for v in (13, 12) for d in ("/opt/homebrew/bin", "/usr/local/bin")),
        str(Path.home() / ".local" / "share" / "mise" / "shims" / "python3"),
    ]
    for c in candidates:
        if c and Path(c).exists() and _py_ok(c):
            return c
    return None


def new_local_key() -> str:
    return "bdk_" + secrets.token_urlsafe(24)


def read_key(inst) -> str:
    p = home(inst) / "key"
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_key(inst, key: str) -> None:
    h = home(inst)
    h.mkdir(parents=True, exist_ok=True)
    p = h / "key"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key + "\n")


def install_commands(home_dir: Path, kind: str, python: str) -> list[list[str]]:
    """Argv da instalação. Testes afirmam isto; nada é executado aqui."""
    venv_py = home_dir / "venv" / "bin" / "python"
    hf = home_dir / "venv" / "bin" / "hf"
    model = home_dir / "model"
    cmds = [
        [python, "-m", "venv", str(home_dir / "venv")],
        [str(venv_py), "-m", "pip", "install", "--disable-pip-version-check", HUB_PIN],
        [str(hf), "download", HF_REPO, "--local-dir", str(model)],
    ]
    if kind == "mlx":
        cmds.append([str(venv_py), "-m", "pip", "install", "--disable-pip-version-check",
                     f"{model}/serving[mlx]"])
    else:
        cmds.append([str(venv_py), "-m", "pip", "install", "--disable-pip-version-check",
                     VLLM_PIN, str(model / "serving")])
    return cmds


def serve_argv(inst, kind: str | None = None) -> list[str]:
    """O que o wrapper executa. A chave vai por `--api-key` no script, lida do arquivo 0600."""
    h = home(inst)
    kind = kind or (h / "kind").read_text(encoding="utf-8").strip()
    bin_name = "hindsight-decision-serve-mlx" if kind == "mlx" else "hindsight-decision-serve"
    return [str(h / "venv" / "bin" / bin_name), str(h / "model"), "--port", str(PORT)]


def unit_plist(brain_dir: str) -> str:
    """LaunchAgent. `__BRAIN_DIR__` já substituído — o template do repo não leva caminho real."""
    # plistlib, não f-string: o XML nunca sai malformado e o caminho (espaço, `&`) é escapado.
    log = f"{brain_dir}/vault/logs/decider.log"
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ["/bin/sh", f"{brain_dir}/services/decider-serve.sh"],
        "EnvironmentVariables": {"BRAIN_DIR": brain_dir},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "ProcessType": "Background",
    }, sort_keys=False).decode("utf-8")


def unit_systemd(brain_dir: str) -> str:
    return f"""[Unit]
Description=Decisor local do Segundo Cerebro (hs-decide-1-flash)
[Service]
Type=simple
Environment=BRAIN_DIR={brain_dir}
ExecStart=/bin/sh {brain_dir}/services/decider-serve.sh
Restart=on-failure
RestartSec=5
[Install]
WantedBy=default.target
"""


def smoke_body() -> dict:
    return {
        "model": MODEL,
        "state": "A Padaria Pao Quente foi cobrada duas vezes na fatura de marco.",
        "questions": {"billing": {"type": "noul", "instructions": "Is this a billing problem?"}},
    }


def smoke(url: str = HOST_URL, key: str = "", *, http_post=None, timeout: int = 30) -> bool:
    """Um julgamento de verdade em `/v1/systemone`. Falso se o servidor não responder."""
    body = json.dumps(smoke_body()).encode()
    if http_post is not None:
        try:
            return bool(http_post(url.rstrip("/") + SMOKE_PATH, body, key))
        except Exception:
            return False
    req = urllib.request.Request(
        url.rstrip("/") + SMOKE_PATH, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode() or "{}")
        answers = data.get("answers") if isinstance(data, dict) else None
        return isinstance(answers, dict) and "billing" in answers
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _scratch(root: Path) -> bool:
    try:
        root.resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except ValueError:
        return False


def prepare(brain, *, key: str | None = None, run=None, http_post=None,
            system: str | None = None, machine: str | None = None, nvidia: bool | None = None,
            python: str | None = None, sleep=None) -> dict:
    """Instala (se faltar), sobe e passa no teste de fumaça. Não grava o slot.

    Recusa no noturno e em plataforma sem MLX/vLLM — nesse caso nada é instalado.
    """
    if util.is_nightly():
        raise util.BrainError(NIGHTLY_REFUSE, code=4)
    kind = platform_kind(system=system, machine=machine, nvidia=nvidia)
    if kind is None:
        raise util.BrainError(REFUSE, code=4)
    inst = brain.inst
    local_key = (key or "").strip() or read_key(inst) or new_local_key()
    if not local_key.startswith("bdk_") and not key:
        local_key = new_local_key()
    # chave explícita do chamador (caminho avançado que ainda pede prepare) é aceita como está
    if smoke(HOST_URL, local_key, http_post=http_post) and installed(inst):
        return {"kind": kind, "local_key": local_key, "container_url": CONTAINER_URL,
                "host_url": HOST_URL, "installed": True, "smoked": True}
    py = python or python_for_venv()
    if not py:
        raise util.BrainError(
            "falta um Python 3.12 ou mais novo para o venv do decisor — nada foi instalado",
            code=4)
    h = home(inst)
    h.mkdir(parents=True, exist_ok=True)
    (inst.logs).mkdir(parents=True, exist_ok=True)
    write_key(inst, local_key)
    (h / "kind").write_text(kind + "\n", encoding="utf-8")
    if run is None:
        run = lambda cmd: _default_run(cmd, timeout=1800)
    log_path = inst.logs / "decider-install.log"
    for cmd in install_commands(h, kind, py):
        code, out = run(cmd)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("$ " + " ".join(cmd) + f"\n(code {code})\n{out}\n")
        if code != 0:
            raise util.BrainError(
                f"instalação do decisor falhou ({cmd[0]} …) — slot não foi ligado. "
                f"ver {log_path}",
                code=4)
    _install_unit(inst, run=run)
    _start_unit(inst, run=run)
    if not _wait_smoke(HOST_URL, local_key, http_post=http_post, sleep=sleep):
        stop_service(inst, remove=False, run=run)
        log = inst.logs / "decider.log"
        where = (f"ver {log}" if log.exists()
                 else f"o serviço nem chegou a escrever {log} — o gerenciador (launchd/systemd) não o iniciou")
        raise util.BrainError(
            f"teste de fumaça do decisor falhou — o slot não foi ligado. {where}",
            code=4)
    return {"kind": kind, "local_key": local_key, "container_url": CONTAINER_URL,
            "host_url": HOST_URL, "installed": True, "smoked": True}


def _wait_smoke(url: str, key: str, *, http_post, sleep, attempts: int = 30, pause: float = 3) -> bool:
    """O kickstart volta antes do servidor escutar. A fumaça espera, não dispara uma vez."""
    import time
    sleep = time.sleep if sleep is None else sleep
    for i in range(attempts):
        if smoke(url, key, http_post=http_post):
            return True
        if i + 1 < attempts:
            sleep(pause)
    return False


def _default_run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    import subprocess
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def _install_unit(inst, *, run) -> None:
    brain_dir = str(inst.root)
    if sys.platform == "darwin":
        dest_dir = Path.home() / "Library" / "LaunchAgents"
        if _scratch(Path(inst.root)):
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{LABEL}.plist"
        dest.write_text(unit_plist(brain_dir), encoding="utf-8")
        uid = str(os.getuid())
        run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])  # não carregado é o caso comum
        code, out = run(["launchctl", "bootstrap", f"gui/{uid}", str(dest)])
        if code != 0:
            # sem isto a falha some e só aparece como "fumaça falhou", sem decider.log para ler
            raise util.BrainError(
                f"o launchd recusou o serviço do decisor (launchctl bootstrap, código {code}): "
                f"{(out or '').strip()[:300]} — plist em {dest}",
                code=4)
    elif sys.platform == "linux":
        if _scratch(Path(inst.root)):
            return
        dest_dir = Path.home() / ".config" / "systemd" / "user"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "segundo-cerebro-decider.service"
        dest.write_text(unit_systemd(brain_dir), encoding="utf-8")
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "enable", "--now", "segundo-cerebro-decider.service"])


def _start_unit(inst, *, run) -> None:
    """Sobe o serviço. `kickstart` exige o job carregado; depois de um bootout (ocioso) o bootstrap recarrega."""
    if _scratch(Path(inst.root)):
        return
    if sys.platform == "darwin":
        uid = str(os.getuid())
        label = f"gui/{uid}/{LABEL}"
        code, _out = run(["launchctl", "kickstart", "-k", label])
        if code != 0:
            plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
            run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
            run(["launchctl", "kickstart", "-k", label])
    elif sys.platform == "linux":
        run(["systemctl", "--user", "start", "segundo-cerebro-decider.service"])


def stop_service(inst, *, remove: bool = True, purge_weights: bool = False, run=None) -> str:
    """Para e, se `remove`, tira o serviço do gerenciador. Os pesos ficam, salvo `purge_weights`."""
    if run is None:
        run = _default_run
    if not _scratch(Path(inst.root)):
        if sys.platform == "darwin":
            uid = str(os.getuid())
            run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
            if remove:
                plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
                try:
                    plist.unlink()
                except FileNotFoundError:
                    pass
        elif sys.platform == "linux":
            run(["systemctl", "--user", "disable", "--now", "segundo-cerebro-decider.service"])
            if remove:
                unit = Path.home() / ".config" / "systemd" / "user" / "segundo-cerebro-decider.service"
                try:
                    unit.unlink()
                except FileNotFoundError:
                    pass
                run(["systemctl", "--user", "daemon-reload"])
    if purge_weights:
        h = home(inst)
        if h.is_dir():
            shutil.rmtree(h, ignore_errors=True)
        return "serviço parado e pesos removidos"
    return "serviço parado (pesos mantidos)"


def idle_flag(inst) -> Path:
    return home(inst) / "idle-stopped"
