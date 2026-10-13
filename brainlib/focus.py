"""Planejador de foco — tempo protegido para as SUAS ações, antes do prazo.

1. `plan`: lê as ações abertas da lista "minhas" (com prazo e esforço), a agenda
   ocupada (snapshot do calendário) e as regras do brain.toml; encaixa blocos por
   prazo mais próximo primeiro (EDF), respeitando expediente, almoço, férias,
   folga entre reuniões e teto diário. Nada vai para o calendário.
2. `approve`: registra a resposta LITERAL do dono ("ok") — o gate semanal.
3. `apply`: só com plano aprovado. Modo google: substitui os blocos FUTUROS do
   cérebro pelos do plano (porta estreita, gcal.py); modo ics: gera arquivo.
4. `sync`: remove blocos futuros de ações já fechadas (autorizado pelo lote).
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from . import util

Interval = tuple[datetime, datetime]


def _hm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def _vacations(cfg) -> list[tuple[date, date]]:
    out = []
    for v in cfg.get("vacations", []):
        out.append((util.parse_date(v["start"]), util.parse_date(v["end"])))
    return out


def _on_vacation(day: date, vac) -> bool:
    return any(a <= day <= b for a, b in vac)


def work_windows(cfg, day: date) -> list[Interval]:
    w = cfg["work"]
    if day.isoweekday() not in w["days"] or _on_vacation(day, _vacations(cfg)):
        return []
    tz = util.tz()
    start = datetime.combine(day, _hm(w["start"]), tz)
    end = datetime.combine(day, _hm(w["end"]), tz)
    lunch = (w.get("lunch") or "").strip()
    if lunch and "-" in lunch:
        ls, le = (datetime.combine(day, _hm(x), tz) for x in lunch.split("-"))
        return [i for i in ((start, ls), (le, end)) if i[1] > i[0]]
    return [(start, end)]


def _subtract(windows: list[Interval], busy: list[Interval]) -> list[Interval]:
    free = list(windows)
    for bs, be in sorted(busy):
        nxt = []
        for fs, fe in free:
            if be <= fs or bs >= fe:
                nxt.append((fs, fe))
                continue
            if bs > fs:
                nxt.append((fs, bs))
            if be < fe:
                nxt.append((be, fe))
        free = nxt
    return free


def parse_busy(raw, cfg) -> list[Interval]:
    """Eventos (JSON do MCP de calendário ou da API) → intervalos ocupados.
    Ignora: transparentes, cancelados, recusados por você, e os próprios blocos do cérebro
    (serão substituídos). Ausência (out of office) o dia todo bloqueia o dia."""
    if isinstance(raw, dict):
        raw = raw.get("events") or raw.get("items") or raw.get("result") or []
    prefix = cfg["focus"]["title_prefix"]
    buffer = timedelta(minutes=cfg["focus"]["buffer_min"])
    out: list[Interval] = []
    for ev in raw or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("status") == "cancelled" or ev.get("transparency") == "transparent":
            continue
        private = (ev.get("extendedProperties") or {}).get("private") or {}
        if private.get("brain_focus") == "1" or str(ev.get("summary", "")).startswith(f"{prefix} ·"):
            continue
        me = [a for a in ev.get("attendees") or [] if a.get("self")]
        if me and me[0].get("responseStatus") == "declined":
            continue
        s, e = ev.get("start") or {}, ev.get("end") or {}
        etype = str(ev.get("eventType", "")).lower()
        if "dateTime" in s and "dateTime" in e:
            out.append((util.parse_dt(s["dateTime"]) - buffer, util.parse_dt(e["dateTime"]) + buffer))
        elif "date" in s and etype in ("outofoffice", "out_of_office"):
            d0, d1 = util.parse_date(s["date"]), util.parse_date(e.get("date") or s["date"])
            out.append((datetime.combine(d0, time(0), util.tz()), datetime.combine(d1, time(0), util.tz())))
    return out


def latest_calendar_snapshot(vault: Path) -> Path | None:
    cands = list((vault / "RAW" / "inbox").glob("gcal-*.json")) + list((vault / "RAW").glob("*/*/gcal-*.json"))
    return max(cands, key=lambda p: p.name.rsplit("-", 1)[-1]) if cands else None


def _spent(brain, aid: str, now: datetime) -> int:
    mins = 0
    for f in brain.state.focus_plans.values():
        for b in f.applied:
            if b["action"] == aid and util.parse_dt(b["end"]) <= now:
                mins += int((util.parse_dt(b["end"]) - util.parse_dt(b["start"])).total_seconds() // 60)
    return mins


def build_plan(brain, busy: list[Interval], days: int | None = None) -> dict:
    cfg, st = brain.inst.cfg, brain.state
    fc = cfg["focus"]
    now = util.now()
    horizon = days or fc["horizon_days"]
    start_day = now.date()
    end_day = start_day + timedelta(days=horizon)
    step = timedelta(minutes=15)
    earliest = (now + step).replace(second=0, microsecond=0)
    earliest = earliest - timedelta(minutes=earliest.minute % 15)

    free: list[Interval] = []
    d = start_day
    while d < end_day:
        free.extend(_subtract(work_windows(cfg, d), busy))
        d += timedelta(days=1)
    free = [(max(s, earliest), e) for s, e in free if e > earliest]

    cands, missing, consumed, blocked = [], [], [], []
    for a in st.actions.values():
        if not (a.open and a.owner == brain.owner and a.list == "mine" and a.status in ("aberta", "fazendo")):
            continue
        if st.blocked(a):
            blocked.append(a.id)
            continue
        effort = a.effort_min or fc["default_effort_min"]
        if not a.effort_min:
            missing.append(a.id)
        spent = _spent(brain, a.id, now)
        remaining = effort - spent
        if remaining <= 0:
            consumed.append(a.id)
            continue
        cands.append((a, remaining))
    far = date(9999, 1, 1)
    cands.sort(key=lambda x: (x[0].due or far, x[0].priority != "alta", x[0].opened or far, x[0].id))

    used_per_day: dict[date, int] = {}
    blocks: list[dict] = []
    remaining_by: dict[str, int] = {a.id: r for a, r in cands}
    daily_max, bmin, bmax = fc["daily_max_min"], fc["block_min"], fc["block_max"]

    def deadline(a) -> datetime | None:
        if not a.due:
            return None
        return datetime.combine(a.due, _hm(cfg["work"]["end"]), util.tz())

    # EDF estrito: cada ação recebe tudo o que precisa antes da próxima (datadas antes das sem
    # prazo). Espalhar em dias diferentes é só preferência dentro da ação (1ª passada).
    for a, _ in cands:
        for one_per_day in (True, False):
            need = remaining_by[a.id]
            if need <= 0:
                break
            limit = deadline(a)
            days_used = {util.parse_dt(b["start"]).date() for b in blocks if b["action"] == a.id}
            i = 0
            while need > 0 and i < len(free):
                fs, fe = free[i]
                day = fs.date()
                if limit and fs >= limit and a.due >= start_day:
                    break
                if one_per_day and day in days_used:
                    i += 1
                    continue
                left_today = daily_max - used_per_day.get(day, 0)
                span = int((fe - fs).total_seconds() // 60)
                chunk = min(need, bmax, span, left_today)
                if limit and a.due >= start_day:
                    chunk = min(chunk, int((limit - fs).total_seconds() // 60))
                if chunk < bmin and not (need <= chunk):
                    i += 1
                    continue
                if chunk <= 0:
                    i += 1
                    continue
                be = fs + timedelta(minutes=chunk)
                blocks.append({"action": a.id, "start": fs.isoformat(timespec="minutes"),
                               "end": be.isoformat(timespec="minutes"), "minutes": chunk})
                used_per_day[day] = used_per_day.get(day, 0) + chunk
                days_used.add(day)
                need -= chunk
                free[i] = (be, fe)
            remaining_by[a.id] = need

    at_risk, unscheduled = [], []
    for a, total in cands:
        left = remaining_by[a.id]
        if left <= 0:
            continue
        if a.due and a.due < end_day:
            at_risk.append({"action": a.id, "due": a.due.isoformat(), "needed_min": total,
                            "shortfall_min": left, "overdue": a.due < start_day})
        else:
            unscheduled.append({"action": a.id, "left_min": left})
    blocks.sort(key=lambda b: b["start"])
    body = {"blocks": blocks, "at_risk": at_risk, "unscheduled": unscheduled, "missing_effort": missing,
            "consumed": consumed, "blocked": blocked,
            "horizon": {"start": start_day.isoformat(), "end": (end_day - timedelta(days=1)).isoformat()},
            "params": {k: fc[k] for k in ("block_min", "block_max", "daily_max_min", "buffer_min")}}
    body["sha"] = util.sha(json.dumps(body, sort_keys=True))
    return body


def to_ics(plan_id: str, blocks: list[dict], titles: dict[str, str], prefix: str) -> str:
    def fold(line: str) -> str:
        out, raw = [], line.encode("utf-8")
        while len(raw) > 74:
            cut = 74
            while (raw[cut] & 0xC0) == 0x80:
                cut -= 1
            out.append(raw[:cut].decode("utf-8"))
            raw = b" " + raw[cut:]
        out.append(raw.decode("utf-8"))
        return "\r\n".join(out)

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def utc(s: str) -> str:
        return util.parse_dt(s).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    stamp = util.now().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//segundo-cerebro//foco//PT", "CALSCALE:GREGORIAN"]
    for b in blocks:
        aid = b["action"]
        summary = esc(f"{prefix} · {aid} · {titles.get(aid, '')}")
        lines += ["BEGIN:VEVENT", f"UID:{plan_id}-{aid}-{utc(b['start'])}@segundo-cerebro",
                  f"DTSTAMP:{stamp}", f"DTSTART:{utc(b['start'])}", f"DTEND:{utc(b['end'])}",
                  fold(f"SUMMARY:{summary}"), "TRANSP:OPAQUE", "CATEGORIES:FOCO", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _title(brain, b: dict) -> str:
    a = brain.state.actions.get(b["action"])
    return f"{brain.inst.cfg['focus']['title_prefix']} · {b['action']} · {a.title if a else ''}"[:200]


def _description(brain, b: dict) -> str:
    a = brain.state.actions.get(b["action"])
    if not a:
        return "Bloco de foco planejado pelo Segundo Cérebro."
    bits = [f"Ação {a.id}: {a.title}"]
    if a.due:
        bits.append(f"Prazo: {util.fmt_date(a.due, True)}")
    if a.project:
        bits.append(f"Projeto: {a.project} {brain.plan.title(a.project)}")
    bits.append("Bloco planejado pelo Segundo Cérebro (aprovação semanal). "
                "Fechou a ação? O bloco futuro sai no próximo sync.")
    return "\n".join(bits)


def apply(brain, fid: str, mode: str | None = None, cal=None) -> dict:
    st = brain.state
    f = st.focus_plans.get(fid)
    if f is None:
        raise util.BrainError(f"plano {fid} não existe", code=3)
    if f.status != "aprovado":
        raise util.BrainError(f"plano {fid} está '{f.status}' — só plano APROVADO pelo dono vai para o calendário "
                              f"(`brain focus approve {fid} --quote \"<resposta literal>\"`)", code=4)
    approved = next(e for e in reversed(st.events) if e.get("type") == "focus.approved" and e.get("id") == fid)
    if approved.get("data", {}).get("sha") != f.sha:
        raise util.BrainError(f"plano {fid}: a aprovação não corresponde a este plano — aprove de novo", code=4)
    mode = mode or brain.inst.cfg["focus"]["mode"]
    now = util.now()
    blocks = [b for b in f.blocks if util.parse_dt(b["start"]) > now]
    created, removed, skipped = [], [], []
    if mode == "ics":
        titles = {b["action"]: (st.actions[b["action"]].title if b["action"] in st.actions else "") for b in blocks}
        path = brain.inst.fresh / "focus" / f"{fid}.ics"
        util.atomic_write(path, to_ics(fid, blocks, titles, brain.inst.cfg["focus"]["title_prefix"]))
        created = [{**b, "uid": f"{fid}-{b['action']}-{b['start']}"} for b in blocks]
        brain.record_one({"type": "focus.applied", "id": fid, "by": "system",
                          "data": {"mode": "ics", "created": created, "ics": brain.inst.rel(path)}})
        return {"mode": "ics", "created": len(created), "file": str(path), "removed": 0, "skipped": []}

    from .gcal import GoogleCalendar
    cal = cal or GoogleCalendar(brain.inst)
    for other in st.focus_plans.values():
        if other.id == fid or other.mode != "google":
            continue
        gone = []
        for b in other.applied:
            if util.parse_dt(b["start"]) > now and b.get("event_id"):
                cal.delete_guarded(b["event_id"], b["action"])
                gone.append(b)
        if gone:
            brain.record_one({"type": "focus.removed", "id": other.id, "by": "system",
                              "data": {"removed": gone, "reason": f"substituído pelo plano aprovado {fid}"}})
            removed.extend(gone)
    if blocks:
        lo = min(b["start"] for b in blocks)
        hi = max(b["end"] for b in blocks)
        busy = parse_busy(cal.list_events(util.parse_dt(lo).isoformat(), util.parse_dt(hi).isoformat()),
                          {**brain.inst.cfg, "focus": {**brain.inst.cfg["focus"], "buffer_min": 0}})
    else:
        busy = []
    fc = brain.inst.cfg["focus"]
    for b in blocks:
        bs, be = util.parse_dt(b["start"]), util.parse_dt(b["end"])
        if any(s < be and e > bs for s, e in busy):
            skipped.append(b)
            continue
        ev = cal.insert_focus(b, fid, _title(brain, b), _description(brain, b), fc["decline_message"])
        created.append({**b, "event_id": ev.get("id", ""), "link": ev.get("htmlLink", "")})
    brain.record_one({"type": "focus.applied", "id": fid, "by": "system",
                      "data": {"mode": "google", "created": created, "skipped": skipped}})
    return {"mode": "google", "created": len(created), "removed": len(removed), "skipped": skipped}


def sync(brain, dry_run: bool = False, cal=None) -> list[dict]:
    """Remove blocos futuros de ações fechadas/descartadas (autorizado pela aprovação do lote)."""
    st, now = brain.state, util.now()
    todo: list[tuple[str, dict]] = []
    for f in st.focus_plans.values():
        for b in f.applied:
            a = st.actions.get(b["action"])
            if a and not a.open and util.parse_dt(b["start"]) > now:
                todo.append((f.id, b))
    if dry_run or not todo:
        return [b for _, b in todo]
    by_plan: dict[str, list] = {}
    for fid, b in todo:
        f = st.focus_plans[fid]
        if f.mode == "google":
            if cal is None:
                from .gcal import GoogleCalendar
                cal = GoogleCalendar(brain.inst)
            cal.delete_guarded(b["event_id"], b["action"])
        by_plan.setdefault(fid, []).append(b)
    for fid, gone in by_plan.items():
        note = "ação fechada" if st.focus_plans[fid].mode == "google" else \
            "ação fechada — remova do calendário manualmente (modo ics)"
        brain.record_one({"type": "focus.removed", "id": fid, "by": "system", "data": {"removed": gone, "reason": note}})
    return [b for _, b in todo]


def cli(args, brain) -> None:
    c = args.fcmd
    if c == "plan":
        if args.busy_file:
            raw = json.loads(Path(args.busy_file).read_text(encoding="utf-8"))
            src = args.busy_file
        else:
            snap = latest_calendar_snapshot(brain.inst.vault)
            raw = json.loads(snap.read_text(encoding="utf-8")) if snap else []
            src = brain.inst.rel(snap) if snap else "nenhum snapshot de calendário (agenda tratada como livre)"
        busy = parse_busy(raw, brain.inst.cfg)
        body = build_plan(brain, busy, args.days)
        ev = brain.record_one({"type": "focus.planned", "by": "system", "source": src,
                               "data": {"plan_file": "FRESH/focus.md", **body}})
        fid = ev["id"]
        if args.json:
            print(json.dumps({"id": fid, **body}, ensure_ascii=False, indent=2))
            return
        print(f"✓ plano {fid} proposto (nada foi para o calendário) · agenda: {src}")
        for b in body["blocks"]:
            a = brain.state.actions.get(b["action"])
            print(f"  {util.fmt_date(b['start'][:10], True)} {b['start'][11:16]}–{b['end'][11:16]} · {b['action']} "
                  f"{a.title if a else ''}")
        for r in body["at_risk"]:
            print(f"  ⚠ {r['action']} não cabe antes de {util.fmt_date(r['due'])}: faltam "
                  f"{util.fmt_duration(r['shortfall_min'])}")
        if body["missing_effort"]:
            print(f"  sem esforço estimado (usei {brain.inst.cfg['focus']['default_effort_min']}min): "
                  + ", ".join(body["missing_effort"]))
        if body["blocked"]:
            print("  fora do plano por bloqueio: " + ", ".join(body["blocked"]))
        print(f"  → mostre ao dono; aprovação: `brain focus approve {fid} --quote \"<resposta literal>\"`")
    elif c == "approve":
        f = brain.state.focus_plans.get(args.id)
        if f is None:
            raise util.BrainError(f"plano {args.id} não existe", code=3)
        if f.status != "proposto":
            raise util.BrainError(f"plano {args.id} está '{f.status}' — só plano proposto pode ser aprovado", code=4)
        brain.record_one({"type": "focus.approved", "id": args.id, "by": "owner",
                          "data": {"quote": args.quote, "sha": f.sha}})
        print(f"✓ plano {args.id} aprovado (\"{args.quote}\") — aplique com `brain focus apply {args.id}`")
    elif c == "apply":
        res = apply(brain, args.id, args.mode)
        if res["mode"] == "ics":
            print(f"✓ {res['created']} blocos em {res['file']} — importe no Google Calendar "
                  "(Configurações → Importar). Modo ics não remove blocos antigos sozinho.")
        else:
            print(f"✓ {res['created']} blocos de foco criados no calendário · {res['removed']} antigos removidos"
                  + (f" · {len(res['skipped'])} pulados por conflito novo" if res["skipped"] else ""))
    elif c == "sync":
        gone = sync(brain, dry_run=args.dry_run)
        verb = "sairiam" if args.dry_run else "removidos"
        print(f"✓ {len(gone)} blocos futuros de ações fechadas {verb}" if gone else "nada a sincronizar")
    elif c == "show":
        st = brain.state
        f = st.focus_plans.get(args.id) if args.id else (max(st.focus_plans.values(), key=lambda x: x.id)
                                                          if st.focus_plans else None)
        if f is None:
            print("nenhum plano de foco")
            return
        payload = {"id": f.id, "status": f.status, "mode": f.mode, "blocks": f.blocks, "applied": f.applied}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"{f.id} · {f.status}" + (f" · {f.mode}" if f.mode else ""))
            for b in (f.applied if f.status == "aplicado" else f.blocks):
                print(f"  {b['start'][:16].replace('T', ' ')}–{b['end'][11:16]} · {b['action']}")
