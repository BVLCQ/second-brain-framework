"""Saúde da instância — o que está quebrado aparece, em vez de apodrecer em silêncio."""
from __future__ import annotations

import json

from . import config, people, upstream, util


def _c(level: str, title: str, detail: str) -> dict:
    return {"level": level, "title": title, "detail": detail}


def checks(brain, online: bool = False, probe_agent: bool = False) -> list[dict]:
    inst, out = brain.inst, []
    cfg = inst.cfg
    if not (inst.config_dir / "brain.toml").exists():
        out.append(_c("warn", "config", "config/brain.toml ausente — rode `./brain setup`"))
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
    rs = util.read_json(inst.fresh / ".render-state.json", {})
    if rs.get("rendered_at"):
        age = (util.now() - util.parse_dt(rs["rendered_at"])).total_seconds() / 3600
        out.append(_c("ok" if age < 26 else "warn", "views", f"último render há {max(age, 0):.0f}h"))
    if cfg["memory"]["engine"] == "hindsight":
        from . import memory
        if online:
            try:
                memory.refresh_release_cache(brain.inst)   # alimenta o cache da fresnness (≤1×/dia)
            except Exception:                              # noqa: BLE001 — fresnness é informação
                pass
        status = memory.status(brain, online=online)
        out.append(_c(status["level"], "memória", status["detail"]))
        from . import providers as _prov
        for slot, s in _prov.stack(brain).items():
            if s["cloud"] and s["key_env"] and not s["key_present"]:
                out.append(_c("error", "memória",
                              f"{slot} em nuvem ({s['provider']}) sem a chave no config/.env ({s['key_env']}) — "
                              f"`brain memory providers set {slot} --provider {s['provider']} --key …`"))
        harnesses = cfg["memory"].get("harnesses") or []
        if harnesses:
            problems = []
            v = None
            try:
                from . import harness as _harness
                v = _harness.verify(brain, memory.client(brain))
            except util.BrainError as e:
                problems.append(f"sem conexão ao servidor ({e})")
            else:
                if not v["bank_exists"]:
                    problems.append(f"banco '{v['bank']}' não existe no servidor — criado no primeiro uso; "
                                    f"`brain memory harness install`")
                elif not v["ping"]:
                    problems.append(f"banco '{v['bank']}' não responde ao recall — `docker logs hindsight`")
                for name in harnesses:
                    if name == "hermes" and not v["hermes_config"]:
                        problems.append("Hermes: config não aponta para este servidor — "
                                        "`brain memory harness install hermes`")
                    elif name != "hermes" and not v["coding_agent"]:
                        problems.append(f"{name}: config do agente não aponta para este servidor — "
                                        f"`brain memory harness install {name}`")
            if problems:
                out.append(_c("warn", "harnesses", "; ".join(problems[:3])
                              + (" …" if len(problems) > 3 else "")))
            else:
                out.append(_c("ok", "harnesses",
                              f"{len(harnesses)} conectado(s) · banco '{(v or {}).get('bank', '?')}' responde ao recall"))
        if status.get("mode") == "full":
            # full é só-nuvem (regra do dono): instância legada com embeddings locais ganha aviso, não erro
            from . import providers as _prov
            if _prov.stack(brain)["embeddings"]["provider"] == "local":
                out.append(_c("warn", "memória", "full com embeddings locais (LM Studio) — o full é só-nuvem: "
                                              "`brain memory providers set embeddings --provider fireworks --key …`"))
            # régua do full: chave presente; gasto do mês como INFORMAÇÃO (sem teto — decisão do dono)
            if not any(k.startswith("HINDSIGHT_API") and k.endswith("API_KEY") and v for k, v in env.items()):
                out.append(_c("error", "memória", "modo full sem chave de LLM no config/.env — "
                                             "`brain setup --only memoria` ou volte ao embed (guides/memory.md)"))
            elif online:
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
    elif c:
        out.append(_c("ok", "framework", f"em dia (v{_ver}, verificado "
                                         + str(c.get("checked_at", ""))[:10] + ")"))
    return out


def cli(args, brain) -> None:
    res = checks(brain, online=args.online, probe_agent=args.online)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    icon = {"ok": "✓", "warn": "⚠", "error": "✗"}
    for c in res:
        print(f"{icon[c['level']]} {c['title']}: {c['detail']}")
    if any(c["level"] == "error" for c in res):
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
