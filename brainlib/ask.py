"""`brain ask` — perguntas do agente ao dono (`ASK-####`): perguntar, responder, aplicar, descartar.

O agente que precisa do dono (identidade ambígua, pessoa sem ficha, classificação duvidosa, permissão negada) não deixa a
dúvida no log: grava uma pergunta. O dono responde pela TUI (ou `brain ask answer`); o agente aplica a resposta no passo 0
do próximo `/dump` ou `/update` e registra `applied`. Estados: aberta → respondida → aplicada, ou descartada.
Só o agente pergunta; só o dono responde (e nunca no noturno).
"""
from __future__ import annotations


from . import ids, schema, util
from .cli import _common, _fact_opts, _out
from .core import Brain


def find_open(brain: Brain, text: str, context: list[str]):
    key = schema.question_key(text, context)
    return next((q for q in brain.state.questions.values() if q.status == "aberta" and q.key == key), None)


def add(brain: Brain, text: str, options: list[str] | None = None, context: list[str] | None = None, kind: str = "outro",
        run: str = "", by: str = "agent", prov: str = "observado", source: str = "", date: str | None = None) -> tuple[dict | None, str, bool]:
    """Grava a pergunta, ou devolve a que já está aberta com o mesmo texto e contexto. → (evento, id, criada?)"""
    context = [ids.normalize(c) for c in (context or [])]
    dup = find_open(brain, text, context)
    if dup is not None:
        return None, dup.id, False
    ev = brain.record_one({"type": "question.asked", "by": by, "prov": prov, "source": source or "chat", "date": date,
                           "data": {"text": text, "options": options or [], "context": context, "kind": kind, "run": run}})
    return ev, ev["id"], True


def line(q) -> str:
    bits = [q.id, q.status, f"[{q.kind}]", q.text]
    if q.options:
        bits.append("opções: " + " | ".join(q.options))
    if q.answer:
        bits.append(f"resposta: {q.answer}" + (" (livre)" if q.free else ""))
    if q.context:
        bits.append("contexto: " + ", ".join(q.context))
    return " · ".join(bits)


def _need(b: Brain, qid: str):
    q = b.state.questions.get(qid)
    if q is None:
        raise util.BrainError(f"{qid} não existe", code=3)
    return q


def cmd_ask(args, b: Brain) -> None:
    c = args.askcmd
    if c == "add":
        ctx = [x for part in (args.context or []) for x in util.split_csv(part)]
        ev, qid, created = add(b, args.text, args.option or [], ctx, args.kind, args.run or "", args.by,
                               args.prov or "observado", args.source or "", args.date)
        q = b.state.questions[qid]
        _out(args, {"id": qid, "created": created}, (f"✓ {line(q)}" if created else f"= já aberta: {line(q)}"))
    elif c == "answer":
        q = _need(b, args.id)
        ev = b.record_one(_common({"type": "question.answered", "id": args.id, "data": {
            "answer": args.answer, "free": bool(q.options and args.answer not in q.options) or None}}, args))
        _out(args, ev, "✓ " + line(b.state.questions[args.id]))
    elif c == "applied":
        _need(b, args.id)
        ev = b.record_one(_common({"type": "question.applied", "id": args.id, "data": {"how": args.how}}, args))
        _out(args, ev, "✓ " + line(b.state.questions[args.id]))
    elif c == "drop":
        _need(b, args.id)
        ev = b.record_one(_common({"type": "question.dropped", "id": args.id, "data": {"reason": args.reason}}, args))
        _out(args, ev, "✓ " + line(b.state.questions[args.id]))
    else:
        want = {"open": {"aberta"}, "answered": {"respondida"}}.get("open" if args.open else "answered" if args.answered else "")
        rows = [q for q in b.state.questions.values() if (want is None and (args.all or q.status in {"aberta", "respondida"})) or
                (want is not None and q.status in want)]
        _out(args, [dict(q.__dict__) for q in rows], "\n".join(line(q) for q in rows) or "(nenhuma)")


def add_parsers(sub) -> None:
    from .schema import QUESTION_KINDS
    p = sub.add_parser("ask", help="perguntas do agente ao dono ASK-#### (perguntar, responder, aplicar, descartar)")
    s = p.add_subparsers(dest="askcmd", required=True)
    x = s.add_parser("add", help="o agente registra uma dúvida em vez de deixá-la no log (texto igual ao de uma aberta devolve o ID dela)")
    x.add_argument("text")
    x.add_argument("--option", action="append", help="opção de resposta (repetível)")
    x.add_argument("--context", action="append", help="refs: TASK-…, PROJ-…, pessoa, caminho do RAW (vírgula ou repetido)")
    x.add_argument("--kind", choices=sorted(QUESTION_KINDS), default="outro")
    x.add_argument("--run", help="id da rodada do agente")
    _fact_opts(x)
    x = s.add_parser("answer", help="o dono responde (uma das opções, ou texto livre)")
    x.add_argument("id")
    x.add_argument("answer")
    _fact_opts(x)
    x.set_defaults(by="owner")
    x = s.add_parser("applied", help="o agente registra o efeito da resposta")
    x.add_argument("id")
    x.add_argument("--how", required=True)
    _fact_opts(x)
    x = s.add_parser("drop")
    x.add_argument("id")
    x.add_argument("--reason", required=True)
    _fact_opts(x)
    x.set_defaults(by="owner")
    x = s.add_parser("list")
    g = x.add_mutually_exclusive_group()
    g.add_argument("--open", action="store_true", help="só as abertas")
    g.add_argument("--answered", action="store_true", help="respondidas e ainda não aplicadas (a fila de reserva do passo 0)")
    x.add_argument("--all", action="store_true", help="inclui aplicadas e descartadas")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ask)
