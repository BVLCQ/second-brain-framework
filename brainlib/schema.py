"""Tipos de evento do livro-razão e suas regras de validação.

Cada linha do ledger é um evento: {seq, ts, type, id, date, actor, by, source, prov, data}.
`ts` = quando foi registrado; `date` = quando aconteceu no mundo; `actor` = quem fez.
"""
from __future__ import annotations

import re

from . import ids, util
from .util import BrainError, parse_date

PROV = {"doc", "observado", "declarado", "sem-fonte", "sistema"}
BY = {"owner", "agent", "system"}

ACTION_LISTS = {"mine", "waiting", "watching"}
ACTION_STATUS = {"aberta", "fazendo", "aguardando"}
PRIORITIES = {"alta", "normal", "baixa"}
DELIVERABLE_STATUS = {"nao-iniciado", "em-andamento", "feito", "cancelado"}
ARTIFACT_KINDS = {"reuniao", "documento", "nota", "conector"}
QUESTION_KINDS = {"identidade", "classificacao", "permissao", "confirmacao", "outro"}
PROPOSAL_KINDS = {"fechar-acao", "atualizar-acao", "mudar-plano", "reestimar", "outro"}
RECURRENCE = {"diaria", "semanal", "quinzenal", "mensal", "trimestral", "sob-demanda", "por-evento"}
RECURRENCE_NEEDS_COUNT = {"sob-demanda", "por-evento"}     # exigem per_month (execuções/mês)
OPP_STATUS = {"ideia", "triagem", "em-espera", "descartada", "priorizada", "em-andamento", "piloto",
              "validando", "entregue"}
OPP_REASON_STATUS = {"em-espera", "descartada"}            # laterais: exigem motivo
OPP_KINDS = {"melhoria-de-processo", "novo-processo", "estruturante"}
DOC_KINDS = {"playbook", "one-pager", "planilha", "artefato", "apresentacao", "outro"}

ACTION_ID, PLAN_NODE = ids.ACTION_ID, ids.PLAN_NODE
PROC_ID = re.compile(r"^PROC-\d{4,}$")
OPP_ID = re.compile(r"^OPP-\d{4,}$")
AREA_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# entity: a qual coleção o id pertence · new: o evento cria a entidade ·
# prefix: o CLI atribui o próximo ID sequencial · req: campos obrigatórios em data
TYPES: dict[str, dict] = {
    "person.added": {"entity": "person", "new": True, "req": ["name"]},
    "person.updated": {"entity": "person", "req": []},
    "person.merged": {"entity": "person", "req": ["into"]},
    "action.opened": {"entity": "action", "new": True, "prefix": ids.prefix("action"), "req": ["title", "owner"]},
    "action.updated": {"entity": "action", "req": []},
    "action.closed": {"entity": "action", "req": ["how"]},
    "action.dropped": {"entity": "action", "req": ["reason"]},
    "action.reopened": {"entity": "action", "req": ["reason"]},
    "decision.made": {"entity": "decision", "new": True, "prefix": ids.prefix("decision"), "req": ["title", "decided_by"]},
    "decision.superseded": {"entity": "decision", "req": ["reason"]},
    "delivery.recorded": {"entity": "delivery", "new": True, "prefix": ids.prefix("delivery"), "req": ["title"]},
    "deliverable.updated": {"entity": "deliverable", "req": ["status"]},
    "artifact.added": {"entity": "artifact", "new": True, "req": ["kind", "title"]},
    "proposal.opened": {"entity": "proposal", "new": True, "prefix": ids.prefix("proposal"), "req": ["kind", "summary"]},
    "proposal.accepted": {"entity": "proposal", "req": ["quote"]},
    "proposal.rejected": {"entity": "proposal", "req": ["quote"]},
    "proposal.superseded": {"entity": "proposal", "req": ["reason"]},
    "progress.declared": {"entity": "plannode", "req": ["pct"]},
    "plan.changed": {"entity": None, "req": ["diff", "reason", "approval"]},
    "message.drafted": {"entity": "message", "new": True, "prefix": ids.prefix("message"), "req": ["to", "text"]},
    "message.approved": {"entity": "message", "req": ["quote", "text_sha"]},
    "message.sent": {"entity": "message", "req": ["text_sha"]},
    "message.failed": {"entity": "message", "req": ["error"]},
    "message.cancelled": {"entity": "message", "req": []},
    "share.requested": {"entity": "share", "new": True, "prefix": ids.prefix("share"),
                        "req": ["report", "destination", "content_sha"]},
    "share.approved": {"entity": "share", "req": ["quote", "content_sha"]},
    "share.published": {"entity": "share", "req": []},
    "share.cancelled": {"entity": "share", "req": []},
    "focus.planned": {"entity": "focus", "new": True, "prefix": ids.prefix("focus"), "req": ["plan_file", "sha", "blocks"]},
    "focus.approved": {"entity": "focus", "req": ["quote", "sha"]},
    "focus.applied": {"entity": "focus", "req": ["mode", "created"]},
    "focus.removed": {"entity": "focus", "req": ["removed"]},
    "connector.pulled": {"entity": "connector", "req": ["changed"]},
    "connector.failed": {"entity": "connector", "req": ["error"]},
    "run.completed": {"entity": "run", "req": ["ok"]},
    "question.asked": {"entity": "question", "new": True, "prefix": ids.prefix("question"), "req": ["text"]},
    "question.answered": {"entity": "question", "req": ["answer"]},
    "question.applied": {"entity": "question", "req": ["how"]},
    "question.dropped": {"entity": "question", "req": ["reason"]},
    "ids.migrated": {"entity": None, "req": ["map", "backup_sha"]},     # `brain migrate ids`: o mapa antigo → novo
    "area.added": {"entity": "area", "new": True, "req": ["name"]},
    "area.updated": {"entity": "area", "req": []},
    "process.added": {"entity": "process", "new": True, "prefix": ids.prefix("process"), "req": ["title", "area"]},
    "process.updated": {"entity": "process", "req": []},
    "process.retired": {"entity": "process", "req": ["reason"]},
    "opportunity.added": {"entity": "opportunity", "new": True, "prefix": ids.prefix("opportunity"), "req": ["title", "area"]},
    "opportunity.updated": {"entity": "opportunity", "req": []},
    "opportunity.status": {"entity": "opportunity", "req": ["status"]},
    "opportunity.scored": {"entity": "opportunity", "req": ["impact", "confidence", "ease"]},
    "opportunity.evidence": {"entity": "opportunity", "req": ["source"]},
    "opportunity.promoted": {"entity": "opportunity", "req": ["project", "goal"]},
    "doc.linked": {"entity": "doclink", "req": ["target", "kind", "ref"]},
    "doc.unlinked": {"entity": "doclink", "req": ["target", "ref"]},
}


# campos de `data` que, quando presentes, são listas (texto solto quebraria a dobra: `"ana" + []`, `list("ana")`)
LIST_FIELDS = ("blocked_by", "unblocks", "people", "people_add", "decided_by", "projects", "aliases", "aliases_add", "clear",
               "executors", "executors_add", "tools", "tools_add", "pains", "pains_add", "options",
               "blocks", "created", "removed")
# aprovações e gates: a fala é do dono — só by=owner grava (o noturno recusa owner; ver core.NIGHT_FORBIDDEN)
OWNER_ONLY = {"proposal.accepted", "proposal.rejected", "message.approved", "share.approved", "focus.approved",
              "plan.changed", "opportunity.promoted"}

# campos de `data` que guardam IDs (um, ou uma lista); valores que não são ID (URL, texto) passam intactos
REF_FIELDS = ("project", "deliverable", "goal", "ref", "link", "target", "blocked_by", "unblocks", "supersedes", "by",
              "process", "projects", "context")
ID_ENTITIES = {"action", "decision", "delivery", "proposal", "message", "share", "focus", "process", "opportunity",
               "question", "plannode", "deliverable", "doclink"}


def normalize_event(ev: dict) -> dict:
    """Nomes antigos (`A-0146`, `G1`, `P3.2`…) → novos, no `id` e nos campos que referenciam IDs. Edita `ev` no lugar.

    É a ponte de entrada: `brain add`, a CLI e a leitura de um ledger ainda não migrado passam por aqui."""
    spec = TYPES.get(ev.get("type"))
    if spec is not None and spec["entity"] in ID_ENTITIES and ev.get("id"):
        ev["id"] = ids.normalize(ev["id"])
    data = ev.get("data")
    if isinstance(data, dict):
        for f in REF_FIELDS:
            if f in data:
                data[f] = ids.normalize(data[f])
    return ev


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
    _need(isinstance(ev.get("by"), str) and ev["by"] in BY, f"{t}: by inválido ({ev.get('by')!r}) — use owner|agent|system")
    _need(isinstance(ev.get("prov"), str) and ev["prov"] in PROV, f"{t}: prov inválida ({ev.get('prov')!r}) — use {sorted(PROV)}")
    _need(ev.get("id") is None or isinstance(ev["id"], str), f"{t}: id deve ser texto ({ev.get('id')!r})")
    parse_date(ev.get("date"))
    for f in LIST_FIELDS:
        _need(f not in data or isinstance(data[f], list), f"{t}: data.{f} deve ser lista")
    if t in OWNER_ONLY:
        _need(ev.get("by") == "owner", f"{t}: aprovação/gate é do dono (by=owner), com a fala literal dele")
    if ev.get("actor"):
        _person(state, ev["actor"], "actor")

    ent = spec["entity"]
    eid = ev.get("id")
    if not spec.get("new") and ent in {"person", "action", "decision", "proposal", "message",
                                       "share", "focus", "area", "process", "opportunity", "question"}:
        _need(eid in state.collection(ent), f"{t}: {ent} {eid!r} não existe")

    if t == "person.added":
        _need(eid not in state.people, f"pessoa '{eid}' já existe — use person.updated (alias)")
    elif t == "person.merged":
        _person(state, data["into"], "into")
        _need(data["into"] != eid, f"pessoa '{eid}' não pode ser fundida nela mesma")
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
        if data.get("due_suggested"):
            _need(data.get("due"), f"{t}: due_suggested exige data.due")
            _need(ev.get("by") == "agent", f"{t}: só o agente sugere prazo (by=agent); "
                  "prazo do dono é declaração, sem due_suggested")
        if data.get("due_confirmed"):
            _need(t == "action.updated" and ev.get("by") == "owner" and state.actions[eid].due_suggested,
                  f"{t}: due_confirmed é só do dono (by=owner) e só vale com prazo sugerido pendente")
        if data.get("project"):
            _plan_node(plan, data["project"], "project")
        if data.get("deliverable"):
            _plan_node(plan, data["deliverable"], "deliverable")
        for ref in data.get("blocked_by", []) + data.get("unblocks", []):
            _action_or_node(state, plan, ref, "blocked_by/unblocks")
        for p in data.get("people", []) + data.get("people_add", []):
            _person(state, p, "people")
        if data.get("effort_min") is not None:
            _need(isinstance(data["effort_min"], int) and not isinstance(data["effort_min"], bool) and data["effort_min"] > 0,
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
        if data.get("link"):
            _need(data["link"] in state.processes or data["link"] in state.opportunities,
                  f"link: {data['link']!r} não existe (PROC-… ou OPP-…)")
    if t == "proposal.opened":
        _need(data["kind"] in PROPOSAL_KINDS, f"kind de proposta inválido: {data['kind']!r}")
    if t in {"proposal.accepted", "proposal.rejected", "proposal.superseded"}:
        _need(state.proposals[eid].status == "aberta", f"proposta {eid} não está aberta")
    if t == "ids.migrated":
        _need(ev.get("by") == "system" and isinstance(data["map"], dict), "ids.migrated: só o sistema grava, com o mapa")
    if t == "progress.declared":
        _plan_node(plan, eid or "", "progress")
        _need(isinstance(data["pct"], int) and not isinstance(data["pct"], bool) and 0 <= data["pct"] <= 100,
              "pct deve ser inteiro 0–100")
    if ent == "question":
        _validate_question(t, ev, data, state)
    if ent in {"area", "process", "opportunity", "doclink"}:
        _validate_portfolio(t, ev, data, state, plan)


def question_key(text: str, context) -> tuple:
    """Chave de dedupe de uma pergunta: texto normalizado + contexto (sem ordem)."""
    return (" ".join(util.fold(text).split()), tuple(sorted(str(c) for c in (context or []))))


def _validate_question(t: str, ev: dict, data: dict, state) -> None:
    by, eid = ev.get("by"), ev.get("id")
    if t == "question.asked":
        _need(by in {"agent", "system"}, "question.asked: só o agente pergunta (by=agent)")
        _need(by != "agent" or ev.get("source"), "question.asked por agente exige --source")
        if data.get("kind"):
            _need(data["kind"] in QUESTION_KINDS, f"kind de pergunta inválido: {data['kind']!r} — {sorted(QUESTION_KINDS)}")
        opts = data.get("options", [])
        _need(isinstance(opts, list) and all(isinstance(o, str) and o.strip() for o in opts), "options deve ser lista de textos")
        _need(isinstance(data.get("context", []), list), "context deve ser lista de referências")
        key = question_key(data["text"], data.get("context"))
        dup = next((q.id for q in state.questions.values() if q.status == "aberta" and q.key == key), None)
        _need(dup is None, f"pergunta igual já aberta: {dup}")
        return
    q = state.questions[eid]
    if t == "question.answered":
        _need(by == "owner", "question.answered: só o dono responde (by=owner)")
        _need(q.status == "aberta", f"{eid} está '{q.status}' — só pergunta aberta recebe resposta")
        _need(not q.options or data["answer"] in q.options or data.get("free"),
              f"{eid}: a resposta não é uma das opções ({', '.join(q.options)}) — marque free para texto livre")
    elif t == "question.applied":
        _need(by in {"agent", "system"}, "question.applied: quem registra o efeito é o agente")
        _need(q.status == "respondida", f"{eid} está '{q.status}' — só pergunta respondida pode ser aplicada")
    elif t == "question.dropped":
        _need(q.status in {"aberta", "respondida"}, f"{eid} já está '{q.status}'")


def _int15(data: dict, field: str) -> None:
    if field in data:
        v = data[field]
        _need(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5,
              f"{field} deve ser inteiro 1–5 (recebido {v!r})")


def _people_fields(data: dict, state) -> None:
    for f in ("owner",):
        if data.get(f):
            _person(state, data[f], f)
    for f in ("executors", "executors_add", "people", "people_add"):
        for p in data.get(f, []):
            _person(state, p, f)


def _validate_portfolio(t: str, ev: dict, data: dict, state, plan) -> None:
    eid = ev.get("id")
    by = ev.get("by")
    if t == "area.added":
        _need(bool(AREA_ID.match(eid or "")), f"area: id inválido {eid!r} (slug minúsculo-com-hífens)")
        _need(eid not in state.areas, f"área '{eid}' já existe — use area.updated")
    if t.startswith("process.") or t.startswith("opportunity."):
        _people_fields(data, state)
        if data.get("area"):
            _need(data["area"] in state.areas, f"area: '{data['area']}' não cadastrada — `brain area add`")
    if t.startswith("process."):
        if "recurrence" in data:
            _need(data["recurrence"] in RECURRENCE, f"recurrence inválida: {data['recurrence']!r} — {sorted(RECURRENCE)}")
        if "per_month" in data:
            v = data["per_month"]
            _need(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0,
                  "per_month deve ser número > 0")
        if "duration" in data:                       # aceita '1h30m'/'45m'/minutos; guarda em minutos
            mins = util.parse_duration(data.pop("duration"))
            _need(bool(mins) and mins > 0, "duration deve ser > 0")
            data["duration_min"] = mins
        if "duration_min" in data:
            v = data["duration_min"]
            _need(isinstance(v, int) and not isinstance(v, bool) and v > 0, "duration_min deve ser inteiro positivo (minutos)")
        if t in {"process.added", "process.updated"} and data.get("recurrence") in RECURRENCE_NEEDS_COUNT:
            _need(data.get("per_month") or (eid in state.processes and state.processes[eid].per_month),
                  f"recurrence '{data['recurrence']}' exige per_month (execuções por mês)")
        _int15(data, "maturity")
        if t == "process.added":
            _need(by != "agent" or ev.get("source"), "process.added por agente exige --source")
        if t in {"process.updated", "process.retired"}:
            _need(state.processes[eid].status == "ativo", f"processo {eid} já foi aposentado")
    if t.startswith("opportunity."):
        if data.get("process"):
            _need(data["process"] in state.processes, f"process: {data['process']} não existe")
        if data.get("kind"):
            _need(data["kind"] in OPP_KINDS, f"kind inválido: {data['kind']!r} — {sorted(OPP_KINDS)}")
        if "hours_saved" in data:
            v = data["hours_saved"]
            _need(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0, "hours_saved deve ser número ≥ 0")
        if data.get("goal"):
            _need(data["goal"] in plan.goals, f"goal: '{data['goal']}' não existe no PLANNING/goals.md")
        if data.get("project"):
            _need(data["project"] in plan.projects, f"project: '{data['project']}' não existe no PLANNING/goals.md")
        for f in ("impact", "confidence", "ease"):
            _int15(data, f)
        if data.get("ice_suggested"):
            _need(by == "agent", f"{t}: só o agente sugere ICE (by=agent); ICE do dono é declaração, sem ice_suggested")
        if t in {"opportunity.added", "opportunity.updated"}:
            # projeto só nasce da promoção (gate); goal aqui é só o alvo pretendido
            _need("project" not in data, f"{t}: project só via `brain opportunity promote` (gate do dono)")
        if t == "opportunity.added":
            _need(by != "agent" or ev.get("source"), "opportunity.added por agente exige --source")
            _need(by == "owner" or data.get("status", "ideia") == "ideia",
                  "agente só cria oportunidade em status 'ideia'")
            ice = [f for f in ("impact", "confidence", "ease") if f in data]
            _need(not ice or len(ice) == 3, "ICE no cadastro exige impact, confidence e ease juntos")
            _need(not ice or by == "owner" or data.get("ice_suggested"),
                  "agente só grava ICE como sugestão (ice_suggested)")
            if data.get("status"):
                _need(data["status"] in OPP_STATUS, f"status inválido: {data['status']!r}")
        if t == "opportunity.status":
            st = data["status"]
            _need(st in OPP_STATUS, f"status inválido: {st!r} — {sorted(OPP_STATUS)}")
            _need(by == "owner" or st == "ideia",
                  "agente só pode gravar status 'ideia' — mover oportunidade é do dono")
            if st in OPP_REASON_STATUS:
                _need(data.get("reason"), f"status '{st}' exige reason (motivo)")
            if st == "em-andamento":
                _need(state.opportunities[eid].project,
                      f"{eid}: 'em-andamento' só com projeto vinculado — use `brain opportunity promote`")
        if t == "opportunity.scored" and by != "owner":
            _need(data.get("ice_suggested"), "agente só grava ICE como sugestão (ice_suggested)")
        if t == "opportunity.promoted":
            _need(by == "owner", "promover oportunidade é do dono (gate)")
            proj = plan.projects.get(data["project"])
            _need(data["goal"] in plan.goals and proj is not None,
                  "promoted: goal/projeto não existem no PLANNING/goals.md")
            _need( proj.goal_id == data["goal"],
                  f"promoted: projeto {data['project']} não pertence a {data['goal']}")
            _need(not state.opportunities[eid].project, f"{eid} já foi promovida")
    if t.startswith("doc."):
        tgt = data["target"]
        _need(tgt in state.processes or tgt in state.opportunities, f"doc: alvo {tgt!r} não existe (PROC-… ou OPP-…)")
        _need(ev.get("id") == tgt, "doc: id do evento deve ser o alvo")
        if t == "doc.linked":
            _need(data["kind"] in DOC_KINDS, f"kind de documento inválido: {data['kind']!r} — {sorted(DOC_KINDS)}")
        else:
            coll = state.processes if tgt in state.processes else state.opportunities
            _need(any(d.ref == data["ref"] for d in coll[tgt].docs), f"doc: {data['ref']!r} não está ligado a {tgt}")
