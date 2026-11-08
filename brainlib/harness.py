"""Harnesses de código com memória no MESMO servidor do cérebro.

Plano: guides/plans/memory-harness-wizard.md. Um serviço, dois mundos:

  brain        ← derivado do vault (embed e full) — `memory rebuild` apaga e recria
  harness_bank ← memória dos agentes (default "hermes", decisão do dono 2026-11-05):
                 conversa/git dos harnesses — NUNCA tocada pelo `memory rebuild`,
                 nunca vira fato do vault.

Claude Code / Cursor CLI / Codex são conectados pelo INSTALADOR OFICIAL
(@vectorize-io/hindsight-coding-agents) em modo self-hosted apontado ao nosso
servidor — o encanamento é do upstream, não nosso. O Hermes ganha config escrita
aqui (~/.hermes/hindsight/config.json + memory.provider); o plugin em si pede
consentimento interativo e fica como receita impressa. Tudo termina em
verificação (recall ping) — perguntar é a prova.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import config, util

INSTALLER = "@vectorize-io/hindsight-coding-agents"
AGENTS = {"claude-code": "Claude Code", "cursor-cli": "Cursor CLI", "codex": "Codex CLI"}
HERMES = "hermes"
# binário que denuncia o harness na máquina (PATH) + pista do diretório do dono
_DETECT = {"claude-code": ("claude", ".claude"), "cursor-cli": ("cursor-agent", ".cursor"),
           "codex": ("codex", ".codex"), HERMES: ("hermes", ".hermes")}


def _home(home: Path | None = None) -> Path:
    return home or Path.home()


def coding_agent_config(home: Path | None = None) -> Path:
    return _home(home) / ".hindsight" / "coding-agent.json"


def hermes_config(home: Path | None = None) -> Path:
    return _home(home) / ".hermes" / "hindsight" / "config.json"


def detect(home: Path | None = None) -> dict[str, bool]:
    """Harness presente na máquina? (PATH primeiro, diretório como pista)."""
    h = _home(home)
    out = {}
    for name, (bin_, dirname) in _DETECT.items():
        out[name] = bool(shutil.which(bin_)) or (h / dirname).exists()
    return out


def merge_coding_agent(path: Path, url: str, bank: str) -> dict:
    """Escreve o ~/.hindsight/coding-agent.json do dono: servidor self-hosted, banco
    único de agente com PROVENÂNCIA (tags/metadata por repo/harness — plano §2.4).
    Merge: chaves estranhas do dono são preservadas; remove o `bankId` para voltar
    ao padrão por-repo do upstream (coding-agent::<repo>)."""
    cfg: dict = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            cfg = {}
    cfg.update({"serverMode": "self-hosted", "apiUrl": url, "bankId": bank,
                "retainTags": ["project:{gitProject}", "harness:{harness}"],
                "retainMetadata": {"repo": "{gitProject}"}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg


def _npx_ok() -> bool:
    return bool(shutil.which("npx")) and bool(shutil.which("node"))


def install(brain, agents: list[str], home: Path | None = None,
            run=subprocess.run) -> list[dict]:
    """Cabla CLIs de código pelo instalador oficial + grava [memory].harnesses.

    Sem node/npm: não falha — devolve a receita para o dono rodar depois."""
    url = brain.inst.cfg["memory"]["url"]
    results = []
    if not _npx_ok():
        for a in agents:
            results.append({"agent": a, "ok": False,
                            "hint": f"node/npm ausentes — rode depois: npx -y {INSTALLER} install {a} "
                                    f"--server self-hosted --api-url {url}"})
        return results
    for a in agents:
        if a not in AGENTS:
            results.append({"agent": a, "ok": False, "hint": f"harness desconhecido: {a!r}"})
            continue
        try:
            r = run(["npx", "-y", INSTALLER, "install", a, "--server", "self-hosted",
                     "--api-url", url], capture_output=True, text=True, timeout=300, cwd=str(_home(home)))
            ok = r.returncode == 0
            results.append({"agent": a, "ok": ok,
                            "hint": "" if ok else (r.stderr or r.stdout or "falhou")[:300]})
        except (OSError, subprocess.TimeoutExpired) as e:
            results.append({"agent": a, "ok": False, "hint": str(e)[:300]})
    if any(r["ok"] for r in results):
        bank = brain.inst.cfg["memory"]["harness_bank"]
        merge_coding_agent(coding_agent_config(home), url, bank)
        done = {a for r in results if r["ok"] for a in (r["agent"],)}
        mem = brain.inst.cfg["memory"]
        config.set_keys(brain.inst, "memory", {"harnesses": sorted(set(mem.get("harnesses") or []) | done)})
        brain.inst = config.load(brain.inst.root)     # reload() não relê config (pitfall do setup)
        brain.reload()
    return results


def wire_hermes(brain, home: Path | None = None,
                run=subprocess.run, which=shutil.which) -> dict:
    """Hermes aponta para o servidor do cérebro: config local_external + memory.provider.
    O PLUGIN em si pede consentimento interativo (TTY) — nada automatiza; a receita
    volta no resultado para o dono rodar. Ativação vale na PRÓXIMA sessão do Hermes."""
    mem = brain.inst.cfg["memory"]
    url, bank = mem["url"], mem["harness_bank"]
    p = hermes_config(home)
    cfg: dict = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            cfg = {}
    cfg.update({"mode": "local_external", "api_url": url, "bank_id": bank})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = {"config": str(p), "cli": False, "plugin_recipe": False}
    if which("hermes"):
        try:
            r = run(["hermes", "config", "set", "memory.provider", "hindsight"],
                    capture_output=True, text=True, timeout=60)
            out["cli"] = r.returncode == 0
            out["hint"] = "" if out["cli"] else (r.stderr or r.stdout or "")[:200]
        except (OSError, subprocess.TimeoutExpired) as e:
            out["hint"] = str(e)[:200]
    else:
        out["hint"] = "CLI do Hermes ausente no PATH — rode: hermes config set memory.provider hindsight"
    # plugin: o consentimento de dependências exige TTY de verdade — só detectamos
    try:
        r = run(["hermes", "memory", "status"], capture_output=True, text=True, timeout=60)
        if "not installed" in (r.stdout or "").lower():
            out["plugin_recipe"] = True
    except (OSError, subprocess.TimeoutExpired):
        pass
    config.set_keys(brain.inst, "memory", {"harnesses": sorted(set(mem.get("harnesses") or []) | {HERMES})})
    brain.inst = config.load(brain.inst.root)         # reload() não relê config (pitfall do setup)
    brain.reload()
    return out


def ping(hs, bank: str) -> bool:
    """Recall ping: pergunta qualquer coisa no banco — 200 é a prova (resposta vazia vale)."""
    try:
        hs.recall(bank, "verificação do brain: qualquer memória?")
        return True
    except util.BrainError:
        return False


def verify(brain, hs, home: Path | None = None) -> dict:
    """Estado da conexão: banco existe? ping responde? configs apontam pra cá?"""
    mem = brain.inst.cfg["memory"]
    bank = mem["harness_bank"]
    out: dict = {"bank": bank, "bank_exists": False, "ping": False, "hermes_config": False,
                 "coding_agent": False, "harnesses": list(mem.get("harnesses") or [])}
    try:
        ids = {b.get("bank_id") for b in hs.banks().get("banks", [])}
        out["bank_exists"] = bank in ids
    except util.BrainError:
        return out
    out["ping"] = out["bank_exists"] and ping(hs, bank)   # banco ausente: nem pergunta
    p = hermes_config(home)
    if p.exists():
        try:
            out["hermes_config"] = json.loads(p.read_text(encoding="utf-8")).get("api_url") == mem["url"]
        except (ValueError, OSError):
            pass
    p = coding_agent_config(home)
    if p.exists():
        try:
            out["coding_agent"] = json.loads(p.read_text(encoding="utf-8")).get("apiUrl") == mem["url"]
        except (ValueError, OSError):
            pass
    return out
