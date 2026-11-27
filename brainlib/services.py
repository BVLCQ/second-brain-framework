"""Dependências locais do stack: uma função, chamada por todo mundo.

`required` lê `[memory]` e diz o que o stack exige. `ensure` confere, religa o que
está fora e espera ficar saudável — não instala no noturno. Abrir o Brain dispara
`kick` em segundo plano; o watchdog e o setup chamam a mesma função.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import decider, util

FRAMEWORK = Path(__file__).resolve().parent.parent
PAUSE = Path.home() / ".brain-watchdog-off"
STATUS_NAME = "services-status.json"
LABELS = {
    "ready": "pronto",
    "starting": "subindo",
    "failed": "falhou",
    "paused": "pausado",
    "skipped": "não exigido",
}


def required(mem: dict | None) -> list[str]:
    """O que o stack atual exige. Sem `[memory]` hindsight, nada.

    Embeddings sem chave no toml contam como local — é o padrão de fábrica, o mesmo
    que o watchdog antigo assumia. O doctor não faz esse default (probe de rede).
    """
    if not isinstance(mem, dict) or mem.get("engine") != "hindsight":
        return []
    out = ["docker", "hindsight"]
    if mem.get("embeddings_provider", "local") == "local":
        out.append("lmstudio")
    if mem.get("decision_provider") == "local":
        out.append("decider")
    return out


def hindsight_blocked(mem: dict, lmstudio_up: bool) -> str | None:
    """Mensagem se recriar o contêiner agora só o mataria de novo. None = pode subir."""
    from .memory import mode
    if mem.get("engine") != "hindsight":
        return "hindsight: modo none — pulando"
    if mode(mem) == "full" and mem.get("embeddings_provider", "local") == "local" and not lmstudio_up:
        return ("hindsight: sem health e o LM Studio (embeddings local no full) não responde em :1234 "
                "— não recrio o contêiner (morreria no boot); rode: brain setup --only memoria")
    return None


def compose_argv(root: Path, mode: str, *, services_dir: Path | None = None,
                 env_file: Path | None = None) -> list[str]:
    services = services_dir or (FRAMEWORK / "services")
    args = ["compose"]
    if mode == "full":
        env = env_file if env_file is not None else (Path(root) / "config" / ".env")
        if env.is_file():
            args += ["--env-file", str(env)]
        args += ["-f", str(services / "compose.yaml"), "-f", str(services / "compose.full.yaml")]
    else:
        args += ["-f", str(services / "compose.yaml")]
    args += ["up", "-d"]
    return args


def status_path(inst) -> Path:
    return Path(inst.logs) / STATUS_NAME


def read_status(inst) -> dict:
    try:
        data = json.loads(status_path(inst).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    state = data.get("state") or "skipped"
    data["state"] = state
    data["label"] = LABELS.get(state, state)
    data.setdefault("deps", {})
    data.setdefault("reason", "")
    return data


def _write_status(inst, row: dict) -> dict:
    row = {**row, "label": LABELS.get(row.get("state", ""), row.get("state", "")),
           "at": util.iso_now()}
    path = status_path(inst)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(row, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    return row


def _get(url: str, timeout: float = 3) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return int(getattr(r, "status", 200)) < 400
    except (OSError, ValueError):
        return False


def _default_probes() -> dict:
    from . import setup
    return {
        "lmstudio": setup.lmstudio_up,
        "docker": setup.docker_available,
        "hindsight": lambda: _get("http://127.0.0.1:8888/health"),
        "decider": lambda: _get(decider.HOST_URL + "/health") or _get(decider.HOST_URL + "/v1/models"),
    }


def _log(inst, msg: str) -> None:
    try:
        path = Path(inst.logs) / "services.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{util.iso_now()} {msg}\n")
    except OSError:
        pass


def ensure(inst, *, reason: str = "cli", install: bool = False, probes=None, run=None,
           sleep=time.sleep, waits: int = 12, pause: float = 5) -> dict:
    """Confere cada dependência exigida e religa a que estiver fora.

    `install=True` só vale fora do noturno e só para o decisor (o resto é o setup).
    `~/.brain-watchdog-off` pausa tudo, qualquer que seja o motivo.
    """
    if PAUSE.exists():
        row = _write_status(inst, {"state": "paused", "reason": reason, "deps": {},
                                   "detail": "pausado (~/.brain-watchdog-off)"})
        _log(inst, "pausado")
        return row
    nightly = util.is_nightly() or reason == "nightly"
    if nightly:
        install = False
    mem = (inst.cfg or {}).get("memory") or {}
    req = required(mem)
    if not req:
        row = _write_status(inst, {"state": "ready", "reason": reason, "deps": {},
                                   "detail": "memória desligada — nada a conferir"})
        _log(inst, "modo none — pulando")
        return row
    # Instância temporária (teste) com as sondas reais: não dorme nem chama docker/systemctl.
    # O teste que quer o religar injeta probes e run.
    if probes is None and run is None and decider._scratch(Path(inst.root)):
        row = _write_status(inst, {"state": "ready", "reason": reason, "deps": {},
                                   "detail": "instância temporária — não religa"})
        _log(inst, "scratch — pulando")
        return row
    probes = probes or _default_probes()
    if run is None:
        run = decider._default_run
    deps: dict[str, dict] = {}
    for name in req:
        deps[name] = _one(inst, name, mem, probes=probes, run=run, install=install,
                          nightly=nightly, reason=reason, sleep=sleep, waits=waits, pause=pause)
    # o código foi atualizado (brain update) e o servidor ainda roda a imagem/.env de antes: acompanha agora
    if "hindsight" in deps and deps.get("docker", {}).get("state", "ready") == "ready":
        try:
            synced = sync_server(inst, run=run, probes=probes, sleep=sleep, waits=max(waits, 24), pause=pause)
        except Exception as e:                                 # noqa: BLE001 — nunca derruba o watchdog
            synced = {"state": "failed", "detail": f"atualização do servidor falhou: {e}"}
        if synced:
            deps["hindsight"] = synced
    if any(d["state"] == "failed" for d in deps.values()):
        state = "failed"
    elif any(d["state"] == "starting" for d in deps.values()):
        state = "starting"
    else:
        state = "ready"
    detail = " · ".join(f"{n} {LABELS.get(d['state'], d['state'])}" for n, d in deps.items())
    row = _write_status(inst, {"state": state, "reason": reason, "deps": deps, "detail": detail})
    _log(inst, f"{reason}: {detail}")
    return row


def _one(inst, name: str, mem: dict, *, probes, run, install: bool, nightly: bool,
         reason: str, sleep, waits: int, pause: float) -> dict:
    up = probes.get(name, lambda: False)
    try:
        healthy = bool(up())
    except Exception:
        healthy = False
    if healthy:
        if name == "decider":
            flag = decider.idle_flag(inst)
            if flag.exists():
                try:
                    flag.unlink()
                except OSError:
                    pass
        return {"state": "ready", "detail": "respondendo"}
    if name == "decider" and reason == "watchdog" and decider.idle_flag(inst).exists():
        return {"state": "ready", "detail": "parado de propósito (ocioso) — abre o Brain para religar"}
    if name == "lmstudio":
        return _restart_lmstudio(inst, run=run, probes=probes, sleep=sleep, waits=waits, pause=pause)
    if name == "docker":
        return _restart_docker(inst, run=run, probes=probes, sleep=sleep, waits=waits, pause=pause)
    if name == "hindsight":
        lms_up = True
        if mem.get("embeddings_provider", "local") == "local":
            try:
                lms_up = bool(probes.get("lmstudio", lambda: False)())
            except Exception:
                lms_up = False
        blocked = hindsight_blocked(mem, lms_up)
        if blocked:
            _log(inst, blocked)
            return {"state": "failed", "detail": blocked}
        return _restart_hindsight(inst, mem, run=run, probes=probes, sleep=sleep, waits=waits, pause=pause)
    if name == "decider":
        if not decider.installed(inst):
            if nightly or not install:
                return {"state": "failed",
                        "detail": decider.NIGHTLY_REFUSE if nightly else
                        "decisor local não instalado — escolha Decisão → Local de novo para instalar"}
            return {"state": "failed",
                    "detail": "instalação do decisor é do slot, não do ensure — nada instalado aqui"}
        return _restart_decider(inst, run=run, probes=probes, sleep=sleep, waits=max(waits, 18), pause=pause)
    return {"state": "failed", "detail": f"dependência desconhecida: {name}"}


def _wait(probe, sleep, waits: int, pause: float = 5) -> bool:
    for i in range(waits):
        try:
            if probe():
                return True
        except Exception:
            pass
        if i + 1 < waits:
            sleep(pause)
    return False


def _restart_lmstudio(inst, *, run, probes, sleep, waits: int, pause: float = 5) -> dict:
    from . import setup
    if not setup.lmstudio_installed():
        return {"state": "failed",
                "detail": "LM Studio ausente — brain setup --only memoria baixa e configura"}
    run([setup.lms_bin() or "lms", "server", "start"])
    if _wait(probes["lmstudio"], sleep, waits, pause):
        return {"state": "ready", "detail": "religado em :1234"}
    return {"state": "failed", "detail": "LM Studio não respondeu em :1234"}


def _restart_docker(inst, *, run, probes, sleep, waits: int, pause: float = 5) -> dict:
    from . import setup
    if not setup.docker_installed():
        return {"state": "failed",
                "detail": "runtime de contêiner ausente — brain setup --only memoria instala"}
    if sys.platform == "darwin" and shutil_which_orb():
        run(["orbctl", "start"])
    if _wait(probes["docker"], sleep, waits, pause):
        return {"state": "ready", "detail": "runtime no ar"}
    return {"state": "failed", "detail": "runtime de contêiner não subiu"}


def shutil_which_orb() -> bool:
    import shutil
    return shutil.which("orbctl") is not None or Path("/opt/homebrew/bin/orbctl").exists()


def pinned_image(services_dir: Path | None = None) -> str:
    """A imagem do Hindsight que ESTE código pede (o pin do services/compose.yaml, sem a variável de volta)."""
    import re
    try:
        txt = ((services_dir or (FRAMEWORK / "services")) / "compose.yaml").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"^\s*image:\s*(?:\$\{BRAIN_HINDSIGHT_IMAGE:-)?([^\s}]+)", txt, re.M)
    return m.group(1) if m else ""


def running_image(run) -> str | None:
    """A imagem com que o contêiner `hindsight` foi criado; None = sem contêiner (ou sem docker)."""
    code, out = run([_docker_bin(), "inspect", "--format", "{{.Config.Image}}", "hindsight"])
    out = (out or "").strip()
    return out if code == 0 and out else None


def data_volume(run) -> str | None:
    """O volume com o banco do contêiner `hindsight` (montado em /home/hindsight/.pg0); None = não achei."""
    code, out = run([_docker_bin(), "inspect", "--format",
                     '{{range .Mounts}}{{if eq .Destination "/home/hindsight/.pg0"}}{{.Name}}{{end}}{{end}}', "hindsight"])
    out = (out or "").strip()
    return out if code == 0 and out and "/" not in out else None


def _copy_volume(run, image: str, src: str, dst: str, *, wipe_dst: bool) -> tuple[int, str]:
    """Copia volume → volume com a própria imagem do Hindsight (tem `sh`), como root: sem root a cópia falha em
    permissão e o servidor subiria num banco vazio."""
    script = ("find /to -mindepth 1 -delete && " if wipe_dst else "") + "cp -a /from/. /to/"
    return run([_docker_bin(), "run", "--rm", "--user", "0", "-v", f"{src}:/from:ro", "-v", f"{dst}:/to",
                "--entrypoint", "sh", image, "-c", script], 900)


def sync_server(inst, *, run=None, probes=None, sleep=time.sleep, waits: int = 24, pause: float = 5,
                verify_llm=None) -> dict | None:
    """Depois de um `brain update`: o servidor de memória acompanha o código. Duas coisas, nesta ordem:
      1. o config/.env do LLM no formato desta versão (providers.migrate_env — escolhas do dono preservadas);
      2. o contêiner recriado com a imagem pinada, se a que roda é outra — e conferido (health; no full, o LLM).
    A imagem nova não subiu? Recria com a anterior (o dono nunca fica sem memória) e o status diz o que falhou.
    Roda no watchdog e na abertura (código novo já no disco, qualquer que seja o código que fez o pull) e no fim do
    `brain update`. None = nada a fazer."""
    mem = (inst.cfg or {}).get("memory") or {}
    if mem.get("engine") != "hindsight" or os.environ.get("BRAIN_SERVICES_NO_KICK") == "1":
        return None
    if run is None and probes is None and decider._scratch(Path(inst.root)):
        return None
    lock = Path(inst.logs) / "server-sync.lock"     # o watchdog roda a cada 5 min; baixar ~2 GB pode levar mais
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < 30 * 60:
            return None
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    try:
        return _sync_server(inst, run=run, probes=probes, sleep=sleep, waits=waits, pause=pause, verify_llm=verify_llm)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _sync_server(inst, *, run, probes, sleep, waits: int, pause: float, verify_llm) -> dict | None:
    mem = inst.cfg["memory"]
    run = run or decider._default_run
    probes = probes or _default_probes()
    from . import config, providers
    from .core import Brain
    changed_env: list[str] = []
    if providers.env_migration_pending(mem):
        try:
            changed_env = providers.migrate_env(Brain(inst))
            _log(inst, f"sync: config/.env do LLM no formato novo ({', '.join(changed_env) or 'sem mudança'})")
        except util.BrainError as e:
            _log(inst, f"sync: migração do .env falhou — {e}")
        inst = config.load(inst.root)
        mem = inst.cfg["memory"]
    want, have = pinned_image(), running_image(run)
    if have is None or (have == want and not changed_env):
        return None                           # sem contêiner: quem cria é o ensure/setup, já com a imagem pinada
    from .memory import mode
    m = mode(mem)
    lms_up = True
    if mem.get("embeddings_provider", "local") == "local":
        try:
            lms_up = bool(probes.get("lmstudio", lambda: False)())
        except Exception:                                      # noqa: BLE001
            lms_up = False
    blocked = hindsight_blocked(mem, lms_up)
    if blocked:
        return {"state": "failed", "detail": f"servidor de memória por atualizar — {blocked}"}
    argv = [_docker_bin(), *compose_argv(Path(inst.root), m)]
    upgrading = have != want
    vol = bak = ""
    if upgrading:
        # As migrações do Hindsight rodam no boot e só andam para frente: voltar à imagem anterior sobre um banco já
        # migrado não é volta. Por isso, antes da imagem nova: baixar (falha aqui não toca em nada), parar, copiar o
        # banco para `<volume>-pre-upgrade` (fica guardado), e só então subir. A volta restaura a cópia.
        vol = data_volume(run) or ""
        if not vol:
            return {"state": "failed", "detail": "servidor de memória por atualizar — não achei o volume de dados do "
                                                 "contêiner hindsight; nada foi mudado"}
        code, out = run([_docker_bin(), "pull", want], 900)
        if code != 0:
            _log(inst, f"sync: pull {want} falhou: {out[-200:]}")
            return {"state": "failed", "detail": "servidor de memória por atualizar — a imagem nova não baixou "
                                                 "(rede?); nada foi mudado, tento de novo na próxima conferência"}
        bak = f"{vol}-pre-upgrade"
        run([_docker_bin(), "stop", "hindsight"], 120)
        run([_docker_bin(), "volume", "rm", "-f", bak])
        code, out = run([_docker_bin(), "volume", "create", bak])
        if code == 0:
            code, out = _copy_volume(run, have, vol, bak, wipe_dst=False)
        if code != 0:
            run([_docker_bin(), "start", "hindsight"], 120)
            _log(inst, f"sync: cópia de segurança falhou ({out[-200:]}) — servidor religado na versão de antes")
            return {"state": "failed", "detail": "servidor de memória por atualizar — a cópia de segurança do banco "
                                                 "falhou; o servidor voltou como estava, nada foi mudado"}
        _log(inst, f"sync: cópia de segurança do banco em {bak}")
    code, out = run(argv, 900) if upgrading else run(argv)
    _log(inst, f"sync: compose ({m}) {have} → {want} code={code} {out[-200:]}")

    def _healthy() -> tuple[bool, str]:
        if not _wait(probes["hindsight"], sleep, waits, pause):
            return False, "sem health depois de recriar"
        if m == "full":
            try:
                (verify_llm or _verify_llm)(inst)
            except Exception as e:                             # noqa: BLE001
                return False, f"health/llm falhou: {str(e)[:160]}"
        return True, ""
    ok, why = (code == 0, out[-200:]) if code != 0 else _healthy()
    if ok:
        return {"state": "ready", "detail": "servidor de memória atualizado" + (
            f" ({want.split('@')[-1][:19]}; cópia do banco de antes em {bak})" if upgrading else " (.env novo)")}
    if upgrading:                                              # volta: banco de antes + imagem de antes
        run([_docker_bin(), "stop", "hindsight"], 120)
        rcode, rout = _copy_volume(run, have, bak, vol, wipe_dst=True)
        if rcode != 0:
            _log(inst, f"sync: imagem nova falhou ({why}) e a restauração também ({rout[-200:]}) — servidor parado")
            return {"state": "failed", "detail": f"a imagem nova do Hindsight não subiu ({why}) e a restauração do "
                                                 f"banco falhou — servidor parado; a cópia intacta está no volume {bak}. "
                                                 f"Não rode `memory rebuild`; veja vault/logs/services.log"}
        run(["env", f"BRAIN_HINDSIGHT_IMAGE={have}", *argv])
        back = _wait(probes["hindsight"], sleep, waits, pause)
        _log(inst, f"sync: imagem nova falhou ({why}) — banco restaurado de {bak}, voltei para {have} "
                   f"({'ok' if back else 'sem health'})")
        return {"state": "failed", "detail": f"a imagem nova do Hindsight não subiu ({why}) — o Brain restaurou o "
                                             f"banco de antes e voltou à versão anterior; detalhes em "
                                             f"vault/logs/services.log e `docker logs hindsight`"}
    return {"state": "failed", "detail": f"servidor de memória recriado com o .env novo, mas {why}"}


def _verify_llm(inst) -> None:
    """Confere o LLM no servidor. Sonda desligada no servidor (404 "disabled" — servidor adotado, fora do compose do
    Brain) não é falha do LLM: sem como verificar, não se desfaz nada por isso."""
    from . import memory
    from .core import Brain
    try:
        memory.client(Brain(inst)).health_llm(inst.cfg["memory"]["bank"])
    except util.BrainError as e:
        if "disabled" in str(e).lower() or "ENABLE_BANK_LLM_HEALTH" in str(e):
            return
        raise


def _restart_hindsight(inst, mem: dict, *, run, probes, sleep, waits: int, pause: float = 5) -> dict:
    from .memory import mode
    m = mode(mem)
    docker = _docker_bin()
    argv = [docker, *compose_argv(Path(inst.root), m)]
    code, out = run(argv)
    _log(inst, f"compose ({m}) code={code} {out[:200]}")
    if _wait(probes["hindsight"], sleep, waits, pause):
        return {"state": "ready", "detail": f"contêiner no ar (modo {m})"}
    return {"state": "failed", "detail": f"Hindsight sem health depois do compose (modo {m})"}


def _docker_bin() -> str:
    import shutil
    orb = "/Applications/OrbStack.app/Contents/MacOS/xbin/docker"
    if Path(orb).exists():
        return orb
    return shutil.which("docker") or "docker"


def _restart_decider(inst, *, run, probes, sleep, waits: int, pause: float = 5) -> dict:
    flag = decider.idle_flag(inst)
    if flag.exists():
        try:
            flag.unlink()
        except OSError:
            pass
    decider._start_unit(inst, run=run)
    if _wait(probes["decider"], sleep, waits, pause):
        return {"state": "ready", "detail": f"respondendo em {decider.HOST_URL}"}
    return {"state": "failed", "detail": f"decisor não respondeu em {decider.HOST_URL} — ver vault/logs/decider.log"}


def kick(inst, reason: str = "open") -> None:
    """Não bloqueia a abertura: grava 'subindo' e confere numa thread."""
    if os.environ.get("BRAIN_SERVICES_NO_KICK") == "1":
        return
    _write_status(inst, {"state": "starting", "reason": reason, "deps": {},
                         "detail": "conferindo dependências"})

    def _run() -> None:
        try:
            ensure(inst, reason=reason, install=False)
        except Exception as e:  # noqa: BLE001 — a abertura não pode morrer por isto
            _write_status(inst, {"state": "failed", "reason": reason, "deps": {},
                                 "detail": f"falhou: {e}"})

    threading.Thread(target=_run, name="brain-services", daemon=True).start()


def install_watchdog(inst, *, home: Path | None = None, run=None) -> str:
    """Instala o LaunchAgent (macOS) ou a unit de usuário (Linux). Instância temporária: não mexe.

    O plist do repo traz `__BRAIN_DIR__`. Aqui o caminho é o desta instância, nunca um caminho
    de outra pessoa no arquivo commitado.
    """
    root = Path(inst.root)
    if decider._scratch(root):
        return "watchdog não instalado (instância temporária)"
    if util.is_nightly():
        return "watchdog não instalado (noturno)"
    if run is None:
        run = decider._default_run
    brain_dir = str(root)
    if sys.platform == "darwin":
        dest_dir = (home or Path.home()) / "Library" / "LaunchAgents"
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = (FRAMEWORK / "services" / "com.segundo-cerebro.watchdog.plist").read_text(encoding="utf-8")
        dest = dest_dir / "com.segundo-cerebro.watchdog.plist"
        dest.write_text(src.replace("__BRAIN_DIR__", brain_dir), encoding="utf-8")
        uid = str(os.getuid())
        run(["launchctl", "bootout", f"gui/{uid}/com.segundo-cerebro.watchdog"])
        code, _out = run(["launchctl", "bootstrap", f"gui/{uid}", str(dest)])
        return "watchdog instalado (login e a cada 5 min)" if code == 0 else "watchdog: launchctl recusou — veja a receita em guides/commands.md"
    if sys.platform == "linux":
        dest_dir = (home or Path.home()) / ".config" / "systemd" / "user"
        dest_dir.mkdir(parents=True, exist_ok=True)
        unit = dest_dir / "segundo-cerebro-watchdog.service"
        unit.write_text(
            "[Unit]\nDescription=Watchdog do Segundo Cerebro\n[Service]\nType=oneshot\n"
            f"ExecStart={brain_dir}/brain services ensure --reason watchdog\n"
            "[Install]\nWantedBy=default.target\n",
            encoding="utf-8")
        timer = dest_dir / "segundo-cerebro-watchdog.timer"
        timer.write_text(
            "[Unit]\nDescription=Watchdog do Segundo Cerebro (5 min)\n[Timer]\nOnBootSec=30\n"
            "OnUnitActiveSec=5min\n[Install]\nWantedBy=timers.target\n",
            encoding="utf-8")
        run(["systemctl", "--user", "daemon-reload"])
        code, _out = run(["systemctl", "--user", "enable", "--now", "segundo-cerebro-watchdog.timer"])
        return "watchdog instalado (systemd --user, a cada 5 min)" if code == 0 else "watchdog: systemctl recusou"
    return "watchdog: esta plataforma não tem gerenciador suportado"


def doctor_item(inst) -> dict | None:
    """Uma linha para o doctor. Sem probe de rede: lê o estado que o ensure gravou."""
    mem = (inst.cfg or {}).get("memory") or {}
    req = required(mem)
    if not req:
        return None
    st = read_status(inst)
    if st.get("at") is None and not st.get("deps"):
        return {"level": "warn", "title": "serviços",
                "detail": "ainda não conferido — abrir o Brain confere e religa (ou rode o comando services ensure)"}
    if st["state"] == "paused":
        return {"level": "ok", "title": "serviços",
                "detail": "pausado de propósito (~/.brain-watchdog-off)"}
    if st["state"] == "ready":
        return {"level": "ok", "title": "serviços",
                "detail": st.get("detail") or "pronto"}
    if st["state"] == "starting":
        return {"level": "warn", "title": "serviços",
                "detail": "subindo — a abertura não espera; a tela de Saúde atualiza"}
    return {"level": "warn", "title": "serviços",
            "detail": (st.get("detail") or "falhou") + " — ver vault/logs/services.log"}


def add_parsers(sub) -> None:
    p = sub.add_parser("services", help="dependências locais do stack (confere e religa; não instala no noturno)")
    s = p.add_subparsers(dest="scmd", required=True)
    e = s.add_parser("ensure", help="confere o que o stack exige e religa o que estiver fora")
    e.add_argument("--reason", default="cli", choices=["cli", "open", "watchdog", "update", "nightly"])
    e.add_argument("--json", action="store_true")
    st = s.add_parser("status", help="último estado gravado (pronto / subindo / falhou)")
    st.add_argument("--json", action="store_true")
    p.set_defaults(fn=cli)


def cli(args, brain) -> None:
    if args.scmd == "status":
        row = read_status(brain.inst)
    else:
        reason = "nightly" if util.is_nightly() else args.reason
        row = ensure(brain.inst, reason=reason, install=False)
    if getattr(args, "json", False):
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return
    print(f"{'✓' if row['state'] in ('ready', 'paused') else '⚠'} serviços: {row.get('label')} — {row.get('detail', '')}")
