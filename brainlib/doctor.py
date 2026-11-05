"""Saúde da instância — o que está quebrado aparece, em vez de apodrecer em silêncio."""
from __future__ import annotations

import json

from . import config, people, upstream, util


def _c(level: str, title: str, detail: str) -> dict:
    return {"level": level, "title": title, "detail": detail}


def checks(brain, online: bool = False) -> list[dict]:
    inst, out = brain.inst, []
    cfg = inst.cfg
    if not (inst.config_dir / "brain.toml").exists():
        out.append(_c("warn", "config", "config/brain.toml ausente — rode `./brain init --owner-id …`"))
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
        lvl = "ok" if night["ok"] and age < 30 else "warn"
        out.append(_c(lvl, "noturno", f"última execução há {age:.0f}h" + ("" if night["ok"] else " — com falhas")))
    else:
        from . import setup as _setup
        hint = ("agendado — primeira execução ainda não aconteceu" if _setup.nightly_installed()
                else "nunca rodou — `brain setup --only noturno` (ou `./brain schedule install`)")
        out.append(_c("warn", "noturno", hint))
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
        status = memory.status(brain, online=online)
        out.append(_c(status["level"], "memória", status["detail"]))
        if status.get("mode") == "full":
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
    res = checks(brain, online=args.online)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    icon = {"ok": "✓", "warn": "⚠", "error": "✗"}
    for c in res:
        print(f"{icon[c['level']]} {c['title']}: {c['detail']}")
    if any(c["level"] == "error" for c in res):
        raise SystemExit(1)
