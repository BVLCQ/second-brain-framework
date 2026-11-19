"""Fila de revisão unificada (fold derivado sobre `brain.state`) e aceite em lote com bloqueio de portas."""
from __future__ import annotations

from pathlib import Path

from . import dupes, feedback, ids, util

KINDS = ("proposal", "outbox", "publish", "ask", "focus", "dupe")
PORT_KINDS = frozenset({"outbox", "publish", "focus"})
BATCH_ACCEPTABLE_KINDS = frozenset({"proposal"})

_PORT_ENTITIES = frozenset({"message", "share", "focus"})
_ACTION_TARGET_KINDS = frozenset({"fechar-acao", "descartar-acao", "unificar-acao", "atualizar-acao", "reestimar"})


def _proposal_diff(st, p) -> str:
    """Resumo legível do efeito esperado se a proposta for aceita."""
    tgt = st.actions.get(p.target) if p.target else None
    tgt_lbl = f"{p.target} ({tgt.title})" if tgt else p.target
    into_lbl = p.into or ""
    if p.kind == "fechar-acao" and p.target:
        return f"Fechar {tgt_lbl}"
    if p.kind == "descartar-acao" and p.target:
        return f"Descartar {tgt_lbl}" + (f" como duplicada de {into_lbl}" if into_lbl else "")
    if p.kind == "unificar-acao" and p.target and p.into:
        return f"Unificar {tgt_lbl} em {into_lbl}"
    if p.kind in ("atualizar-acao", "reestimar") and p.target:
        return f"Atualizar {tgt_lbl}: {p.summary}"
    if p.kind == "mudar-plano":
        return f"Mudar plano: {p.summary}"
    if p.kind == "framework":
        return f"Abrir issue pública: {p.issue_title or p.summary}"
    return p.summary


def _opened_meta(st) -> dict[str, dict]:
    """Mapeia `id -> evento` de criação para ler `prov` e `source` originais das propostas."""
    return {ev["id"]: ev for ev in st.events if ev.get("type") == "proposal.opened" and ev.get("id")}


def queue(brain, *, kind: str | None = None) -> dict:
    """Fold derivado da fila de revisão sobre `brain.state` (sem entidade ou evento próprio)."""
    if kind is not None and kind not in KINDS:
        raise util.BrainError(f"tipo de revisão inválido: {kind!r} (use {', '.join(KINDS)})", code=4)

    st = brain.state
    meta = _opened_meta(st)
    items: list[dict] = []

    for p in sorted(st.proposals.values(), key=lambda x: x.id):
        if p.status != "aberta":
            continue
        ev = meta.get(p.id, {})
        items.append({
            "id": p.id,
            "kind": "proposal",
            "subkind": p.kind,
            "summary": p.summary,
            "target": p.target,
            "into": p.into,
            "evidence": p.evidence,
            "prov": ev.get("prov", ""),
            "source": ev.get("source", ""),
            "date": p.date.isoformat() if p.date else None,
            "diff": _proposal_diff(st, p),
            "is_port": False,
            "batch_acceptable": True,
        })

    for m in sorted(st.messages.values(), key=lambda x: x.id):
        if m.status != "rascunho":
            continue
        to_name = m.to if m.to.startswith("#") else st.person_name(m.to)
        preview = m.text[:140] + ("…" if len(m.text) > 140 else "")
        items.append({
            "id": m.id,
            "kind": "outbox",
            "summary": f"Enviar para {to_name}: {preview}",
            "to": m.to,
            "to_name": to_name,
            "body_preview": preview,
            "channel": m.channel,
            "ref": m.ref,
            "why": m.why,
            "date": m.drafted.isoformat() if m.drafted else None,
            "is_port": True,
            "port": "outbox",
            "batch_acceptable": False,
        })

    for s in sorted(st.shares.values(), key=lambda x: x.id):
        if s.status != "solicitada":
            continue
        name = Path(s.report).name or s.report
        items.append({
            "id": s.id,
            "kind": "publish",
            "summary": f"Publicar {name} em {s.destination}",
            "report": s.report,
            "dest": s.destination,
            "date": s.date.isoformat() if s.date else None,
            "is_port": True,
            "port": "publish",
            "batch_acceptable": False,
        })

    for q in sorted(st.questions.values(), key=lambda x: x.id):
        if q.status != "aberta":
            continue
        items.append({
            "id": q.id,
            "kind": "ask",
            "subkind": q.kind,
            "summary": q.text,
            "question": q.text,
            "options": list(q.options),
            "context": list(q.context),
            "date": q.asked.isoformat() if q.asked else None,
            "is_port": False,
            "batch_acceptable": False,
        })

    for f in sorted(st.focus_plans.values(), key=lambda x: x.id):
        if f.status != "proposto":
            continue
        items.append({
            "id": f.id,
            "kind": "focus",
            "summary": f"Plano de foco {f.id} ({len(f.blocks)} bloco(s))",
            "blocks": len(f.blocks),
            "plan_file": f.plan_file,
            "date": f.created.isoformat() if f.created else None,
            "is_port": True,
            "port": "focus",
            "batch_acceptable": False,
        })

    for pair in dupes.pairs(st):
        a_id, b_id = pair["a"], pair["b"]
        items.append({
            "id": f"DUPE:{a_id}:{b_id}",
            "kind": "dupe",
            "summary": f"{a_id} ({pair['a_title']}) ↔ {b_id} ({pair['b_title']}) · {pair['score']:.2f}",
            "pair": [a_id, b_id],
            "score": pair["score"],
            "why": list(pair["why"]),
            "is_port": False,
            "batch_acceptable": False,
        })

    counts = {k: 0 for k in KINDS}
    for it in items:
        counts[it["kind"]] += 1
    total = sum(counts.values())
    batch_acceptable = counts["proposal"]
    ports = sum(counts[k] for k in PORT_KINDS)

    filtered = [it for it in items if it["kind"] == kind] if kind is not None else items
    return {
        "items": filtered,
        "counts": counts,
        "total": total,
        "batch_acceptable": batch_acceptable,
        "ports": ports,
        "kind": kind,
    }


def summary(brain) -> dict:
    """Resumo compacto da fila de revisão para badge/contagem no view-model."""
    q = queue(brain)
    return {
        "total": q["total"],
        "counts": q["counts"],
        "batch_acceptable": q["batch_acceptable"],
        "ports": q["ports"],
    }


def _close_events(st, target_id: str, how: str) -> list[dict]:
    """Eventos de fechamento da ação alvo e avisos nas ações desbloqueadas."""
    a = st.actions.get(target_id)
    if a is None:
        raise util.BrainError(f"{target_id} não existe", code=3)
    if not a.open:
        raise util.BrainError(f"{target_id} já está {a.status}", code=4)
    events = [{"type": "action.closed", "id": target_id, "by": "owner", "data": {"how": how or "concluída"}}]
    for other in st.actions.values():
        if other.open and other.id != target_id and target_id in other.blocked_by:
            others = [x for x in st.blocked(other) if x != target_id]
            note = f"desbloqueada ({target_id} fechada)" if not others else (
                f"{target_id} fechada; ainda bloqueada por {', '.join(others)}")
            events.append({"type": "action.updated", "id": other.id, "by": "system", "data": {"note": note}})
    for ref in a.unblocks:
        if ref in st.actions and st.actions[ref].open and target_id not in st.actions[ref].blocked_by:
            events.append({"type": "action.updated", "id": ref, "by": "system",
                           "data": {"note": f"{target_id} (que a destravava) foi fechada"}})
    return events


def _merge_events(st, dup_id: str, keep_id: str, reason: str) -> list[dict]:
    """Eventos de unificação: transfere metadados para `keep_id` e descarta `dup_id`."""
    dup, keep = st.actions.get(dup_id), st.actions.get(keep_id)
    if dup is None or keep is None or dup.id == keep.id:
        raise util.BrainError("unificar-acao: informe duas ações existentes e diferentes", code=3)
    if not dup.open or not keep.open:
        raise util.BrainError(f"unificar-acao: {dup.id} e {keep.id} precisam estar abertas", code=4)
    data: dict = {"note": f"unificada com {dup.id}: {dup.title}"}
    extra = [p for p in dup.people + ([dup.owner] if dup.owner != keep.owner else []) if p not in keep.people]
    if extra:
        data["people_add"] = extra
    if dup.link and not keep.link:
        data["link"] = dup.link
    if dup.due and not dup.due_suggested and (not keep.due or keep.due_suggested or dup.due < keep.due):
        data["due"] = dup.due.isoformat()
    for f in ("blocked_by", "unblocks"):
        merged = [x for x in getattr(keep, f) + getattr(dup, f) if x not in (keep.id, dup.id)]
        merged = list(dict.fromkeys(merged))
        if merged != getattr(keep, f):
            data[f] = merged
    events = [{"type": "action.updated", "id": keep.id, "by": "owner", "data": data}]
    for other in st.actions.values():
        if other.open and other.id not in (dup.id, keep.id) and dup.id in other.blocked_by:
            events.append({"type": "action.updated", "id": other.id, "by": "system", "data": {
                "blocked_by": list(dict.fromkeys(keep.id if x == dup.id else x for x in other.blocked_by)),
                "note": f"bloqueio passou de {dup.id} para {keep.id} (unificadas)"}})
    events.append({"type": "action.dropped", "id": dup.id, "by": "owner", "data": {
        "reason": reason or f"unificada em {keep.id}", "duplicate_of": keep.id}})
    return events


def _accept_one_proposal(brain, pid: str, quote: str) -> dict:
    """Aceita uma proposta individual no ledger e aplica o efeito determinístico seguro."""
    st = brain.state
    p = st.proposals.get(pid)
    if p is None:
        raise util.BrainError(f"proposta {pid!r} não existe", code=3)
    if p.status != "aberta":
        raise util.BrainError(f"proposta {pid} não está aberta ({p.status})", code=4)

    events: list[dict] = [{"type": "proposal.accepted", "id": pid, "by": "owner", "data": {"quote": quote}}]
    effect = f"proposta {p.kind} aceita"

    if p.kind in _ACTION_TARGET_KINDS and p.target:
        tgt = st.actions.get(p.target)
        if tgt is None:
            raise util.BrainError(f"{p.target} não existe", code=3)
        if not tgt.open:
            raise util.BrainError(f"{p.target} já está {tgt.status}", code=4)

    if p.kind == "fechar-acao" and p.target:
        events.extend(_close_events(st, p.target, p.summary or "concluída"))
        effect = f"{p.target} fechada"
    elif p.kind == "descartar-acao" and p.target:
        drop_data = {"reason": p.summary or (f"duplicada de {p.into}" if p.into else "descartada")}
        if p.into:
            drop_data["duplicate_of"] = p.into
        events.append({"type": "action.dropped", "id": p.target, "by": "owner", "data": drop_data})
        effect = f"{p.target} descartada" + (f" (duplicada de {p.into})" if p.into else "")
    elif p.kind == "unificar-acao" and p.target and p.into:
        events.extend(_merge_events(st, p.target, p.into, p.summary or f"unificada em {p.into}"))
        effect = f"{p.target} unificada em {p.into}"
    elif p.kind == "mudar-plano":
        effect = "proposta aceita (mudança no goals.md permanece no gate manual)"

    recorded = brain.record(events)
    out = {
        "id": pid,
        "ok": True,
        "status": "accepted",
        "kind": p.kind,
        "effect": effect,
        "seq": recorded[0]["seq"],
    }
    if p.target:
        out["target"] = p.target
    if p.kind == "framework":
        fid, warn = feedback.from_proposal(brain, pid)
        if fid:
            f = brain.state.feedbacks[fid]
            out["feedback"] = fid
            out["effect"] = f"issue registrada ({fid}: {f.status})"
        if warn:
            out["warning"] = warn
    return out


def _normalize_review_id(raw_id: str) -> str:
    s = (raw_id or "").strip()
    if s.upper().startswith("DUPE:"):
        parts = s.split(":", 2)
        if len(parts) == 3:
            return f"DUPE:{ids.normalize(parts[1])}:{ids.normalize(parts[2])}"
        return "DUPE:" + s[5:]
    return ids.normalize(s)


def accept_batch(brain, item_ids: list[str], *, quote: str) -> dict:
    """Aceita um lote de propostas (`PROP-*`) gravando eventos individuais e barrando portas/individuais."""
    if not isinstance(quote, str) or not quote.strip():
        raise util.BrainError("review accept: --quote obrigatório (não pode ser vazio)", code=4)

    deduped = list(dict.fromkeys(_normalize_review_id(x) for x in item_ids if isinstance(x, str) and x.strip()))
    accepted: list[dict] = []
    failed: list[dict] = []

    for item_id in deduped:
        if item_id.startswith("DUPE:"):
            failed.append({
                "id": item_id,
                "ok": False,
                "status": "rejected_kind",
                "error": "este item exige decisão individual, não aceite em lote",
            })
            continue
        ent = ids.entity_of(item_id)
        if ent in _PORT_ENTITIES:
            failed.append({
                "id": item_id,
                "ok": False,
                "status": "rejected_port",
                "error": "portas externas não entram em aceite em lote — aprove individualmente",
            })
            continue
        if ent != "proposal":
            failed.append({
                "id": item_id,
                "ok": False,
                "status": "rejected_kind",
                "error": "este item exige decisão individual, não aceite em lote",
            })
            continue
        try:
            accepted.append(_accept_one_proposal(brain, item_id, quote.strip()))
        except util.BrainError as e:
            failed.append({
                "id": item_id,
                "ok": False,
                "status": "error",
                "error": str(e),
            })

    return {
        "accepted": accepted,
        "failed": failed,
        "summary": {
            "requested": len(deduped),
            "accepted": len(accepted),
            "failed": len(failed),
        },
    }
