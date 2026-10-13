"""Tipos de evento do livro-razão e suas regras de validação.

Cada linha do ledger é um evento: {seq, ts, type, id, date, actor, by, source, prov, data}.
`ts` = quando foi registrado; `date` = quando aconteceu no mundo; `actor` = quem fez.
"""
from __future__ import annotations

import re

from .util import BrainError, parse_date

PROV = {"doc", "observado", "declarado", "sem-fonte", "sistema"}
BY = {"owner", "agent", "system"}

ACTION_LISTS = {"mine", "waiting", "watching"}
ACTION_STATUS = {"aberta", "fazendo", "aguardando"}
PRIORITIES = {"alta", "normal", "baixa"}
DELIVERABLE_STATUS = {"nao-iniciado", "em-andamento", "feito", "cancelado"}
ARTIFACT_KINDS = {"reuniao", "documento", "nota", "conector"}
PROPOSAL_KINDS = {"fechar-acao", "atualizar-acao", "mudar-plano", "reestimar", "outro"}

ACTION_ID = re.compile(r"^A-\d{4,}$")
PLAN_NODE = re.compile(r"^(G\d+|P\d+|P\d+\.\d+)$")

# entity: a qual coleção o id pertence · new: o evento cria a entidade ·
# prefix: o CLI atribui o próximo ID sequencial · req: campos obrigatórios em data
TYPES: dict[str, dict] = {
    "person.added": {"entity": "person", "new": True, "req": ["name"]},
    "person.updated": {"entity": "person", "req": []},
    "action.opened": {"entity": "action", "new": True, "prefix": "A", "req": ["title", "owner"]},
    "action.updated": {"entity": "action", "req": []},
    "action.closed": {"entity": "action", "req": ["how"]},
    "action.dropped": {"entity": "action", "req": ["reason"]},
    "action.reopened": {"entity": "action", "req": ["reason"]},
    "decision.made": {"entity": "decision", "new": True, "prefix": "D", "req": ["title", "decided_by"]},
    "decision.superseded": {"entity": "decision", "req": ["reason"]},
    "delivery.recorded": {"entity": "delivery", "new": True, "prefix": "E", "req": ["title"]},
    "deliverable.updated": {"entity": "deliverable", "req": ["status"]},
    "artifact.added": {"entity": "artifact", "new": True, "req": ["kind", "title"]},
    "proposal.opened": {"entity": "proposal", "new": True, "prefix": "R", "req": ["kind", "summary"]},
    "proposal.accepted": {"entity": "proposal", "req": ["quote"]},
    "proposal.rejected": {"entity": "proposal", "req": ["quote"]},
    "progress.declared": {"entity": "plannode", "req": ["pct"]},
    "plan.changed": {"entity": None, "req": ["diff", "reason", "approval"]},
    "message.drafted": {"entity": "message", "new": True, "prefix": "M", "req": ["to", "text"]},
    "message.approved": {"entity": "message", "req": ["quote", "text_sha"]},
    "message.sent": {"entity": "message", "req": ["text_sha"]},
    "message.failed": {"entity": "message", "req": ["error"]},
    "message.cancelled": {"entity": "message", "req": []},
    "share.requested": {"entity": "share", "new": True, "prefix": "S",
                        "req": ["report", "destination", "content_sha"]},
    "share.approved": {"entity": "share", "req": ["quote", "content_sha"]},
    "share.published": {"entity": "share", "req": []},
    "share.cancelled": {"entity": "share", "req": []},
    "focus.planned": {"entity": "focus", "new": True, "prefix": "F", "req": ["plan_file", "sha", "blocks"]},
    "focus.approved": {"entity": "focus", "req": ["quote", "sha"]},
    "focus.applied": {"entity": "focus", "req": ["mode", "created"]},
    "focus.removed": {"entity": "focus", "req": ["removed"]},
    "connector.pulled": {"entity": "connector", "req": ["changed"]},
    "connector.failed": {"entity": "connector", "req": ["error"]},
    "run.completed": {"entity": "run", "req": ["ok"]},
}


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise BrainError(msg, code=4)


def _person(state, pid: str, field: str) -> None:
    _need(pid in state.people, f"{field}: pessoa '{pid}' não registrada — resolva com "
          f"`brain person resolve` ou registre com `brain person add` antes")


def _plan_node(plan, node: str, field: str) -> None:
    _need(plan.has(node), f"{field}: '{node}' não existe no PLANNING/goals.md "
          f"(criar goal/projeto/entregável passa pelo gate)")


def _action_or_node(state, plan, ref: str, field: str) -> None:
    if ACTION_ID.match(ref):
        _need(ref in state.actions, f"{field}: ação {ref} não existe")
    else:
        _plan_node(plan, ref, field)


def validate(ev: dict, state, plan) -> None:
    """Valida um evento já com id atribuído contra o estado atual. Levanta BrainError(code=4)."""
    t = ev.get("type")
    spec = TYPES.get(t)
    _need(spec is not None, f"tipo de evento desconhecido: {t!r}")
    data = ev.setdefault("data", {})
    for f in spec["req"]:
        _need(f in data and data[f] not in (None, ""), f"{t}: campo obrigatório ausente: data.{f}")
    _need(ev.get("by") in BY, f"{t}: by inválido ({ev.get('by')!r}) — use owner|agent|system")
    _need(ev.get("prov") in PROV, f"{t}: prov inválida ({ev.get('prov')!r}) — use {sorted(PROV)}")
    parse_date(ev.get("date"))
    if ev.get("actor"):
        _person(state, ev["actor"], "actor")

    ent = spec["entity"]
    eid = ev.get("id")
    if not spec.get("new") and ent in {"person", "action", "decision", "proposal", "message",
                                       "share", "focus"}:
        _need(eid in state.collection(ent), f"{t}: {ent} {eid!r} não existe")

    if t == "person.added":
        _need(eid not in state.people, f"pessoa '{eid}' já existe — use person.updated (alias)")
    elif t == "action.opened":
        _person(state, data["owner"], "owner")
        _need(data.get("list", "mine") in ACTION_LISTS, f"list inválida: {data.get('list')!r}")
    if t.startswith("action.") and t != "action.closed":
        if data.get("owner"):
            _person(state, data["owner"], "owner")
        if data.get("list"):
            _need(data["list"] in ACTION_LISTS, f"list inválida: {data['list']!r}")
        if data.get("status"):
            _need(data["status"] in ACTION_STATUS,
                  f"status inválido: {data['status']!r} — fechar/descartar têm comandos próprios")
        if data.get("priority"):
            _need(data["priority"] in PRIORITIES, f"priority inválida: {data['priority']!r}")
        if data.get("due"):
            parse_date(data["due"])
        if data.get("project"):
            _plan_node(plan, data["project"], "project")
        if data.get("deliverable"):
            _plan_node(plan, data["deliverable"], "deliverable")
        for ref in data.get("blocked_by", []) + data.get("unblocks", []):
            _action_or_node(state, plan, ref, "blocked_by/unblocks")
        for p in data.get("people", []) + data.get("people_add", []):
            _person(state, p, "people")
        if data.get("effort_min") is not None:
            _need(isinstance(data["effort_min"], int) and data["effort_min"] > 0,
                  "effort_min deve ser inteiro positivo (minutos)")
    if t == "action.closed":
        _need(state.actions[eid].open, f"{eid} já está fechada/descartada — use action.reopened")
    if t == "action.reopened":
        _need(not state.actions[eid].open, f"{eid} já está aberta")
    if t == "decision.made":
        _need(isinstance(data["decided_by"], list) and data["decided_by"],
              "decided_by deve ser lista não vazia de pessoas")
        for p in data["decided_by"]:
            _person(state, p, "decided_by")
        if data.get("project"):
            _plan_node(plan, data["project"], "project")
        if data.get("supersedes"):
            _need(data["supersedes"] in state.decisions, f"supersedes: {data['supersedes']} não existe")
    if t == "decision.superseded" and data.get("by"):
        _need(data["by"] in state.decisions, f"by: {data['by']} não existe")
    if t == "delivery.recorded" and data.get("ref"):
        _action_or_node(state, plan, data["ref"], "ref")
    if t == "deliverable.updated":
        _plan_node(plan, eid or "", "deliverable")
        _need(data["status"] in DELIVERABLE_STATUS, f"status de entregável inválido: {data['status']!r}")
    if t == "artifact.added":
        _need(data["kind"] in ARTIFACT_KINDS, f"kind inválido: {data['kind']!r} — {sorted(ARTIFACT_KINDS)}")
        _need(eid not in state.artifacts, f"artefato já registrado: {eid} (idempotência — pulado)")
        raw = data.get("raw")
        _need(not raw or raw not in state.raw_index,
              f"fonte já processada: {raw} → {state.raw_index.get(raw)} (idempotência — pulado)")
        for p in data.get("people", []):
            _person(state, p, "people")
        for p in data.get("projects", []):
            _plan_node(plan, p, "projects")
    if t == "proposal.opened":
        _need(data["kind"] in PROPOSAL_KINDS, f"kind de proposta inválido: {data['kind']!r}")
    if t in {"proposal.accepted", "proposal.rejected"}:
        _need(state.proposals[eid].status == "aberta", f"proposta {eid} não está aberta")
    if t == "progress.declared":
        _plan_node(plan, eid or "", "progress")
        _need(isinstance(data["pct"], int) and 0 <= data["pct"] <= 100, "pct deve ser inteiro 0–100")
