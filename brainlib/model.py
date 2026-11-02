"""View model: o retrato derivado que TODAS as superfícies consomem.

Painel HTML, páginas Markdown, servidor MCP e exports compartilháveis leem
daqui — uma única fonte de cálculo para progresso, saúde, atrasos e conquistas.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from . import portfolio, util
from .state import Action, State

KANBAN = {"aberta": "a fazer", "fazendo": "fazendo", "aguardando": "aguardando",
          "bloqueada": "bloqueada", "fechada": "feita", "descartada": "descartada"}
HEALTH_ORDER = ["em-risco", "travado", "atencao", "em-dia", "concluido", "congelado", "fechado"]
HEALTH_LABEL = {"em-risco": "em risco", "travado": "travado", "atencao": "atenção",
                "em-dia": "em dia", "concluido": "concluído", "congelado": "congelado",
                "fechado": "fechado"}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


class ModelBuilder:
    def __init__(self, brain):
        self.b = brain
        self.st: State = brain.state
        self.plan = brain.plan
        self.cfg = brain.inst.cfg
        self.owner = brain.owner
        self.today = util.today()

    # ── rótulos ────────────────────────────────────────────────────────────
    def source_label(self, source: str) -> str:
        if not source:
            return "sem fonte registrada"
        if source == "chat":
            return "declarado no chat"
        art = self.st.artifacts.get(source.split("#")[0])
        if art:
            return f"{art.title} ({util.fmt_date(art.date)})"
        return Path(source.split("#")[0]).name

    def ref_project(self, ref: str | None) -> str | None:
        if not ref:
            return None
        if ref in self.st.actions:
            a = self.st.actions[ref]
            return a.project or self.plan.project_of(a.deliverable)
        return self.plan.project_of(ref)

    # ── entidades ──────────────────────────────────────────────────────────
    def action(self, a: Action) -> dict:
        eff = self.st.effective_status(a)
        project = a.project or self.plan.project_of(a.deliverable)
        overdue = (self.today - a.due).days if a.open and a.due and a.due < self.today else 0
        last = a.last_activity or a.opened
        return {
            "id": a.id, "title": a.title, "owner": a.owner, "owner_name": self.st.person_name(a.owner),
            "list": a.list, "status": eff, "kanban": KANBAN.get(eff, eff), "open": a.open,
            "mine": a.owner == self.owner,
            "due": _iso(a.due), "due_in": (a.due - self.today).days if a.open and a.due else None,
            "due_suggested": bool(a.open and a.due and a.due_suggested), "due_reason": a.due_reason,
            "overdue_days": overdue,
            "aging_days": (self.today - last).days if a.open and last else None,
            "effort_min": a.effort_min, "priority": a.priority, "parked": bool(a.open and a.parked),
            "project": project, "project_title": self.plan.title(project) if project else None,
            "goal": self.plan.goal_of(project), "deliverable": a.deliverable,
            "blocked_by": self.st.blocked(a), "blocked_by_all": a.blocked_by, "unblocks": a.unblocks,
            "people": a.people, "link": a.link, "origin": a.origin,
            "source": a.source, "source_label": self.source_label(a.source), "prov": a.prov,
            "opened": _iso(a.opened), "closed": _iso(a.closed), "how": a.how, "outcome": a.outcome,
            "history": [{"date": e.get("date"), "ts": e.get("ts"), "type": e["type"].split(".")[1],
                         "by": e.get("by"), "note": self._note(e)} for e in a.history],
        }

    @staticmethod
    def _note(ev: dict) -> str:
        d = ev.get("data", {})
        return d.get("note") or d.get("how") or d.get("reason") or d.get("title") or \
            ", ".join(f"{k}={v}" for k, v in d.items() if k not in ("title",))

    def decision(self, d) -> dict:
        project = d.project
        return {
            "id": d.id, "title": d.title, "date": _iso(d.date), "decided_by": d.decided_by,
            "decided_by_names": [self.st.person_name(p) for p in d.decided_by],
            "project": project, "project_title": self.plan.title(project) if project else None,
            "goal": self.plan.goal_of(project), "context": d.context, "rationale": d.rationale,
            "status": d.status, "supersedes": d.supersedes, "superseded_by": d.superseded_by,
            "source": d.source, "source_label": self.source_label(d.source), "prov": d.prov,
        }

    def delivery(self, e) -> dict:
        project = self.ref_project(e.ref)
        return {
            "id": e.id, "title": e.title, "date": _iso(e.date), "ref": e.ref,
            "project": project, "project_title": self.plan.title(project) if project else None,
            "result": e.result or "resultado não declarado", "evidence": e.evidence,
            "impact": e.impact, "prov": e.prov, "source": e.source,
            "source_label": self.source_label(e.source),
        }

    def artifact(self, a) -> dict:
        return {"id": a.id, "kind": a.kind, "title": a.title, "date": _iso(a.date), "raw": a.raw,
                "people": a.people, "projects": a.projects, "summary": a.summary, "prov": a.prov}

    # ── agregados ──────────────────────────────────────────────────────────
    def deliverable_done_events(self) -> list[dict]:
        out = []
        for did, evs in self.st.deliverable_events.items():
            for ev in evs:
                if ev["data"]["status"] == "feito" and did in self.plan.deliverables:
                    out.append({"id": did, "date": ev.get("date"), "title": self.plan.title(did),
                                "project": self.plan.project_of(did), "by": ev.get("by"),
                                "evidence": ev["data"].get("evidence", ""), "prov": ev.get("prov")})
        known = {(x["id"]) for x in out}
        for did, d in self.plan.deliverables.items():
            if d.done and d.done_date and did not in known:
                out.append({"id": did, "date": _iso(d.done_date), "title": d.title,
                            "project": d.project_id, "by": "owner", "evidence": "PLANNING/goals.md",
                            "prov": "declarado"})
        return out

    def project_activity(self) -> dict[str, date]:
        last: dict[str, date] = {}

        def bump(pid: str | None, d) -> None:
            d = util.parse_date(d) if d and not isinstance(d, date) else d
            if pid and d and (pid not in last or d > last[pid]):
                last[pid] = d

        for a in self.st.actions.values():
            pid = a.project or self.plan.project_of(a.deliverable)
            for ev in a.history:
                bump(pid, ev.get("date"))
        for d in self.st.decisions.values():
            bump(d.project, d.date)
        for art in self.st.artifacts.values():
            for pid in art.projects:
                bump(pid, art.date)
        for did, evs in self.st.deliverable_events.items():
            for ev in evs:
                bump(self.plan.project_of(did), ev.get("date"))
        for e in self.st.deliveries.values():
            bump(self.ref_project(e.ref), e.date)
        return last

    def project_health(self, proj, prog: dict, actions: list[dict], last: date | None) -> dict:
        status = proj.status
        if status not in ("ativo", "ativa"):
            key = "congelado" if status.startswith("congel") else "fechado"
            return {"level": key, "label": HEALTH_LABEL[key], "reason": f"projeto {status}"}
        if prog["total"] and prog["done"] == prog["total"]:
            return {"level": "concluido", "label": "concluído", "reason": "todos os entregáveis feitos"}
        open_d = [d for d in proj.deliverables if d.status not in ("feito", "cancelado")]
        late_d = sorted((d for d in open_d if d.due and d.due < self.today), key=lambda d: d.due)
        if late_d:
            n = (self.today - late_d[0].due).days
            return {"level": "em-risco", "label": "em risco",
                    "reason": f"{late_d[0].id} venceu há {n}d ({late_d[0].title})"}
        late_a = sorted((a for a in actions if a["mine"] and a["overdue_days"]),
                        key=lambda a: -a["overdue_days"])
        if late_a:
            return {"level": "em-risco", "label": "em risco",
                    "reason": f"{late_a[0]['id']} atrasada {late_a[0]['overdue_days']}d"}
        stale_days = self.cfg["views"]["stale_project_days"]
        idle = (self.today - last).days if last else None
        if (idle is None or idle > stale_days) and (open_d or any(a["open"] for a in actions)):
            why = f"sem movimento há {idle}d" if idle is not None else "nenhum movimento registrado"
            return {"level": "travado", "label": "travado", "reason": why}
        soon = sorted((d for d in open_d if d.due and (d.due - self.today).days <= 7), key=lambda d: d.due)
        if soon:
            n = (soon[0].due - self.today).days
            return {"level": "atencao", "label": "atenção",
                    "reason": f"{soon[0].id} vence em {n}d" if n else f"{soon[0].id} vence hoje"}
        return {"level": "em-dia", "label": "em dia",
                "reason": f"último movimento {util.fmt_date(last)}" if last else "sem prazos próximos"}

    def build(self) -> dict:
        st, plan, today = self.st, self.plan, self.today
        actions = [self.action(a) for a in st.actions.values()]
        by_id = {a["id"]: a for a in actions}
        decisions = sorted((self.decision(d) for d in st.decisions.values()),
                           key=lambda d: (d["date"] or "", d["id"]), reverse=True)
        deliveries = sorted((self.delivery(e) for e in st.deliveries.values()),
                            key=lambda e: (e["date"] or "", e["id"]), reverse=True)
        artifacts = sorted((self.artifact(a) for a in st.artifacts.values()),
                           key=lambda a: a["date"] or "", reverse=True)
        deliv_done = self.deliverable_done_events()
        activity = self.project_activity()

        projects = []
        for pid, proj in plan.projects.items():
            prog = plan.progress(pid)
            p_actions = [a for a in actions if a["project"] == pid]
            declared = (st.progress.get(pid) or [None])[-1]
            people: dict[str, dict] = {}

            def role(person: str, r: str) -> None:
                if person not in st.people:
                    return
                entry = people.setdefault(person, {"id": person, "name": st.person_name(person),
                                                   "roles": [], "count": 0})
                entry["count"] += 1
                if r not in entry["roles"]:
                    entry["roles"].append(r)

            for a in p_actions:
                role(a["owner"], "dono de ação")
                for p in a["people"]:
                    role(p, "envolvido")
            p_decisions = [d for d in decisions if d["project"] == pid]
            for d in p_decisions:
                for p in d["decided_by"]:
                    role(p, "decidiu")
            p_artifacts = [x for x in artifacts if pid in x["projects"]]
            for x in p_artifacts:
                for p in x["people"]:
                    role(p, "citado")
            if proj.owner:
                role(proj.owner, "dono do projeto")
            timeline = self._timeline_for(pid, p_actions, p_decisions, deliveries, deliv_done, p_artifacts)
            open_dl = [d for d in proj.deliverables if d.status not in ("feito", "cancelado") and d.due]
            nxt = min(open_dl, key=lambda d: d.due) if open_dl else None
            last = activity.get(pid)
            projects.append({
                "id": pid, "title": proj.title, "goal": proj.goal_id, "goal_title": plan.title(proj.goal_id),
                "status": proj.status, "owner": proj.owner, "meta": proj.meta, "progress": prog,
                "declared": {"pct": declared["pct"], "date": _iso(declared["date"]), "note": declared["note"]}
                if declared else None,
                "deliverables": [{
                    "id": d.id, "title": d.title, "status": d.status, "due": _iso(d.due),
                    "done_date": _iso(d.done_date), "weight": d.weight,
                    "overdue_days": (today - d.due).days if d.due and d.due < today
                    and d.status not in ("feito", "cancelado") else 0,
                    "due_in": (d.due - today).days if d.due else None,
                } for d in proj.deliverables],
                "decisions": [d["id"] for d in p_decisions],
                "actions": {
                    "mine": [a["id"] for a in p_actions if a["open"] and a["list"] == "mine"],
                    "waiting": [a["id"] for a in p_actions if a["open"] and a["list"] == "waiting"],
                    "watching": [a["id"] for a in p_actions if a["open"] and a["list"] == "watching"],
                    "closed": [a["id"] for a in sorted(p_actions, key=lambda a: a["closed"] or "",
                                                       reverse=True) if not a["open"]][:15],
                },
                "people": sorted(people.values(), key=lambda p: -p["count"]),
                "artifacts": [x["id"] for x in p_artifacts[:20]],
                "timeline": timeline,
                "last_activity": _iso(last),
                "health": self.project_health(proj, prog, p_actions, last),
                "next_due": {"id": nxt.id, "title": nxt.title, "date": _iso(nxt.due)} if nxt else None,
            })

        goals = []
        proj_by_id = {p["id"]: p for p in projects}
        for gid, g in plan.goals.items():
            declared = (st.progress.get(gid) or [None])[-1]
            ps = [proj_by_id[p.id] for p in g.projects]
            worst = min((p["health"]["level"] for p in ps), key=HEALTH_ORDER.index, default="em-dia")
            lasts = [p["last_activity"] for p in ps if p["last_activity"]]
            goals.append({
                "id": gid, "title": g.title, "status": g.status, "horizon": g.horizon, "why": g.why,
                "progress": plan.progress(gid),
                "declared": {"pct": declared["pct"], "date": _iso(declared["date"]), "note": declared["note"]}
                if declared else None,
                "projects": [p["id"] for p in ps], "health": worst, "health_label": HEALTH_LABEL[worst],
                "last_activity": max(lasts) if lasts else None,
            })

        people = self._people(actions, decisions, artifacts)
        wins = self._wins(deliveries, deliv_done, actions, decisions)
        mine_open = [a for a in actions if a["open"] and a["mine"] and a["list"] == "mine"]
        waiting = [a for a in actions if a["open"] and a["list"] == "waiting"]
        horizon7 = today + timedelta(days=7)
        agenda = self._agenda(mine_open, projects, horizon7)
        focus = self._focus()
        return {
            "generated_at": util.iso_now(), "today": today.isoformat(),
            "owner": {"id": self.owner, "name": self.cfg["owner"]["name"]},
            "goals": goals, "projects": projects, "actions": actions, "decisions": decisions,
            "deliveries": deliveries, "deliverables_done": sorted(deliv_done, key=lambda x: x["date"] or "",
                                                                  reverse=True),
            "artifacts": artifacts, "people": people, "wins": wins, "agenda": agenda,
            "timeline": self._timeline(projects, deliveries, deliv_done, decisions, actions, artifacts),
            "focus": focus,
            "proposals": [{"id": p.id, "kind": p.kind, "summary": p.summary, "target": p.target, "into": p.into,
                           "evidence": p.evidence, "date": _iso(p.date)}
                          for p in st.proposals.values() if p.status == "aberta"],
            "outbox": [{"id": m.id, "to": m.to, "to_name": st.person_name(m.to) if not m.to.startswith("#")
                        else m.to, "text": m.text, "status": m.status, "ref": m.ref, "why": m.why,
                        "drafted": _iso(m.drafted), "sent": _iso(m.sent), "link": m.link}
                       for m in sorted(st.messages.values(), key=lambda m: m.id, reverse=True)],
            "shares": [{"id": s.id, "report": s.report, "destination": s.destination, "status": s.status,
                        "link": s.link, "date": _iso(s.date)} for s in st.shares.values()],
            "plan_changes": [{**c, "date": _iso(c["date"])} for c in st.plan_changes],
            "plan_warnings": plan.warnings,
            "feedback": [{"id": f.id, "kind": f.kind, "title": f.title, "body": f.body, "context": f.context,
                          "status": f.status,
                          "number": f.number, "url": f.url, "issue_state": f.issue_state,
                          "issue_reason": f.issue_reason, "error": f.error, "added": _iso(f.added),
                          "pushed": _iso(f.pushed), "synced": _iso(f.synced)}
                         for f in sorted(st.feedbacks.values(), key=lambda f: f.id, reverse=True)],
            "portfolio": portfolio.build(st, plan, today),
            "questions": [{"id": q.id, "text": q.text, "kind": q.kind, "status": q.status, "options": q.options,
                           "context": q.context, "run": q.run, "answer": q.answer, "asked": _iso(q.asked)}
                          for q in sorted(st.questions.values(), key=lambda q: q.id) if q.status in ("aberta", "respondida")],
            "counts": {
                "mine_open": len(mine_open),
                "mine_overdue": sum(1 for a in mine_open if a["overdue_days"]),
                "mine_due_7d": sum(1 for a in mine_open if a["due_in"] is not None and 0 <= a["due_in"] <= 7),
                "mine_blocked": sum(1 for a in mine_open if a["status"] == "bloqueada"),
                "waiting_open": len(waiting),
                "watching_open": sum(1 for a in actions if a["open"] and a["list"] == "watching"),
                "wins_30d": wins["last_30d"],
                "decisions_30d": sum(1 for d in decisions
                                     if d["date"] and (today - date.fromisoformat(d["date"])).days <= 30),
                "proposals_open": sum(1 for p in st.proposals.values() if p.status == "aberta"),
                "questions_open": sum(1 for q in st.questions.values() if q.status == "aberta"),
                "outbox_pending": sum(1 for m in st.messages.values() if m.status in ("rascunho", "aprovada")),
                "feedback_pending": sum(1 for f in st.feedbacks.values() if f.status in ("pendente", "falhou")),
                "mine_no_due": sum(1 for a in mine_open if not a["due"]),
                "mine_no_effort": sum(1 for a in mine_open if not a["effort_min"]),
            },
            "by_id": {"actions": list(by_id)},
        }

    def _timeline_for(self, pid, p_actions, p_decisions, deliveries, deliv_done, p_artifacts) -> list[dict]:
        items = []
        for x in p_artifacts:
            if x["kind"] == "reuniao":
                items.append({"date": x["date"], "kind": "reunião", "id": x["id"], "title": x["title"]})
        for d in p_decisions:
            items.append({"date": d["date"], "kind": "decisão", "id": d["id"], "title": d["title"],
                          "who": ", ".join(d["decided_by_names"])})
        for e in deliveries:
            if e["project"] == pid:
                items.append({"date": e["date"], "kind": "entrega", "id": e["id"], "title": e["title"]})
        for x in deliv_done:
            if x["project"] == pid:
                items.append({"date": x["date"], "kind": "entregável", "id": x["id"], "title": x["title"]})
        for a in p_actions:
            items.append({"date": a["opened"], "kind": "ação aberta", "id": a["id"], "title": a["title"],
                          "who": a["owner_name"]})
            if a["closed"]:
                items.append({"date": a["closed"], "kind": "ação fechada" if a["status"] == "fechada"
                              else "ação descartada", "id": a["id"], "title": a["title"], "who": a["owner_name"]})
        return sorted((i for i in items if i["date"]), key=lambda i: (i["date"], i["id"]), reverse=True)

    def _people(self, actions, decisions, artifacts) -> list[dict]:
        # índices por pessoa numa passada só (antes: pessoas × ações/artefatos/decisões); a ordem das listas é a de origem
        arts_of: dict[str, list[dict]] = {}
        owes_of: dict[str, list[str]] = {}
        i_owe_of: dict[str, list[str]] = {}
        proj_of: dict[str, set[str]] = {}
        decs_of: dict[str, list[str]] = {}
        for x in artifacts:
            for pid in dict.fromkeys(x["people"]):
                arts_of.setdefault(pid, []).append(x)
        for a in actions:
            if a["open"]:
                owes_of.setdefault(a["owner"], []).append(a["id"])
                if a["mine"]:
                    for pid in dict.fromkeys(a["people"]):
                        i_owe_of.setdefault(pid, []).append(a["id"])
            if a["project"]:
                for pid in {a["owner"], *a["people"]}:
                    proj_of.setdefault(pid, set()).add(a["project"])
        for d in decisions:
            for pid in dict.fromkeys(d["decided_by"]):
                decs_of.setdefault(pid, []).append(d["id"])
                if d["project"]:
                    proj_of.setdefault(pid, set()).add(d["project"])
        out = []
        for pid, p in self.st.people.items():
            arts = arts_of.get(pid, [])
            meetings = [x for x in arts if x["kind"] == "reuniao"]
            last = (meetings or arts or [None])[0]
            owes_me = owes_of.get(pid, []) if pid != self.owner else []
            i_owe = i_owe_of.get(pid, [])
            projects = sorted(proj_of.get(pid, set()) | {pr for x in arts for pr in x["projects"]})
            out.append({
                "id": pid, "name": p.name, "aliases": p.aliases, "role": p.role, "relation": p.relation,
                "email": p.email, "is_owner": pid == self.owner,
                "last_interaction": {"date": last["date"], "title": last["title"], "artifact": last["id"]}
                if last else None,
                "owes_me": owes_me, "i_owe": i_owe,
                "decisions": decs_of.get(pid, []),
                "artifacts": [x["id"] for x in arts[:25]], "projects": projects,
                "mentions": len(arts),
            })
        return sorted(out, key=lambda p: ((p["last_interaction"] or {}).get("date") or "", p["mentions"]),
                      reverse=True)

    def _wins(self, deliveries, deliv_done, actions, decisions) -> dict:
        n_weeks = self.cfg["views"]["wins_weeks"]
        weeks: dict[str, dict] = {}
        start = self.today - timedelta(weeks=n_weeks - 1)
        d = start
        while d <= self.today:
            k = util.week_key(d)
            weeks.setdefault(k, {"key": k, "label": util.week_label(k), "deliveries": [], "deliverables": [],
                                 "closed": [], "decisions": []})
            d += timedelta(days=7)
        weeks.setdefault(util.week_key(self.today), {"key": util.week_key(self.today),
                                                      "label": util.week_label(util.week_key(self.today)),
                                                      "deliveries": [], "deliverables": [], "closed": [],
                                                      "decisions": []})

        def put(kind: str, when: str | None, item) -> None:
            if not when:
                return
            k = util.week_key(date.fromisoformat(when))
            if k in weeks:
                weeks[k][kind].append(item)

        for e in deliveries:
            put("deliveries", e["date"], e["id"])
        for x in deliv_done:
            put("deliverables", x["date"], x["id"])
        for a in actions:
            if a["mine"] and a["status"] == "fechada":
                put("closed", a["closed"], a["id"])
        for dd in decisions:
            put("decisions", dd["date"], dd["id"])
        cutoff = (self.today - timedelta(days=30)).isoformat()
        last_30 = sum(1 for e in deliveries if (e["date"] or "") >= cutoff) + \
            sum(1 for x in deliv_done if (x["date"] or "") >= cutoff)
        closed_30 = sum(1 for a in actions if a["mine"] and a["status"] == "fechada" and (a["closed"] or "") >= cutoff)
        return {"weeks": sorted(weeks.values(), key=lambda w: w["key"], reverse=True),
                "last_30d": last_30, "closed_30d": closed_30}

    def _agenda(self, mine_open, projects, horizon: date) -> list[dict]:
        items = []
        for a in mine_open:
            if a["due"] and date.fromisoformat(a["due"]) <= horizon:
                items.append({"date": a["due"], "kind": "ação", "id": a["id"], "title": a["title"],
                              "project": a["project"], "overdue_days": a["overdue_days"],
                              "status": a["status"]})
        for p in projects:
            for d in p["deliverables"]:
                if d["due"] and d["status"] not in ("feito", "cancelado") and \
                        date.fromisoformat(d["due"]) <= horizon:
                    items.append({"date": d["due"], "kind": "entregável", "id": d["id"], "title": d["title"],
                                  "project": p["id"], "overdue_days": d["overdue_days"], "status": d["status"]})
        for f in self.st.focus_plans.values():
            blocks = f.applied if f.status == "aplicado" else (f.blocks if f.status in ("proposto", "aprovado") else [])
            for blk in blocks:
                day = blk["start"][:10]
                if self.today.isoformat() <= day <= horizon.isoformat():
                    items.append({"date": day, "kind": "foco", "id": blk["action"],
                                  "title": f"{blk['start'][11:16]}–{blk['end'][11:16]} · "
                                           f"{self.st.actions[blk['action']].title if blk['action'] in self.st.actions else blk['action']}",
                                  "project": None, "overdue_days": 0,
                                  "status": "aplicado" if f.status == "aplicado" else f.status})
        return sorted(items, key=lambda i: (i["date"], i["kind"] != "foco", i["id"]))

    def _focus(self) -> dict | None:
        if not self.st.focus_plans:
            return None
        live = [f for f in self.st.focus_plans.values() if f.status != "substituido"]
        f = max(live or self.st.focus_plans.values(), key=lambda f: f.id)
        ev = next(e for e in self.st.events if e["type"] == "focus.planned" and e["id"] == f.id)
        data = ev["data"]
        return {"id": f.id, "status": f.status, "mode": f.mode, "quote": f.quote,
                "blocks": f.blocks, "applied": f.applied, "plan_file": f.plan_file,
                "at_risk": data.get("at_risk", []), "missing_effort": data.get("missing_effort", []),
                "consumed": data.get("consumed", []), "horizon": data.get("horizon", {}),
                "busy": data.get("busy", []),
                "created": _iso(f.created)}

    def _timeline(self, projects, deliveries, deliv_done, decisions, actions, artifacts) -> dict:
        back = self.today - timedelta(days=self.cfg["views"]["timeline_back_days"])
        ahead = self.today + timedelta(days=self.cfg["views"]["timeline_ahead_days"])
        past = []
        for e in deliveries:
            past.append({"date": e["date"], "kind": "entrega", "id": e["id"], "title": e["title"],
                         "project": e["project"]})
        for x in deliv_done:
            past.append({"date": x["date"], "kind": "entregável", "id": x["id"], "title": x["title"],
                         "project": x["project"]})
        for d in decisions:
            past.append({"date": d["date"], "kind": "decisão", "id": d["id"], "title": d["title"],
                         "project": d["project"], "who": ", ".join(d["decided_by_names"])})
        for c in self.st.plan_changes:
            past.append({"date": _iso(c["date"]), "kind": "plano", "id": f"plan-{c['seq']}",
                         "title": c["diff"], "project": None})
        for x in artifacts:
            if x["kind"] == "reuniao":
                past.append({"date": x["date"], "kind": "reunião", "id": x["id"], "title": x["title"],
                             "project": (x["projects"] or [None])[0]})
        for a in actions:
            if a["mine"] and a["status"] == "fechada":
                past.append({"date": a["closed"], "kind": "ação fechada", "id": a["id"], "title": a["title"],
                             "project": a["project"]})
        past = [p for p in past if p["date"] and back.isoformat() <= p["date"] <= self.today.isoformat()]
        future = []
        for p in projects:
            for d in p["deliverables"]:
                if d["due"] and d["status"] not in ("feito", "cancelado") and d["due"] <= ahead.isoformat():
                    future.append({"date": d["due"], "kind": "entregável", "id": d["id"], "title": d["title"],
                                   "project": p["id"], "overdue": d["overdue_days"] > 0})
        for a in actions:
            if a["open"] and a["mine"] and a["due"] and a["due"] <= ahead.isoformat():
                future.append({"date": a["due"], "kind": "ação", "id": a["id"], "title": a["title"],
                               "project": a["project"], "overdue": a["overdue_days"] > 0})
        return {"past": sorted(past, key=lambda x: (x["date"], x["id"]), reverse=True),
                "future": sorted(future, key=lambda x: (x["date"], x["id"])),
                "back": back.isoformat(), "ahead": ahead.isoformat()}


def build(brain) -> dict:
    return ModelBuilder(brain).build()
