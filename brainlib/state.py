"""Dobra (fold) do livro-razão: eventos em ordem → estado atual de cada entidade.

Nada aqui escreve. O estado é sempre reconstruível a partir do ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import util

LIST_LABEL = {"mine": "minhas", "waiting": "aguardando", "watching": "observando"}
_new_list = list  # Action tem um campo chamado `list`, que sombreia o builtin no corpo da classe


@dataclass
class Person:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    role: str = ""
    relation: str = ""
    email: str = ""
    added: str = ""

    def names(self) -> list[str]:
        return [self.name, self.id, *self.aliases] + ([self.email] if self.email else [])


@dataclass
class Action:
    id: str
    title: str
    owner: str
    list: str = "mine"
    status: str = "aberta"           # aberta | fazendo | aguardando | fechada | descartada
    due: date | None = None
    due_suggested: bool = False      # prazo sugerido pelo agente; qualquer data do dono (ou confirmação) zera
    due_reason: str = ""             # por que o agente sugeriu essa data
    effort_min: int | None = None
    project: str | None = None
    deliverable: str | None = None
    blocked_by: _new_list[str] = field(default_factory=_new_list)
    unblocks: _new_list[str] = field(default_factory=_new_list)
    people: _new_list[str] = field(default_factory=_new_list)
    priority: str = "normal"
    link: str = ""
    origin: str = ""
    source: str = ""
    prov: str = ""
    opened: date | None = None
    closed: date | None = None
    how: str = ""
    outcome: str = ""
    last_activity: date | None = None
    history: _new_list[dict] = field(default_factory=_new_list)

    @property
    def open(self) -> bool:
        return self.status not in ("fechada", "descartada")


@dataclass
class Decision:
    id: str
    title: str
    decided_by: list[str]
    date: date | None
    project: str | None = None
    context: str = ""
    rationale: str = ""
    supersedes: str | None = None
    superseded_by: str | None = None
    status: str = "ativa"            # ativa | substituida
    source: str = ""
    prov: str = ""
    history: list[dict] = field(default_factory=list)


@dataclass
class Delivery:
    id: str
    title: str
    date: date | None
    ref: str | None = None
    result: str = ""
    evidence: str = ""
    impact: str = ""
    source: str = ""
    prov: str = ""


@dataclass
class Artifact:
    id: str                          # caminho relativo ao vault
    kind: str
    title: str
    date: date | None
    raw: str = ""
    people: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    summary: str = ""
    prov: str = ""


@dataclass
class Proposal:
    id: str
    kind: str
    summary: str
    target: str = ""
    evidence: str = ""
    status: str = "aberta"           # aberta | aceita | rejeitada
    date: date | None = None
    quote: str = ""


@dataclass
class Message:
    id: str
    to: str
    text: str
    channel: str = "slack"
    ref: str = ""
    why: str = ""
    status: str = "rascunho"         # rascunho | aprovada | enviada | falhou | cancelada
    text_sha: str = ""
    quote: str = ""
    link: str = ""
    drafted: date | None = None
    sent: date | None = None
    history: list[dict] = field(default_factory=list)


@dataclass
class Share:
    id: str
    report: str
    destination: str
    content_sha: str
    status: str = "solicitada"       # solicitada | aprovada | publicada | cancelada
    quote: str = ""
    link: str = ""
    date: date | None = None


@dataclass
class FocusPlan:
    id: str
    plan_file: str
    sha: str
    blocks: list[dict]
    status: str = "proposto"         # proposto | aprovado | aplicado | substituido
    quote: str = ""
    mode: str = ""
    applied: list[dict] = field(default_factory=list)   # [{action,start,end,event_id}]
    created: date | None = None


@dataclass
class Connector:
    key: str
    last_ok: str = ""
    last_fail: str = ""
    last_error: str = ""
    last_changed: str = ""
    last_snapshot: str = ""
    consecutive_failures: int = 0
    pulls: int = 0


@dataclass
class State:
    events: list[dict] = field(default_factory=list)
    people: dict[str, Person] = field(default_factory=dict)
    merged_people: dict[str, str] = field(default_factory=dict)   # id aposentado → id que o absorveu
    actions: dict[str, Action] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    deliveries: dict[str, Delivery] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    raw_index: dict[str, str] = field(default_factory=dict)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    messages: dict[str, Message] = field(default_factory=dict)
    shares: dict[str, Share] = field(default_factory=dict)
    focus_plans: dict[str, FocusPlan] = field(default_factory=dict)
    connectors: dict[str, Connector] = field(default_factory=dict)
    runs: dict[str, dict] = field(default_factory=dict)
    deliverable_events: dict[str, list[dict]] = field(default_factory=dict)
    progress: dict[str, list[dict]] = field(default_factory=dict)
    plan_changes: list[dict] = field(default_factory=list)

    def max_seq(self) -> int:
        return self.events[-1]["seq"] if self.events else 0

    def collection(self, entity: str) -> dict:
        return {"person": self.people, "action": self.actions, "decision": self.decisions,
                "delivery": self.deliveries, "artifact": self.artifacts,
                "proposal": self.proposals, "message": self.messages, "share": self.shares,
                "focus": self.focus_plans}[entity]

    def next_id(self, prefix: str) -> str:
        coll = {"A": self.actions, "D": self.decisions, "E": self.deliveries, "R": self.proposals,
                "M": self.messages, "S": self.shares, "F": self.focus_plans}[prefix]
        nums = [int(k.split("-")[1]) for k in coll]
        return f"{prefix}-{(max(nums) + 1 if nums else 1):04d}"

    def person_name(self, pid: str | None) -> str:
        if not pid:
            return "—"
        p = self.people.get(pid)
        return p.name if p else pid

    def blocked(self, a: Action) -> list[str]:
        """Bloqueios ativos: ações referenciadas em blocked_by que ainda estão abertas."""
        out = []
        for ref in a.blocked_by:
            other = self.actions.get(ref)
            if other is not None and other.open:
                out.append(ref)
        return out

    def effective_status(self, a: Action) -> str:
        if a.open and self.blocked(a):
            return "bloqueada"
        return a.status


def _d(value) -> date | None:
    try:
        return util.parse_date(value)
    except util.BrainError:
        return None


def _merge_person(st: State, old_id: str, into: str) -> None:
    """Aposenta `old_id`: nomes, aliases e e-mail viram aliases de `into`; referências são redirecionadas."""
    old, new = st.people.pop(old_id), st.people[into]
    for alias in [old.id, old.name, old.email, *old.aliases]:
        if alias and alias not in new.names():
            new.aliases.append(alias)
    for f in ("role", "relation", "email"):
        if not getattr(new, f) and getattr(old, f):
            setattr(new, f, getattr(old, f))
    st.merged_people[old_id] = into

    def swap(ids: list[str]) -> None:
        for i, v in enumerate(ids):
            if v == old_id:
                ids[i] = into
        ids[:] = list(dict.fromkeys(ids))

    for a in st.actions.values():
        if a.owner == old_id:
            a.owner = into
        swap(a.people)
    for d in st.decisions.values():
        swap(d.decided_by)
    for art in st.artifacts.values():
        swap(art.people)
    for m in st.messages.values():
        if m.to == old_id:
            m.to = into


def apply(st: State, ev: dict) -> None:
    t, eid, data = ev["type"], ev.get("id"), ev.get("data", {})
    when = _d(ev.get("date")) or _d(ev.get("ts"))
    st.events.append(ev)

    if t == "person.added":
        st.people[eid] = Person(eid, data["name"], list(data.get("aliases", [])), data.get("role", ""),
                                data.get("relation", ""), data.get("email", ""), ev.get("date", ""))
    elif t == "person.updated":
        p = st.people[eid]
        for a in data.get("aliases_add", []):
            if a not in p.aliases:
                p.aliases.append(a)
        for f in ("name", "role", "relation", "email"):
            if data.get(f):
                setattr(p, f, data[f])
    elif t == "person.merged":
        _merge_person(st, eid, data["into"])

    elif t.startswith("action."):
        if t == "action.opened":
            st.actions[eid] = Action(
                id=eid, title=data["title"], owner=data["owner"], list=data.get("list", "mine"),
                due=_d(data.get("due")), effort_min=data.get("effort_min"),
                due_suggested=bool(data.get("due_suggested")) and bool(data.get("due")),
                due_reason=data.get("due_reason", "") if data.get("due_suggested") else "",
                project=data.get("project"), deliverable=data.get("deliverable"),
                blocked_by=list(data.get("blocked_by", [])), unblocks=list(data.get("unblocks", [])),
                people=list(data.get("people", [])),
                priority=data.get("priority", "normal"), link=data.get("link", ""),
                origin=data.get("origin", ""), source=ev.get("source", ""), prov=ev.get("prov", ""),
                opened=when)
        a = st.actions[eid]
        if t == "action.updated":
            for f in ("title", "owner", "list", "status", "priority", "link", "project", "deliverable"):
                if data.get(f):
                    setattr(a, f, data[f])
            if "due" in data:
                # data nova sem due_suggested = o dono decidiu (a sugestão deixa de valer)
                a.due = _d(data["due"])
                a.due_suggested = bool(data.get("due_suggested")) and a.due is not None
                a.due_reason = data.get("due_reason", "") if a.due_suggested else ""
            if data.get("due_confirmed"):
                a.due_suggested, a.due_reason = False, ""
            for f in data.get("clear", []):
                if f in ("due", "effort_min", "project", "deliverable"):
                    setattr(a, f, None)
                if f == "due":
                    a.due_suggested, a.due_reason = False, ""
            if data.get("effort_min"):
                a.effort_min = data["effort_min"]
            if "blocked_by" in data:
                a.blocked_by = list(data["blocked_by"])
            if "unblocks" in data:
                a.unblocks = list(data["unblocks"])
            for p in data.get("people_add", []):
                if p not in a.people:
                    a.people.append(p)
        elif t == "action.closed":
            a.status, a.closed, a.how = "fechada", when, data["how"]
            a.outcome = data.get("outcome", "")
        elif t == "action.dropped":
            a.status, a.closed, a.how = "descartada", when, data["reason"]
        elif t == "action.reopened":
            a.status, a.closed, a.how, a.outcome = "aberta", None, "", ""
        a.last_activity = when
        a.history.append(ev)

    elif t == "decision.made":
        st.decisions[eid] = Decision(eid, data["title"], list(data["decided_by"]), when,
                                     data.get("project"), data.get("context", ""),
                                     data.get("rationale", ""), data.get("supersedes"),
                                     source=ev.get("source", ""), prov=ev.get("prov", ""), history=[ev])
        old = data.get("supersedes")
        if old and old in st.decisions:
            st.decisions[old].status, st.decisions[old].superseded_by = "substituida", eid
    elif t == "decision.superseded":
        d = st.decisions[eid]
        d.status = "substituida"
        d.superseded_by = data.get("by") or d.superseded_by
        d.history.append(ev)

    elif t == "delivery.recorded":
        st.deliveries[eid] = Delivery(eid, data["title"], when, data.get("ref"), data.get("result", ""),
                                      data.get("evidence", ""), data.get("impact", ""),
                                      ev.get("source", ""), ev.get("prov", ""))
    elif t == "deliverable.updated":
        st.deliverable_events.setdefault(eid, []).append(ev)

    elif t == "artifact.added":
        st.artifacts[eid] = Artifact(eid, data["kind"], data["title"], when, data.get("raw", ""),
                                     list(data.get("people", [])), list(data.get("projects", [])),
                                     data.get("summary", ""), ev.get("prov", ""))
        if data.get("raw"):
            st.raw_index[data["raw"]] = eid

    elif t == "proposal.opened":
        st.proposals[eid] = Proposal(eid, data["kind"], data["summary"], data.get("target", ""),
                                     data.get("evidence", ""), date=when)
    elif t in ("proposal.accepted", "proposal.rejected"):
        p = st.proposals[eid]
        p.status = "aceita" if t.endswith("accepted") else "rejeitada"
        p.quote = data["quote"]

    elif t == "progress.declared":
        st.progress.setdefault(eid, []).append({"pct": data["pct"], "note": data.get("note", ""),
                                                "date": when})
    elif t == "plan.changed":
        st.plan_changes.append({**data, "date": when, "seq": ev["seq"]})

    elif t.startswith("message."):
        if t == "message.drafted":
            st.messages[eid] = Message(eid, data["to"], data["text"], data.get("channel", "slack"),
                                       data.get("ref", ""), data.get("why", ""),
                                       text_sha=util.sha(data["text"]), drafted=when)
        m = st.messages[eid]
        if t == "message.approved":
            m.status, m.quote = "aprovada", data["quote"]
        elif t == "message.sent":
            m.status, m.link, m.sent = "enviada", data.get("link", ""), when
        elif t == "message.failed":
            m.status = "falhou"
        elif t == "message.cancelled":
            m.status = "cancelada"
        m.history.append(ev)

    elif t.startswith("share."):
        if t == "share.requested":
            st.shares[eid] = Share(eid, data["report"], data["destination"], data["content_sha"], date=when)
        s = st.shares[eid]
        if t == "share.approved":
            s.status, s.quote = "aprovada", data["quote"]
        elif t == "share.published":
            s.status, s.link = "publicada", data.get("link", "")
        elif t == "share.cancelled":
            s.status = "cancelada"

    elif t.startswith("focus."):
        if t == "focus.planned":
            for other in st.focus_plans.values():
                if other.status in ("proposto", "aprovado"):
                    other.status = "substituido"
            st.focus_plans[eid] = FocusPlan(eid, data["plan_file"], data["sha"], data["blocks"],
                                            created=when)
        f = st.focus_plans[eid]
        if t == "focus.approved":
            f.status, f.quote = "aprovado", data["quote"]
        elif t == "focus.applied":
            f.status, f.mode = "aplicado", data["mode"]
            f.applied.extend(data["created"])
        elif t == "focus.removed":
            gone = {r.get("event_id") or r.get("uid") for r in data["removed"]}
            f.applied = [b for b in f.applied if (b.get("event_id") or b.get("uid")) not in gone]

    elif t.startswith("connector."):
        c = st.connectors.setdefault(eid, Connector(eid))
        if t == "connector.pulled":
            c.last_ok, c.consecutive_failures, c.pulls = ev["ts"], 0, c.pulls + 1
            if data.get("changed"):
                c.last_changed, c.last_snapshot = ev["ts"], data.get("snapshot", "")
        else:
            c.last_fail, c.last_error = ev["ts"], data["error"]
            c.consecutive_failures += 1

    elif t == "run.completed":
        st.runs[eid] = {"ts": ev["ts"], "ok": data["ok"], "steps": data.get("steps", {})}


def build(events: list[dict]) -> State:
    st = State()
    for ev in events:
        apply(st, ev)
    return st
