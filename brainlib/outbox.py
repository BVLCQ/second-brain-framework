"""Porta das mensagens — o cérebro escreve, o dono aprova o texto EXATO, só então sai.

Fluxo (cada passo é um evento no ledger):
  draft    → MSG-#### rascunho (destinatário precisa estar em [outbound].allow)
  approve  → resposta literal do dono + hash do texto travado
  (o agente envia pelo MCP do Slack exatamente `brain outbox show MSG-####`)
  sent     → só se aprovado e com o mesmo hash; registra link
Mudou o texto? Cancela e faz rascunho novo — aprovação nunca é herdada.
"""
from __future__ import annotations

import json

from . import util


def _allowed(brain, to: str) -> bool:
    allow = brain.inst.cfg["outbound"]["allow"]
    return to in allow


def _require_allowed(brain, m) -> None:
    # O rascunho pode ter entrado pelo `brain add` (sem passar pelo draft) ou o dono pode ter tirado o
    # destinatário da lista depois: a porta confere de novo na aprovação e no envio.
    if not _allowed(brain, m.to):
        raise util.BrainError(f"{m.id}: '{m.to}' não está em [outbound].allow do config/brain.toml — a porta das "
                              "mensagens só abre para destinatários que o dono listou", code=4)


def _sent_today(brain) -> int:
    today = util.today().isoformat()
    return sum(1 for m in brain.state.messages.values() if m.status == "enviada" and m.sent and m.sent.isoformat() == today)


def draft(brain, to: str, text: str, ref: str | None, why: str | None, channel: str = "slack") -> dict:
    st = brain.state
    if not to.startswith("#"):
        from .cli import _resolve_people
        to = _resolve_people(brain, [to])[0]
    if not _allowed(brain, to):
        raise util.BrainError(f"'{to}' não está em [outbound].allow do config/brain.toml — a porta das mensagens "
                              "só abre para destinatários que o dono listou", code=4)
    if ref and ref not in st.actions and ref not in st.decisions:
        raise util.BrainError(f"ref {ref} não existe", code=4)
    return brain.record_one({"type": "message.drafted", "by": "agent", "prov": "sistema", "source": "chat",
                             "data": {"to": to, "text": text, "channel": channel, "ref": ref, "why": why}})


def approve(brain, mid: str, quote: str) -> dict:
    m = brain.state.messages.get(mid)
    if m is None:
        raise util.BrainError(f"{mid} não existe", code=3)
    if m.status != "rascunho":
        raise util.BrainError(f"{mid} está '{m.status}' — só rascunho pode ser aprovado", code=4)
    _require_allowed(brain, m)
    return brain.record_one({"type": "message.approved", "id": mid, "by": "owner",
                             "data": {"quote": quote, "text_sha": m.text_sha}})


def sent(brain, mid: str, link: str | None) -> dict:
    m = brain.state.messages.get(mid)
    if m is None:
        raise util.BrainError(f"{mid} não existe", code=3)
    if m.status != "aprovada":
        raise util.BrainError(f"{mid} está '{m.status}' — envio só depois de aprovação explícita do dono", code=4)
    if any(e["type"] in ("message.cancelled", "message.failed", "message.sent") for e in m.history):
        # aprovação gravada depois de cancelada/falha/envio (só possível por fora do `outbox approve`) não reabre a porta
        raise util.BrainError(f"{mid}: mensagem já cancelada/falhou/enviada — faça novo rascunho", code=4)
    approved = next(e for e in reversed(m.history) if e["type"] == "message.approved")
    if approved["data"]["text_sha"] != util.sha(m.text):
        raise util.BrainError(f"{mid}: texto difere do aprovado — cancele e faça novo rascunho", code=4)
    _require_allowed(brain, m)
    cap = brain.inst.cfg["outbound"]["daily_max"]
    if _sent_today(brain) >= cap:
        raise util.BrainError(f"teto diário de {cap} mensagens atingido ([outbound].daily_max)", code=4)
    return brain.record_one({"type": "message.sent", "id": mid, "by": "system",
                             "data": {"text_sha": m.text_sha, "link": link}})


def cli(args, brain) -> None:
    c, st = args.ocmd, brain.state
    if c == "draft":
        ev = draft(brain, args.to, args.text, args.ref, args.why, args.channel)
        print(f"✓ rascunho {ev['id']} para {st.person_name(ev['data']['to']) if not ev['data']['to'].startswith('#') else ev['data']['to']}"
              f" — mostre o texto ao dono e peça aprovação explícita")
    elif c == "show":
        m = st.messages.get(args.id)
        if m is None:
            raise util.BrainError(f"{args.id} não existe", code=3)
        person = st.people.get(m.to)
        payload = {"id": m.id, "status": m.status, "to": m.to, "to_name": person.name if person else m.to,
                   "to_email": person.email if person else "", "channel": m.channel, "text": m.text,
                   "text_sha": m.text_sha}
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"{m.id} · {m.status} · para {payload['to_name']}"
                  + (f" <{payload['to_email']}>" if payload["to_email"] else "") + f" · via {m.channel}\n")
            print(m.text)
    elif c == "approve":
        approve(brain, args.id, args.quote)
        print(f"✓ {args.id} aprovada (\"{args.quote}\") — envie exatamente o texto de `brain outbox show {args.id}`"
              f" e depois `brain outbox sent {args.id} --link <permalink>`")
    elif c == "sent":
        sent(brain, args.id, args.link)
        print(f"✓ {args.id} registrada como enviada")
    elif c == "failed":
        brain.record_one({"type": "message.failed", "id": args.id, "by": "system", "data": {"error": args.error}})
        print(f"✓ falha registrada em {args.id}")
    elif c == "cancel":
        brain.record_one({"type": "message.cancelled", "id": args.id, "by": "owner", "data": {"reason": args.reason}})
        print(f"✓ {args.id} cancelada")
    elif c == "list":
        rows = [m for m in st.messages.values() if args.all or m.status in ("rascunho", "aprovada")]
        if getattr(args, "json", False):
            print(json.dumps([{"id": m.id, "to": m.to, "status": m.status, "text": m.text} for m in rows],
                             ensure_ascii=False, indent=2))
        else:
            print("\n".join(f"{m.id} · {m.status} · {st.person_name(m.to) if not m.to.startswith('#') else m.to}"
                            f" · {m.text[:70]}" for m in rows) or "(nenhuma pendente)")
