"""Saúde da instância — o que está quebrado aparece, em vez de apodrecer em silêncio."""
from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config, people, upstream, util

ORBSTACK_DOCKER = "/Applications/OrbStack.app/Contents/MacOS/xbin/docker"
LMSTUDIO_MODELS_URL = "http://127.0.0.1:1234/v1/models"
BOOT_GRACE_S = 180
_STD_WHICH = shutil.which
_STD_RUN = subprocess.run

FRESHNESS_THRESHOLDS = {
    "dump_warn_h": 48,
    "render_warn_h": 26,
    "memory_sync_warn_h": 26,
    "inbox_warn_count": 1,
    "inbox_oldest_warn_h": 48,
}

AUTO_FIXABLE = (
    "orphan_bridge_pid",
    "fts_stale",
    "views_stale",
    "memory_unsynced",
)


def _c(level: str, title: str, detail: str) -> dict:
    return {"level": level, "title": title, "detail": detail}


def _machine_checks(cfg: dict, which=shutil.which, exists=None) -> list[dict]:
    """Dependências de máquina que o install.sh bootstrapa (plano
    guides/plans/install-bootstrap.md): git · mise · contêiner. Sempre
    `ok`/`warn` — nunca `error`: a saída do doctor gateia o modal da TUI."""
    out = []
    if which("git"):
        out.append(_c("ok", "máquina", "git presente"))
    else:
        out.append(_c("warn", "máquina", "git ausente — o instalador resolve:  sh install.sh"))
    if which("mise"):
        out.append(_c("ok", "máquina", "mise presente"))
    else:
        out.append(_c("warn", "máquina", "mise ausente — brew install mise (macOS) ou o instalador oficial (linux) e mise install"))
    mem = cfg.get("memory") if isinstance(cfg, dict) else None
    hindsight = isinstance(mem, dict) and mem.get("engine") == "hindsight"
    docker = which("docker")
    if not docker:
        if exists is not None:
            docker = ORBSTACK_DOCKER if exists(ORBSTACK_DOCKER) else None
        else:
            docker = which(ORBSTACK_DOCKER)
    if hindsight:
        out.append(_c("ok", "máquina", "runtime de contêiner presente") if docker else _c(
            "warn", "máquina",
            "docker ausente com memória ligada — `brain setup --only memoria` instala e sobe "
            "(OrbStack no macOS · Docker Engine no Linux/WSL)"))
        _lms_machine_check(cfg, out)
    elif not docker:
        out.append(_c("ok", "máquina", "docker ausente — só é preciso ao ligar a memória (embed/full)"))
    return out


def open_check(cfg: dict, which=shutil.which) -> dict:
    """Como os arquivos do vault abrem. ok/warn — nunca error (a saída gateia o modal da TUI)."""
    raw = cfg.get("open") if isinstance(cfg, dict) else None
    section = raw if isinstance(raw, dict) else {}
    mode = str(section.get("mode") or "auto")
    ide = str(section.get("ide") or "")
    found = [n for n in ("cursor", "code", "zed") if which(n)]
    if mode not in ("auto", "ide", "brain"):
        return _c("warn", "abertura", f"mode {mode!r} não é auto, ide ou brain — vale o automático")
    if mode == "brain":
        return _c("ok", "abertura", "modo brain — o arquivo abre no próprio painel")
    name = ide or (found[0] if found else "")
    if mode == "ide" and not name:
        return _c("warn", "abertura", "modo ide sem editor — preencha [open].ide ou use mode = \"brain\"")
    dest = name or "padrão do sistema"
    extra = f" (detectado: {', '.join(found)})" if found and not ide else ""
    return _c("ok", "abertura", f"modo {mode} · {dest}{extra}")


def _lms_machine_check(cfg: dict, out: list) -> None:
    """Embeddings locais (embed ou full): o LM Studio precisa existir e responder. Warn, nunca
    error (a saída gateia o modal da TUI) — e a dica acompanha o estado real: instalado com
    servidor desligado ≠ ausente (o `brain setup --only memoria` resolve os dois sozinho)."""
    from . import memory as _memory, setup
    mem = cfg.get("memory") or {}
    # exige a chave explícita (configs carregadas sempre a trazem pelo DEFAULTS): dict de teste
    # mínimo não aciona probe de rede
    if _memory.mode(mem) not in ("embed", "full") or mem.get("cloud_embeddings") \
            or mem.get("embeddings_provider") != "local":
        return
    state = setup.lmstudio_state()
    if state == "up":
        out.append(_c("ok", "máquina", "LM Studio respondendo em :1234 (embeddings locais)"))
    elif state == "installed":
        out.append(_c("warn", "máquina", "LM Studio instalado com o servidor desligado — "
                                   "`brain setup --only memoria` sobe e configura o modelo"))
    else:
        out.append(_c("warn", "máquina", "LM Studio ausente — `brain setup --only memoria` baixa e "
                                         "configura (instalador oficial, embeddings locais)"))


def _lms_embeddings_item(label: str, mem_mode: str) -> dict:
    """Item do slot Embeddings quando o provedor é `local`. No full o LLM segue na nuvem — o egresso é
    dito aqui — e o contêiner morre no boot sem o LM Studio: o estado real da máquina decide ok/warn."""
    from . import setup
    where = "embeddings local; o LLM continua na nuvem" if mem_mode == "full" else "local, sem chave"
    state = setup.lmstudio_state()
    if state == "up":
        return _c("ok", "memória · embeddings", f"{label} ({where}) — LM Studio respondendo em :1234")
    why = "instalado com o servidor desligado" if state == "installed" else "ausente"
    return _c("warn", "memória · embeddings",
              f"{label} ({where}) — LM Studio {why}: o Hindsight não sobe sem ele; "
              "`brain setup --only memoria` resolve")


def _lms_reachable(http_get=None) -> bool:
    try:
        if http_get is not None:
            r = http_get(LMSTUDIO_MODELS_URL)
            if r is False or r is None:
                return False
            return int(getattr(r, "status", getattr(r, "code", 200))) < 400
        with urllib.request.urlopen(LMSTUDIO_MODELS_URL, timeout=1) as r:
            return int(getattr(r, "status", 200)) < 400
    except Exception:  # noqa: BLE001
        return False


def _host_url(url: str) -> str:
    """Reescreve `host.docker.internal` para `localhost`: o container usa o nome do host Docker,
    mas o doctor roda fora do container."""
    if not url:
        return ""
    return re.sub(r"(?i)(https?://)host\.docker\.internal(?=[:/]|$)", r"\1localhost", url.strip())


def _decision_local_reachable(url: str, http_get=None) -> tuple[bool, str]:
    probe_url = _host_url(url)
    if not probe_url:
        return False, ""
    try:
        if http_get is not None:
            r = http_get(probe_url)
            if r is False or r is None:
                return False, probe_url
            if r is True:
                return True, probe_url
            return int(getattr(r, "status", getattr(r, "code", 200))) < 500, probe_url
        with urllib.request.urlopen(probe_url, timeout=1) as r:
            return int(getattr(r, "status", 200)) < 500, probe_url
    except Exception:  # noqa: BLE001
        return False, probe_url


def _hindsight_transient(cfg: dict | None = None, which=shutil.which, run=subprocess.run,
                         http_get=None, online: bool = True, exists=None) -> str | None:
    if which is _STD_WHICH:
        which = shutil.which
    if run is _STD_RUN:
        run = subprocess.run
    docker_bin = which("docker")
    if not docker_bin:
        docker_bin = (ORBSTACK_DOCKER if exists(ORBSTACK_DOCKER) else None) if exists is not None else which(ORBSTACK_DOCKER)
    if not docker_bin:
        return None
    try:
        res = run([docker_bin, "inspect", "--format",
                   "{{.State.Status}}|{{.State.Restarting}}|{{.State.ExitCode}}|{{.State.StartedAt}}",
                   "hindsight"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(res, "returncode", 1) != 0:
        return None
    parts = (getattr(res, "stdout", "") or "").strip().split("|", 3)
    if len(parts) < 4:
        return None
    c_status, restarting, _exit_code, started_at = (
        parts[0].strip().lower(), parts[1].strip().lower(), parts[2].strip(), parts[3].strip()
    )
    transient = restarting == "true" or c_status == "restarting"
    if not transient and c_status == "running" and started_at and not started_at.startswith("0001-"):
        try:
            norm = re.sub(r"\.(\d{6})\d+", r".\1", started_at)
            age_s = (util.now() - util.parse_dt(norm)).total_seconds()
            transient = 0 <= age_s < BOOT_GRACE_S
        except (ValueError, TypeError):
            transient = False
    if not transient:
        return None
    mem_cfg = (cfg.get("memory") if isinstance(cfg, dict) and isinstance(cfg.get("memory"), dict) else cfg) or {}
    local_emb = mem_cfg.get("embeddings_provider", "local") == "local" and not mem_cfg.get("cloud_embeddings", False)
    if (local_emb or http_get is not None) and not _lms_reachable(http_get):
        return ("Hindsight reiniciando no boot (aguardando embeddings no LM Studio) — "
                "estado transitório; rode ./brain doctor em ~2 min")
    return "Hindsight inicializando no boot — estado transitório; rode ./brain doctor em ~1 min"


def checks(brain, online: bool = False, probe_agent: bool = False, docker_probe=None,
           *, http_get=None, auth_probe=None) -> list[dict]:
    inst, out = brain.inst, []
    cfg = inst.cfg
    if not (inst.config_dir / "brain.toml").exists():
        out.append(_c("warn", "config", "config/brain.toml ausente — rode `./brain setup`"))
    out.extend(_machine_checks(cfg))
    out.append(open_check(cfg))
    for zone in ("PROFILE", "PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
        if not (inst.vault / zone).exists():
            out.append(_c("error", "vault", f"zona ausente: vault/{zone} — rode `./brain init`"))
    try:
        st = brain.state
    except util.BrainError as e:
        return out + [_c("error", "ledger", str(e))]
    if brain.owner not in st.people:
        out.append(_c("warn", "dono", f"o dono '{brain.owner}' não está registrado como pessoa no ledger"))
    problems = brain.validate_all()
    out.append(_c("error", "ledger", f"{len(problems)} problemas — rode `./brain validate`") if problems
               else _c("ok", "ledger", f"{len(st.events)} eventos íntegros"))
    plan = brain.plan
    if plan.warnings:
        out.append(_c("warn", "PLANNING", "; ".join(plan.warnings[:3])))
    elif plan.goals:
        no_due = sum(1 for d in plan.deliverables.values() if not d.due and d.status not in ("feito", "cancelado"))
        out.append(_c("warn" if no_due else "ok", "PLANNING",
                      f"{len(plan.goals)} goals · {len(plan.projects)} projetos · {len(plan.deliverables)} entregáveis"
                      + (f" · {no_due} sem prazo" if no_due else "")))
    else:
        out.append(_c("warn", "PLANNING", "nenhum goal — rode /init"))
    from . import watch
    for msg in watch.broken_links(brain):
        out.append(_c("warn", "watch", msg))
    coll = people.alias_collisions(st)
    if coll:
        out.append(_c("warn", "identidades", "aliases ambíguos: " + "; ".join(f"{a} → {', '.join(i)}"
                                                                          for a, i in coll[:3])))
    inbox = [p for p in inst.inbox.glob("*") if p.is_file() and p.name != ".keep.md"] if inst.inbox.exists() else []
    if inbox:
        oldest = min(p.stat().st_mtime for p in inbox)
        age = (util.now().timestamp() - oldest) / 86400
        out.append(_c("warn" if age > 2 else "ok", "inbox",
                      f"{len(inbox)} itens aguardando /dump (mais antigo há {max(age, 0):.0f}d)"))
    else:
        out.append(_c("ok", "inbox", "vazia"))
    night = st.runs.get("nightly")
    if night:
        age = (util.now() - util.parse_dt(night["ts"])).total_seconds() / 3600
        steps = night.get("steps") or {}
        failed = [f"{k}: {str(v).removeprefix('falhou: ')}" for k, v in steps.items() if str(v).startswith("falhou")]
        fell_back = "(fallback" in str(steps.get("agente", ""))
        lvl = "ok" if night["ok"] and age < 30 and not fell_back else "warn"
        detail = f"última execução há {age:.0f}h"
        if failed:
            detail += " — com falhas: " + "; ".join(failed)[:300]
        elif not night["ok"]:
            detail += " — com falhas"
        if fell_back:
            detail += f" — agente: {steps['agente']} (faça o login do escolhido ou troque o runner)"
        out.append(_c(lvl, "noturno", detail))
    else:
        from . import setup as _setup, runner as _runner
        foreign = _runner.foreign_schedule(inst.root)
        if _setup.nightly_installed(inst.root):
            hint = "agendado — primeira execução ainda não aconteceu"
        elif foreign:
            hint = (f"o agendamento desta máquina roda outra instância ({foreign}) — esta não tem noturno: "
                    "`brain setup --only noturno`")
        else:
            hint = "nunca rodou — `brain setup --only noturno` (ou `./brain schedule install`)"
        out.append(_c("warn", "noturno", hint))
    from . import runner
    gap = runner.mcp_gap(brain)
    if gap:
        out.append(_c("warn", "runner", gap))
    if probe_agent:
        c = runner.agent_candidates(cfg)
        if c:
            pr = runner.probe(c[0][0], cfg, cwd=inst.root)
            name, reason, auth = pr["name"], pr["reason"], pr["auth"]
            hint = runner.LOGIN_HINT.get(name, "verifique o login do comando em [runner].command")
            out.append(_c("ok", "runner", f"{name} respondeu à sonda") if pr["ok"]
                       else _c("error", "runner", f"{name}: {reason}" + (f" — {hint}" if auth else "")))
    for c in st.connectors.values():
        if c.consecutive_failures >= 2:
            out.append(_c("error", f"fonte {c.key}", f"{c.consecutive_failures} falhas seguidas — último erro: "
                                                     f"{c.last_error[:120]} (escalar ao dono)"))
        elif c.last_ok:
            out.append(_c("ok", f"fonte {c.key}", f"último pull {c.last_ok[:16].replace('T', ' ')}"))
    pending_msgs = [m for m in st.messages.values() if m.status == "rascunho"]
    approved_unsent = [m for m in st.messages.values() if m.status == "aprovada"]
    if pending_msgs:
        out.append(_c("warn", "mensagens", f"{len(pending_msgs)} rascunhos aguardando aprovação"))
    if approved_unsent:
        out.append(_c("warn", "mensagens", f"{len(approved_unsent)} aprovadas e não enviadas: "
                                           + ", ".join(m.id for m in approved_unsent)))
    proposed = [f for f in st.focus_plans.values() if f.status == "proposto"]
    if proposed:
        out.append(_c("warn", "foco", f"plano {proposed[-1].id} aguardando aprovação"))
    env = config.load_env(inst)
    if cfg["focus"]["mode"] == "google" and not all(env.get(k) for k in (
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")):
        out.append(_c("error", "calendário", "focus.mode = google, mas faltam GOOGLE_* no config/.env "
                                             "(guides/google-oauth.md) — use mode = \"ics\" até lá"))
    fb_wait = [f for f in st.feedbacks.values() if f.status in ("pendente", "falhou")]
    has_token = bool(config.load_env(inst).get("GITHUB_TOKEN"))
    if fb_wait and not has_token:
        out.append(_c("warn", "feedback", f"{len(fb_wait)} sugestão(ões) aguardando publicação e sem GITHUB_TOKEN no "
                                          "config/.env — `./brain setup --only portas`, depois `brain feedback push FB-####`"))
    elif fb_wait:
        out.append(_c("warn", "feedback", f"{len(fb_wait)} sugestão(ões) ainda não publicadas — `brain feedback list`"))
    agent_drafts = [f for f in fb_wait if f.added_by == "agent" and f.status == "pendente"]
    if agent_drafts:
        out.append(_c("warn", "feedback",
                      f"{len(agent_drafts)} rascunho(s) do agente aguardando leitura — "
                      "leia o texto na aba Sugestões antes de publicar"))
    fb_retract_asks = [
        q for q in st.questions.values()
        if q.status == "aberta" and q.kind == "permissao"
        and any(c in st.feedbacks and st.feedbacks[c].status not in ("retirado", "retratado") for c in q.context)
    ]
    if fb_retract_asks:
        fids = ", ".join(sorted({c for q in fb_retract_asks for c in q.context if c in st.feedbacks}))
        out.append(_c("warn", "feedback",
                      f"{len(fb_retract_asks)} retratação descoberta e ainda não aplicada ({fids}) — "
                      "`brain ask list --open` / `brain feedback retract`"))
    open_props = [p for p in st.proposals.values() if p.status == "aberta"]
    if open_props:
        out.append(_c("warn", "propostas", f"{len(open_props)} aguardando sua resposta"))
    open_asks = [q for q in st.questions.values() if q.status == "aberta"]
    if open_asks:
        out.append(_c("warn", "perguntas", f"{len(open_asks)} pergunta(s) do agente aguardando você (painel 4, aba Perguntas)"))
    mine = [a for a in st.actions.values() if a.open and a.owner == brain.owner and a.list == "mine"]
    no_due = [a for a in mine if not a.due]
    if no_due:
        out.append(_c("warn", "ações sem prazo", f"{len(no_due)} suas — o foco não agenda o que não tem data"))
    rs_path = inst.fresh / ".render-state.json"
    if not rs_path.exists():
        out.append(_c("warn", "views", "nunca renderizado (.render-state.json ausente) — rode `brain render`"))
    else:
        try:
            rs_raw = json.loads(rs_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            rs_raw = None
        rdt = _parse_dt_safe(rs_raw.get("rendered_at")) if isinstance(rs_raw, dict) else None
        if rdt is None:
            out.append(_c("warn", "views", ".render-state.json corrompido ou sem rendered_at — rode `brain render`"))
        else:
            age = (util.now() - rdt).total_seconds() / 3600
            out.append(_c("ok" if age < 26 else "warn", "views", f"último render há {max(age, 0):.0f}h"))
    if cfg["memory"]["engine"] == "hindsight":
        from . import memory
        if online:
            try:
                memory.refresh_release_cache(brain.inst)   # alimenta o cache da fresnness (≤1×/dia)
            except Exception:                              # noqa: BLE001 — fresnness é informação
                pass
        status = memory.status(brain, online=online)
        if status["level"] != "ok":
            if docker_probe is None:
                transient = _hindsight_transient(cfg, online=online)
            elif callable(docker_probe):
                try:
                    params = inspect.signature(docker_probe).parameters.values()
                    takes_arg = any(p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                               inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                               inspect.Parameter.VAR_POSITIONAL) for p in params)
                except (ValueError, TypeError):
                    takes_arg = True
                transient = docker_probe(cfg) if takes_arg else docker_probe()
            else:
                transient = None
            if transient:
                status = {**status, "level": "warn", "detail": transient}
        out.append(_c(status["level"], "memória", status["detail"]))
        from . import providers as _prov
        st_prov = _prov.stack(brain)
        mem_mode = status.get("mode") or memory.mode(cfg["memory"])

        # Slot LLM
        llm_ok = True
        llm_s = st_prov["llm"]
        llm_prov = llm_s["provider"]
        llm_p = _prov.PROVIDERS["llm"].get(llm_prov)
        effort_val = env.get("HINDSIGHT_API_LLM_REASONING_EFFORT", "").strip().lower()
        effort_max = effort_val == "max"
        effort_note = " · HINDSIGHT_API_LLM_REASONING_EFFORT=max é diferente do padrão (high)" if effort_max else ""
        if llm_prov == "cursor" or (llm_p and llm_p.get("docker_auth") == "unavailable"):
            out.append(_c("warn", "memória · LLM",
                          f"{llm_p['label'] if llm_p else llm_prov} — indisponível no Docker "
                          f"({(llm_p or {}).get('setup_hint', '')}; login no servidor não verificado)"))
        elif mem_mode == "embed" and llm_p and llm_p.get("docker_auth") == "manual":
            out.append(_c("warn", "memória · LLM",
                          f"{llm_p['label']} — login no servidor não verificado "
                          f"({llm_p.get('auth_command') or llm_p.get('setup_hint', '')})"))
        elif mem_mode == "embed":
            if effort_max:
                out.append(_c("warn", "memória · LLM",
                              "HINDSIGHT_API_LLM_REASONING_EFFORT=max no config/.env é diferente do padrão (high)"))
            else:
                out.append(_c("ok", "memória · LLM", "não exigido no modo embed (LLM não é chamado)"))
        elif mem_mode == "full":
            if llm_prov in _prov.LOCAL_LLM_BLOCKED:
                llm_ok = False
                out.append(_c("error", "memória · LLM",
                              f"provedor local ({llm_prov}) não é suportado no slot LLM — "
                              "escolha assinatura ou chave via `brain memory providers`"))
            elif not llm_prov:
                if env.get("HINDSIGHT_API_LLM_API_KEY"):
                    out.append(_c("warn" if effort_max else "ok", "memória · LLM",
                                  "configurado via config/.env (HINDSIGHT_API_LLM_API_KEY presente)" + effort_note))
                else:
                    llm_ok = False
                    out.append(_c("error", "memória",
                                  "modo full sem chave de LLM no config/.env — "
                                  "`brain memory providers` ou `brain setup --only memoria` (guides/memory.md)"))
            elif llm_p is None:
                llm_ok = False
                out.append(_c("error", "memória · LLM",
                              f"provedor desconhecido ({llm_prov}) — escolha via `brain memory providers`"))
            elif llm_p.get("family") == "subscription":
                if llm_p.get("docker_auth") == "manual":
                    probed_ok = False
                    if auth_probe is not None:
                        res_p = auth_probe(llm_prov) if callable(auth_probe) else auth_probe
                        probed_ok = (res_p.returncode == 0) if hasattr(res_p, "returncode") else bool(res_p)
                    if not probed_ok:
                        cmd_hint = f" · `{llm_p['auth_command']}`" if llm_p.get("auth_command") else ""
                        out.append(_c("warn", "memória · LLM",
                                      f"{llm_p['label']} — login no servidor não verificado "
                                      f"({llm_p.get('setup_hint', '')}{cmd_hint})"))
                    else:
                        out.append(_c("warn" if effort_max else "ok", "memória · LLM",
                                      f"{llm_p['label']} (assinatura — login verificado no servidor{effort_note})"))
                else:
                    auth = _prov.auth_state(brain, run=auth_probe)
                    if auth.get("state") == "pending":
                        llm_ok = False
                        out.append(_c("error", "memória · LLM",
                                      f"{llm_p['label']} sem credencial — {auth.get('note', '')} · {auth.get('fix', '')}"))
                    elif auth.get("state") == "unknown":
                        out.append(_c("warn", "memória · LLM",
                                      f"{llm_p['label']} (assinatura — {auth.get('note') or 'autenticação não verificada'})"))
                    else:
                        note = auth.get("note") if auth.get("state") == "ok" else f"verificação manual: {auth.get('note', '')}"
                        out.append(_c("warn" if effort_max else "ok", "memória · LLM",
                                      f"{llm_p['label']} (assinatura — {note}{effort_note})"))
            else:
                kenv = llm_p.get("key_env", "")
                if kenv and not env.get(kenv):
                    llm_ok = False
                    out.append(_c("error", "memória · LLM",
                                  f"LLM ({llm_prov}) sem a chave no config/.env ({kenv}) — "
                                  f"`brain memory providers set llm --provider {llm_prov} --key …`"))
                else:
                    out.append(_c("warn" if effort_max else "ok", "memória · LLM",
                                  f"{llm_p['label']} (chave presente no config/.env{effort_note})"))

        # Slot Embeddings
        emb_s = st_prov["embeddings"]
        emb_prov = emb_s["provider"]
        emb_p = _prov.PROVIDERS["embeddings"].get(emb_prov)
        if emb_prov == "local" or (emb_p and not emb_p.get("key_env")):
            if mem_mode == "full":
                out.append(_lms_embeddings_item(emb_s["label"], mem_mode))
            else:
                out.append(_c("ok", "memória · embeddings", f"{emb_s['label']} (local, sem chave)"))
        elif emb_p is None:
            out.append(_c("error", "memória · embeddings",
                          f"provedor desconhecido ({emb_prov}) — `brain memory providers`"))
        else:
            kenv = emb_p.get("key_env", "")
            if kenv and not env.get(kenv):
                out.append(_c("error", "memória · embeddings",
                              f"embeddings em nuvem ({emb_prov}) sem a chave no config/.env ({kenv}) — "
                              f"`brain memory providers set embeddings --provider {emb_prov} --key …`"))
            else:
                out.append(_c("ok", "memória · embeddings", f"{emb_s['label']} (chave presente no config/.env)"))

        # Slot Reranker
        rer_s = st_prov["reranker"]
        rer_prov = rer_s["provider"]
        rer_p = _prov.PROVIDERS["reranker"].get(rer_prov)
        if rer_prov == "off" or (rer_p and not rer_p.get("key_env")):
            out.append(_c("ok", "memória · reranker", f"{rer_s['label']}"))
        elif rer_p is None:
            out.append(_c("error", "memória · reranker",
                          f"provedor desconhecido ({rer_prov}) — `brain memory providers`"))
        else:
            kenv = rer_p.get("key_env", "")
            if kenv and not env.get(kenv):
                out.append(_c("error", "memória · reranker",
                              f"reranker em nuvem ({rer_prov}) sem a chave no config/.env ({kenv}) — "
                              f"`brain memory providers set reranker --provider {rer_prov} --key …`"))
            else:
                out.append(_c("ok", "memória · reranker", f"{rer_s['label']} (chave presente no config/.env)"))

        # Slot Decisão (opcional — off é o padrão de fábrica)
        dec_s = st_prov["decision"]
        dec_prov = dec_s["provider"]
        dec_p = _prov.PROVIDERS["decision"].get(dec_prov)
        recall_on = (bool(cfg["memory"].get("decision_recall"))
                     or env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER") == "hindsight")
        recall_warn_msg = ("recall com decisor: cada candidato é uma requisição própria, não há fallback "
                           "nesta versão do servidor (1.2.0) e o recall falha fechado se o decisor cair")
        if dec_prov in ("", "off"):
            if recall_on:
                out.append(_c("warn", "memória · decisão",
                              f"recall do decisor ligado sem provedor ativo (chave/URL ausente) — {recall_warn_msg}"))
            else:
                out.append(_c("ok", "memória · decisão",
                              "desligado (padrão) — as operações usam só o LLM; ligar corta ~40% das chamadas"))
        elif dec_p is None:
            out.append(_c("error", "memória · decisão",
                          f"provedor desconhecido ({dec_prov}) — `brain memory providers`"))
        elif dec_prov == "local":
            kenv = dec_p.get("key_env", "")
            has_key = bool(kenv and env.get(kenv))
            raw_url = env.get("HINDSIGHT_API_DECISION_MODEL_BASE_URL") or cfg["memory"].get("decision_base_url", "")
            missing = []
            if not has_key:
                missing.append(f"chave ({kenv})")
            if not raw_url:
                missing.append("base URL (HINDSIGHT_API_DECISION_MODEL_BASE_URL)")
            if missing:
                out.append(_c("warn", "memória · decisão",
                              f"decisão local sem {' e '.join(missing)} no config/.env — "
                              "`brain memory providers set decision --provider local --base-url … --key …`"
                              + (f" · {recall_warn_msg}" if recall_on else "")))
            elif http_get is not None or online:
                reach_ok, probed_url = _decision_local_reachable(raw_url, http_get=http_get)
                if not reach_ok:
                    out.append(_c("warn", "memória · decisão",
                                  f"{dec_s['label']} — servidor local inacessível em {probed_url} "
                                  "(o Brain religa ao abrir; ver vault/logs/decider.log)"))
                elif recall_on:
                    out.append(_c("warn", "memória · decisão",
                                  f"{dec_s['label']} (respondendo em {probed_url}) — recall local não é suportado "
                                  f"nesta entrega · {recall_warn_msg}"))
                else:
                    out.append(_c("ok", "memória · decisão",
                                  f"{dec_s['label']} (respondendo em {probed_url} · zero egress, cloud_decision = false)"))
            else:
                probed_url = _host_url(raw_url)
                if recall_on:
                    out.append(_c("warn", "memória · decisão",
                                  f"{dec_s['label']} (URL {probed_url}) — recall local não é suportado "
                                  f"nesta entrega · {recall_warn_msg}"))
                else:
                    out.append(_c("ok", "memória · decisão",
                                  f"{dec_s['label']} (chave e URL presentes · sonda em {probed_url} · "
                                  "zero egress, cloud_decision = false)"))
        else:
            kenv = dec_p.get("key_env", "")
            has_key = bool(kenv and env.get(kenv))
            if recall_on:
                if not has_key:
                    out.append(_c("warn", "memória · decisão",
                                  f"decisão ({dec_prov}) com recall ligado e sem a chave hsk_ no config/.env ({kenv}) — "
                                  f"{recall_warn_msg} · `brain memory providers set decision --provider hindsight "
                                  "--key … --recall on --candidates N`"))
                else:
                    cands = (cfg["memory"].get("decision_max_candidates")
                             or env.get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES") or "?")
                    out.append(_c("warn", "memória · decisão",
                                  f"{dec_s['label']} (chave presente · cloud_decision = true · top-{cands} candidatos) — "
                                  f"{recall_warn_msg}"))
            else:
                if not has_key:
                    out.append(_c("error", "memória · decisão",
                                  f"decisão ({dec_prov}) sem a chave hsk_ no config/.env ({kenv}) — "
                                  "`brain memory providers set decision --provider hindsight --key …` "
                                  "(ou volte a off)"))
                else:
                    out.append(_c("ok", "memória · decisão",
                                  f"{dec_s['label']} (chave presente) — julga antes de chamar o LLM"))

        if mem_mode == "full" and llm_ok and online:
            try:
                c = memory.cost(brain)
                out.append(_c("ok", "memória", f"gasto do mês ({c['month']}): {c['detail']} — brain memory cost"))
            except util.BrainError as e:
                out.append(_c("warn", "memória", f"medidor indisponível: {e}"))
    # ── régua da instalação (guides/setup.md): o doctor valida o que o setup montou ──
    from . import setup as _setup
    from . import index as _index_mod
    idx = _index_mod.status(brain)
    if idx.get("ok"):
        out.append(_c("ok", "índice", f"SQLite em dia · {idx['events']} eventos (FRESH/_index)"))
    elif "ausente" in idx["detail"]:
        out.append(_c("warn", "índice", "projeção SQLite ausente — `brain index rebuild` acelera "
                                      "`brain search`/`query` (sem ela, tudo continua funcionando)"))
    else:
        out.append(_c("warn", "índice", f"{idx['detail']} — rode `brain index update`"))
    cmd = _setup.brain_command_status(inst.root)
    out.append(_c("ok", "comando", f"`brain` no PATH ({cmd})") if cmd else
               _c("warn", "comando", "`brain` não está no PATH — `brain setup --only comando` "
                                     "(ou chame ./brain a partir da raiz)"))
    tui_py = _setup.FRAMEWORK / ".venv-tui" / "bin" / "python"
    if not tui_py.exists():
        out.append(_c("warn", "tui", "TUI não instalada (extra opcional) — `brain setup --only tui`"))
    raw = inst.vault / "RAW"
    big = [p for p in raw.rglob("*") if p.is_file() and p.stat().st_size > 50 * 2**20] if raw.exists() else []
    if big:
        mb = sum(p.stat().st_size for p in big) / 2**20
        out.append(_c("ok", "arquivos grandes", f"{len(big)} arquivos > 50 MB no RAW ({mb:.0f} MB) — "
                                                "fora do backup e da memória por padrão"))
    from . import perms
    pst = perms.status(inst)
    if pst["static"] != "ok":
        out.append(_c("warn", "permissões", ".claude/settings.json ausente ou desatualizado — `./brain update` (ou git pull): "
                                           "sem ele o Claude Code pergunta antes de cada comando"))
    if pst["local"] != "ok":
        out.append(_c("warn", "permissões", "MCP e pastas da instância fora da sessão interativa — `./brain agent permissions`"))
    if pst["static"] == "ok" and pst["local"] == "ok":
        out.append(_c("ok", "permissões", "sessão interativa pré-autorizada (.claude/settings.json + settings.local.json)"))
    out.extend(upstream.doctor_checks(inst))
    from . import __version__ as _ver
    c = upstream.read_check_cache(inst)
    if c and (c.get("behind") or 0) > 0:
        out.append(_c("warn", "framework", f"atualização disponível (v{_ver} → v{c.get('remote_version', '?')}, "
                                         f"{c['behind']} commits) — `brain update` (novidades: {len(c.get('news', []))})"))
    elif c and upstream.check_is_stale(c):
        out.append(_c("warn", "framework", f"sem confirmação de atualização (v{_ver}, última verificação "
                                         + str(c.get("checked_at", ""))[:16].replace("T", " ")
                                         + (" falhou" if c.get("error") else " está velha")
                                         + ") — `brain update --check`"))
    elif c:
        out.append(_c("ok", "framework", f"em dia (v{_ver}, verificado "
                                         + str(c.get("checked_at", ""))[:10] + ")"))
    from . import services as _services
    item = _services.doctor_item(inst)
    if item:
        out.append(_c(item["level"], item["title"], item["detail"]))
    return out


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return util.now()
    return now.astimezone(util.tz()) if now.tzinfo else now.replace(tzinfo=util.tz())


def _parse_dt_safe(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return util.parse_dt(value).astimezone(util.tz())
    except (ValueError, TypeError):
        return None


def _memory_state_info(brain) -> tuple[Path | None, datetime | None]:
    """Localiza `.memory-state.json` (raiz da instância ou config/) e extrai timestamp de sync."""
    inst = brain.inst
    candidates = [inst.root / ".memory-state.json", inst.config_dir / ".memory-state.json"]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return None, None
    best_path: Path | None = None
    best_dt: datetime | None = None
    for p in existing:
        dt: datetime | None = None
        data = util.read_json(p, None)
        if isinstance(data, dict):
            for key in ("synced_at", "last_sync_at", "last_sync", "ts", "updated_at"):
                dt = _parse_dt_safe(data.get(key))
                if dt is not None:
                    break
            if dt is None and isinstance(data.get("_ops"), dict):
                op_dts = []
                for bank_ops in data["_ops"].values():
                    if not isinstance(bank_ops, dict):
                        continue
                    for info in bank_ops.values():
                        if isinstance(info, dict):
                            odt = _parse_dt_safe(info.get("ts"))
                            if odt is not None:
                                op_dts.append(odt)
                if op_dts:
                    dt = max(op_dts)
        if dt is None:
            try:
                dt = datetime.fromtimestamp(p.stat().st_mtime, tz=util.tz())
            except OSError:
                dt = None
        if best_path is None or (dt is not None and (best_dt is None or dt > best_dt)):
            best_path, best_dt = p, dt
    return best_path, best_dt


def freshness(brain, *, now: datetime | None = None) -> dict:
    """Telemetria de frescor da instância (dump, render, sync da memória e backlog da inbox)."""
    cur = _coerce_now(now)
    inst = brain.inst
    cfg = inst.cfg
    th = dict(FRESHNESS_THRESHOLDS)

    # Último /dump (maior ts de artifact.added no ledger)
    dump_reason: str | None = None
    last_dump_dt: datetime | None = None
    try:
        events = brain.state.events
    except util.BrainError:
        events = []
        dump_reason = "ledger ilegível"
    for ev in events:
        if ev.get("type") == "artifact.added":
            dt = _parse_dt_safe(ev.get("ts"))
            if dt is not None and (last_dump_dt is None or dt > last_dump_dt):
                last_dump_dt = dt
    if last_dump_dt is not None:
        last_dump_at: str | None = last_dump_dt.isoformat(timespec="seconds")
        raw_dump_age_h: float | None = max((cur - last_dump_dt).total_seconds() / 3600, 0.0)
        last_dump_age_h: float | None = round(raw_dump_age_h, 2)
    else:
        last_dump_at = None
        raw_dump_age_h = None
        last_dump_age_h = None
        if dump_reason is None:
            dump_reason = "nunca dumpado"

    # Último render (FRESH/.render-state.json)
    rs = util.read_json(inst.fresh / ".render-state.json", {})
    last_render_at: str | None = None
    raw_render_age_h: float | None = None
    last_render_age_h: float | None = None
    if isinstance(rs, dict) and rs.get("rendered_at"):
        rdt = _parse_dt_safe(str(rs["rendered_at"]))
        if rdt is not None:
            last_render_at = str(rs["rendered_at"])
            raw_render_age_h = max((cur - rdt).total_seconds() / 3600, 0.0)
            last_render_age_h = round(raw_render_age_h, 2)

    # Último sync da memória (apenas quando Hindsight ativo)
    mem_enabled = cfg["memory"]["engine"] == "hindsight"
    last_memory_sync_at: str | None = None
    raw_mem_age_h: float | None = None
    last_memory_sync_age_h: float | None = None
    if mem_enabled:
        _, mem_dt = _memory_state_info(brain)
        if mem_dt is not None:
            last_memory_sync_at = mem_dt.isoformat(timespec="seconds")
            raw_mem_age_h = max((cur - mem_dt).total_seconds() / 3600, 0.0)
            last_memory_sync_age_h = round(raw_mem_age_h, 2)

    # Backlog da inbox
    inbox_files = (
        [p for p in inst.inbox.glob("*") if p.is_file() and p.name != ".keep.md" and not p.name.startswith(".")]
        if inst.inbox.exists() else []
    )
    inbox_backlog = len(inbox_files)
    if inbox_files:
        oldest_mtime = min(p.stat().st_mtime for p in inbox_files)
        raw_inbox_oldest_h: float | None = max((cur.timestamp() - oldest_mtime) / 3600, 0.0)
        inbox_oldest_age_h: float | None = round(raw_inbox_oldest_h, 2)
    else:
        raw_inbox_oldest_h = None
        inbox_oldest_age_h = None

    stale = {
        "dump": raw_dump_age_h is None or raw_dump_age_h >= th["dump_warn_h"],
        "render": raw_render_age_h is None or raw_render_age_h >= th["render_warn_h"],
        "memory_sync": mem_enabled and (raw_mem_age_h is None or raw_mem_age_h >= th["memory_sync_warn_h"]),
        "inbox": (inbox_backlog >= th["inbox_warn_count"]
                  and raw_inbox_oldest_h is not None
                  and raw_inbox_oldest_h >= th["inbox_oldest_warn_h"]),
    }

    return {
        "last_dump_at": last_dump_at,
        "last_dump_age_h": last_dump_age_h,
        "dump_reason": dump_reason,
        "last_render_at": last_render_at,
        "last_render_age_h": last_render_age_h,
        "last_memory_sync_at": last_memory_sync_at,
        "last_memory_sync_age_h": last_memory_sync_age_h,
        "inbox_backlog": inbox_backlog,
        "inbox_oldest_age_h": inbox_oldest_age_h,
        "stale": stale,
        "thresholds": th,
    }


def _default_pid_alive(pid: int) -> bool:
    # sondagem portátil: no Windows `os.kill(pid, 0)` encerra o processo em vez de sondar
    try:
        return pid > 0 and util.pid_alive(pid)
    except (OSError, ValueError, TypeError):
        return False


def _suggestion_command(c: dict) -> str:
    t = c["title"]
    detail = c.get("detail", "")
    if t == "mensagens":
        return "./brain outbox list"
    if t == "foco":
        return "./brain focus show"
    if t == "propostas":
        return "./brain proposal list"
    if t == "perguntas":
        return "./brain ask list --open"
    if t == "feedback":
        if "retrat" in detail:
            return "./brain feedback retract"
        if "GITHUB_TOKEN" in detail:
            return "./brain setup --only portas"
        return "./brain feedback list"
    if t == "PLANNING":
        return "./brain plan show"
    if t == "calendário":
        return "./brain setup --only portas"
    if t == "inbox":
        return "/dump"
    if t == "noturno":
        if "nunca rodou" in detail or "não tem noturno" in detail:
            return "./brain setup --only noturno"
        return "./brain doctor --online"
    if t == "runner":
        return "./brain agent allow" if "MCP" in detail else "./brain doctor --online"
    if t.startswith("fonte "):
        return f"/connect {t.split(' ', 1)[1]}"
    if t == "config":
        return "./brain setup"
    if t == "vault":
        return "./brain init"
    if t == "dono":
        return "./brain person add"
    if t == "ledger":
        return "./brain validate"
    if t == "watch":
        return "./brain watch list"
    if t == "identidades":
        return "./brain person list"
    if t == "ações sem prazo":
        return "./brain action list --list mine"
    if t == "memória":
        if "rebuild" in detail:
            return "./brain memory rebuild"
        if "providers" in detail or "chave de LLM" in detail:
            return "./brain memory providers show"
        return "./brain memory status"
    if t.startswith("memória · "):
        return "./brain memory providers show"
    if t == "comando":
        return "./brain setup --only comando"
    if t == "tui":
        return "./brain setup --only tui"
    if t == "permissões":
        return "./brain agent permissions" if "agent permissions" in detail else "./brain update"
    if t == "framework":
        return "./brain upstream scan" if ("upstream scan" in detail or "melhorias locais" in detail) else "./brain update"
    if t == "git fetch":
        return "./brain setup --only framework"
    if t == "hook pre-push":
        return "./brain upstream hook install"
    m = re.search(r"`(\.?/?brain [^`]+)`", detail)
    if m:
        cmd = m.group(1)
        return cmd if cmd.startswith("./") else f"./{cmd}"
    return "./brain doctor"


def _suggestion_for(c: dict) -> dict:
    return {
        "title": c["title"],
        "level": c["level"],
        "command": _suggestion_command(c),
        "reason": c["detail"],
        "gate": True,
        "fix": fix_for(c),
    }


def plan_fix(brain, *, pid_alive=None, now: datetime | None = None) -> dict:
    """Planeja auto-correções seguras (allowlist fechada) e lista achados com gate em suggestions."""
    inst = brain.inst
    cur_now = _coerce_now(now)
    alive_fn = pid_alive or _default_pid_alive
    actions: list[dict] = []

    # 1. orphan_bridge_pid
    from . import serve
    pid_file = serve.live_url_file(inst)
    if pid_file.exists():
        orphan_reason: str | None = None
        try:
            row = json.loads(pid_file.read_text(encoding="utf-8"))
            pid = int(row["pid"])
            if not alive_fn(pid):
                orphan_reason = f"PID {pid} inativo para {inst.rel(pid_file)}"
        except (OSError, ValueError, TypeError, KeyError):
            orphan_reason = f"registro ilegível da ponte em {inst.rel(pid_file)}"
        if orphan_reason:
            rel_pid = inst.rel(pid_file)
            actions.append({
                "kind": "orphan_bridge_pid",
                "title": "pidfile órfão da ponte",
                "reason": orphan_reason,
                "command": f"rm {rel_pid}",
                "targets": [rel_pid],
                "status": "planned",
            })

    # 2. fts_stale
    from . import index as _index
    db = _index.db_path(inst)
    fts_reason: str | None = None
    if not db.exists():
        fts_reason = "índice SQLite ausente"
    elif brain.ledger_path.exists() and db.stat().st_mtime < brain.ledger_path.stat().st_mtime:
        fts_reason = "índice SQLite mais antigo que o ledger"
    else:
        try:
            idx = _index.status(brain)
            if not idx.get("ok"):
                fts_reason = "índice SQLite desatualizado em relação ao ledger"
        except util.BrainError:
            fts_reason = None
    if fts_reason:
        actions.append({
            "kind": "fts_stale",
            "title": "índice SQLite desatualizado",
            "reason": fts_reason,
            "command": "./brain index rebuild",
            "targets": [inst.rel(db)],
            "status": "planned",
        })

    # 3. views_stale
    rs_path = inst.fresh / ".render-state.json"
    fresh_m = freshness(brain, now=cur_now)
    views_reason: str | None = None
    if not rs_path.exists():
        views_reason = "views ainda não geradas"
    else:
        rs = util.read_json(rs_path, {})
        rendered_at = rs.get("rendered_at") if isinstance(rs, dict) else None
        rdt = _parse_dt_safe(str(rendered_at)) if rendered_at else None
        if rdt is None:
            views_reason = "estado de renderização inválido ou sem rendered_at"
        else:
            rs_mtime = rs_path.stat().st_mtime
            for src in (brain.ledger_path, inst.planning_file):
                if not src.exists():
                    continue
                src_mtime = src.stat().st_mtime
                if src_mtime > rs_mtime or (src_mtime <= cur_now.timestamp() + 5 and int(src_mtime) > int(rdt.timestamp())):
                    views_reason = f"views mais antigas que {inst.rel(src)}"
                    break
            if not views_reason and fresh_m["stale"]["render"]:
                views_reason = f"views sem render recente (>= {FRESHNESS_THRESHOLDS['render_warn_h']}h)"
    if views_reason:
        actions.append({
            "kind": "views_stale",
            "title": "views desatualizadas",
            "reason": views_reason,
            "command": "./brain render",
            "targets": ["FRESH/"],
            "status": "planned",
        })

    # 4. memory_unsynced
    if inst.cfg["memory"]["engine"] == "hindsight":
        from . import memory as _memory
        state_path, _ = _memory_state_info(brain)
        mem_reason: str | None = None
        if state_path is None:
            mem_reason = ".memory-state.json ausente"
        else:
            try:
                pend = _memory.pending(brain)
            except util.BrainError:
                pend = []
            if pend:
                mem_reason = f"{len(pend)} documento(s) pendente(s) de sync"
            elif brain.ledger_path.exists() and state_path.stat().st_mtime < brain.ledger_path.stat().st_mtime:
                mem_reason = ".memory-state.json mais antigo que o ledger"
        if mem_reason:
            target = util.relpath(state_path, inst.root) if state_path else "config/.memory-state.json"
            actions.append({
                "kind": "memory_unsynced",
                "title": "memória dessincronizada",
                "reason": mem_reason,
                "command": "./brain memory sync",
                "targets": [target],
                "status": "planned",
            })

    # Achados não auto-corrigíveis (sempre gate=True, nunca em actions)
    planned_kinds = {a["kind"] for a in actions}
    suggestions: list[dict] = []
    for c in checks(brain):
        if c["level"] == "ok":
            continue
        t = c["title"]
        if t == "views" and "views_stale" in planned_kinds:
            continue
        if t == "índice" and "fts_stale" in planned_kinds:
            continue
        if (t == "memória" and "memory_unsynced" in planned_kinds
                and "documentos do vault ainda não enviados" in c["detail"]
                and "fora do ar" not in c["detail"]
                and "erro" not in c["detail"].lower()):
            continue
        suggestions.append(_suggestion_for(c))

    try:
        pending_pub = [s for s in brain.state.shares.values() if s.status in ("solicitada", "aprovada")]
    except util.BrainError:
        pending_pub = []
    if pending_pub:
        ids_str = ", ".join(sorted(s.id for s in pending_pub))
        suggestions.append({
            "title": "publicação",
            "level": "warn",
            "command": "./brain publish list",
            "reason": f"{len(pending_pub)} publicação(ões) aguardando aprovação/envio ({ids_str})",
            "gate": True,
            "fix": None,
        })

    return {"mode": "dry-run", "actions": actions, "suggestions": suggestions}


def format_fix_diff(plan: dict) -> str:
    """Formata o plano do `--fix` de forma determinística (sem timestamps voláteis)."""
    lines = []
    for a in plan.get("actions", []):
        targets = ", ".join(a.get("targets") or []) or "-"
        lines.append(f"+ [{a['kind']}] {a['command']} -> {targets} ({a['reason']})")
    for s in plan.get("suggestions", []):
        lines.append(f"! [{s['title']}] {s['command']} ({s['reason']})")
    return "\n".join(lines) if lines else "✓ nada a corrigir"


def _call_fix_handler(fn, brain, action: dict):
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (ValueError, TypeError):
        return fn(brain)
    has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    pos = [p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                           inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    req = [p for p in pos if p.default is inspect.Parameter.empty]
    if not pos and not has_var:
        return fn()
    if len(req) >= 2:
        return fn(brain, action)
    return fn(brain)


def _default_fix_handlers() -> dict:
    from . import index as _index, memory as _memory, render as _render, serve as _serve
    return {
        "orphan_bridge_pid": lambda b: _serve.live_url_file(b.inst).unlink(missing_ok=True),
        "fts_stale": lambda b: _index.rebuild(b),
        "views_stale": lambda b: _render.render_all(b),
        "memory_unsynced": lambda b: _memory.sync(b),
    }


def apply_fix(brain, plan: dict | None = None, *, pid_alive=None, handlers: dict | None = None) -> dict:
    """Executa as ações seguras planejadas na ordem da allowlist e grava `vault/logs/doctor-fix.log`."""
    if plan is None:
        plan = plan_fix(brain, pid_alive=pid_alive)
    order = {kind: idx for idx, kind in enumerate(AUTO_FIXABLE)}
    raw_actions = sorted(
        plan.get("actions", []),
        key=lambda a: order.get(a.get("kind", ""), len(AUTO_FIXABLE)),
    )
    suggestions = [dict(s) for s in plan.get("suggestions", [])]
    defaults = _default_fix_handlers()
    executed: list[dict] = []

    for act in raw_actions:
        item = dict(act)
        kind = item.get("kind", "")
        if kind not in order:
            item["status"] = "failed"
            item["error"] = f"classe fora da allowlist: {kind!r}"
            executed.append(item)
            continue
        fn = handlers[kind] if handlers and kind in handlers else defaults[kind]
        try:
            res = _call_fix_handler(fn, brain, item)
            if kind == "memory_unsynced" and isinstance(res, dict) and res.get("errors"):
                item["status"] = "failed"
                item["error"] = "; ".join(str(e) for e in res["errors"])
            else:
                item["status"] = "applied"
        except Exception as e:  # noqa: BLE001 — isolamento por ação
            item["status"] = "failed"
            item["error"] = str(e)
        executed.append(item)

    log_path = brain.inst.logs / "doctor-fix.log"
    brain.inst.logs.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": util.iso_now(),
        "mode": "apply",
        "applied": sum(1 for a in executed if a["status"] == "applied"),
        "failed": sum(1 for a in executed if a["status"] == "failed"),
        "actions": [
            {
                "kind": a["kind"],
                "command": a["command"],
                "targets": a.get("targets", []),
                "status": a["status"],
                **({"error": a["error"]} if "error" in a else {}),
            }
            for a in executed
        ],
        "suggestions": len(suggestions),
    }
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {
        "mode": "apply",
        "actions": executed,
        "suggestions": suggestions,
        "log": brain.inst.rel(log_path),
    }


def cli(args, brain) -> None:
    dry_run = bool(getattr(args, "dry_run", False))
    apply = bool(getattr(args, "apply", False))
    fix = bool(getattr(args, "fix", False))
    if dry_run and apply:
        raise util.BrainError("use --dry-run ou --apply, não os dois juntos", code=4)
    if not fix:
        if dry_run or apply:
            raise util.BrainError("--dry-run e --apply exigem --fix", code=4)
        res = checks(brain, online=args.online, probe_agent=args.online)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return
        icon = {"ok": "✓", "warn": "⚠", "error": "✗"}
        for c in res:
            print(f"{icon[c['level']]} {c['title']}: {c['detail']}")
        if any(c["level"] == "error" for c in res):
            raise SystemExit(1)
        return

    if not apply:
        plan = plan_fix(brain)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(format_fix_diff(plan))
        return

    res = apply_fix(brain)
    post = checks(brain, online=False, probe_agent=False)
    remaining_errors = sum(1 for c in post if c["level"] == "error")
    if args.json:
        out = {**res, "remaining_errors": remaining_errors}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not res["actions"] and not res["suggestions"]:
            print("✓ nada a corrigir")
        else:
            for a in res["actions"]:
                targets = ", ".join(a.get("targets") or []) or "-"
                if a["status"] == "applied":
                    print(f"✓ [{a['kind']}] {a['command']} -> {targets}")
                else:
                    print(f"✗ [{a['kind']}] {a['command']} -> {targets}: {a.get('error', 'falhou')}")
            for s in res["suggestions"]:
                print(f"! [{s['title']}] {s['command']} ({s['reason']})")
    if any(a["status"] == "failed" for a in res["actions"]) or remaining_errors > 0:
        raise SystemExit(1)


def fix_for(c: dict) -> dict | None:
    """O que dá para fazer a respeito de um aviso (tecla f no TUI e no painel). `go` = (painel, aba) do TUI;
    `page` = a página equivalente do painel HTML."""
    if c["level"] == "ok" and not c["title"].startswith("fonte "):
        return None
    t = c["title"]
    if t == "inbox":
        return {"label": "processar com o agente", "agent": "dump"}
    if t == "noturno":
        detail = c["detail"]
        return ({"label": "agendar o noturno", "sys": "sys:schedule"}
                if ("nunca rodou" in detail or "não tem noturno" in detail) else None)
    if t == "ações sem prazo":
        return {"label": "ir às ações e dar prazo", "go": (2, 0), "page": "todo"}
    if t.startswith("fonte "):
        return {"label": "puxar agora com o agente", "agent": "connect", "key": t.split(" ", 1)[1]}
    if t == "mensagens":
        return {"label": "ir ao outbox", "go": (4, 2), "page": "outbox"}
    if t == "foco":
        return {"label": "ir ao plano de foco", "go": (4, 3), "page": "focus"}
    if t == "propostas":
        return {"label": "ir às propostas", "go": (4, 1), "page": "ask"}
    if t == "perguntas":
        return {"label": "ir às perguntas do agente", "go": (4, 0), "page": "ask"}
    return None
