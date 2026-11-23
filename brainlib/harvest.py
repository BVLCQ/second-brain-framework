"""Colheita: edições do dono em superfícies derivadas viram eventos declarados.

FRESH é regenerado inteiro a cada render — então, ANTES de sobrescrever, olhamos
o que o dono mudou desde o último render:
  · checkbox de ação em FRESH/todo.md            → fechar / reabrir
  · `status:` de FRESH/records/actions/TASK-*.md     → ficha da ação (qualquer editor)
  · `status:` de FRESH/records/opportunities/OPP-*.md → status da oportunidade (valor inválido: aviso, não grava)
  · checkbox de entregável em PLANNING/goals.md   → estado factual do entregável
Só essas mudanças são colhidas; qualquer outra edição em FRESH é descartada.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from . import ids, planning, util

STATE_FILE = ".render-state.json"
HARVEST_GUARD_FILE = "harvest-guard.json"
TODO_LINE = re.compile(r"^\s*-\s+\[( |x|X)\]\s+.*?\b(TASK-\d{4,}|" + ids.LEGACY_ACTION_SRC + r")\b")
FRONT_STATUS = re.compile(r"^status:\s*\"?([^\"\n]+?)\"?\s*$", re.M)

KANBAN_TO_EVENT = {
    "feita": ("action.closed", {"how": "marcada como feita na ficha (status)"}),
    "descartada": ("action.dropped", {"reason": "descartada na ficha (status)"}),
    "fazendo": ("action.updated", {"status": "fazendo", "note": "movida para fazendo (status)"}),
    "a fazer": ("action.updated", {"status": "aberta", "note": "movida para a fazer (status)"}),
    "aguardando": ("action.updated", {"status": "aguardando", "note": "movida para aguardando (status)"}),
}


def load_state(fresh: Path) -> dict:
    return util.read_json(fresh / STATE_FILE, {})


def watched_paths(inst) -> dict[str, Path]:
    """Enumera os caminhos que `collect()` lê (estado inicial antes do agente)."""
    paths: dict[str, Path] = {"FRESH/todo.md": inst.fresh / "todo.md"}
    act_dir = inst.fresh / "records" / "actions"
    if act_dir.exists():
        for p in sorted(act_dir.glob("TASK-*.md")):
            paths[f"FRESH/records/actions/{p.name}"] = p
    opp_dir = inst.fresh / "records" / "opportunities"
    if opp_dir.exists():
        for p in sorted(opp_dir.glob("OPP-*.md")):
            paths[f"FRESH/records/opportunities/{p.name}"] = p
    paths["PLANNING/goals.md"] = inst.planning_file
    return paths


def _deliverable_lines(text: str) -> dict[str, str]:
    lines = planning._lines(text)
    plan = planning.parse(text)
    return {
        did: lines[d.line_no - 1]
        for did, d in plan.deliverables.items()
        if 1 <= d.line_no <= len(lines)
    }


def snapshot_inputs(inst) -> dict[str, dict]:
    """Impressão digital (sha256 + mtime_ns; no goals.md também o texto e as linhas de entregáveis) dos arquivos colhidos."""
    out: dict[str, dict] = {}
    for rel, path in watched_paths(inst).items():
        if not path.is_file():
            continue
        st = path.stat()
        raw = path.read_bytes()
        entry: dict = {
            "sha": hashlib.sha256(raw).hexdigest(),
            "mtime_ns": st.st_mtime_ns,
        }
        if rel == "PLANNING/goals.md":
            text = raw.decode("utf-8", "replace")
            entry["text"] = text
            entry["deliverable_lines"] = _deliverable_lines(text)
        out[rel] = entry
    return out


def _ledger_seq(inst) -> int:
    """`seq` do último evento do ledger (0 se vazio ou ilegível). Lê só o rabo do arquivo: é a marca de até onde o
    ledger ia quando a janela abriu — evento de entregável com `seq` maior nasceu DEPOIS, por comando com gate."""
    from . import core  # import tardio: o núcleo não pode depender da colheita

    try:
        with (inst.vault / core.LEDGER_REL).open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            tail = fh.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return 0
    for line in reversed(tail):
        line = line.strip()
        if not line:
            continue
        try:
            seq = json.loads(line).get("seq")
        except json.JSONDecodeError:
            continue
        return seq if isinstance(seq, int) else 0
    return 0


def _guard_path(inst) -> Path:
    return inst.logs / HARVEST_GUARD_FILE


def _write_guard(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _timeout_min(inst) -> int:
    cfg = inst.cfg if isinstance(inst.cfg, dict) else {}
    runner_cfg = cfg.get("runner") if isinstance(cfg.get("runner"), dict) else {}
    try:
        val = int(runner_cfg.get("timeout_min", 45))
    except (TypeError, ValueError):
        val = 45
    return max(0, val)


def _read_guard(path: Path) -> dict | None:
    """Lê `harvest-guard.json` sem apagar. None se não existe ou não tem a forma de uma janela."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None


def _window_end(window: dict) -> int:
    """Fim efetivo da janela: `ended_ns`; janela sem fim (crash) vale até o menor entre agora e o deadline."""
    ended = window.get("ended_ns")
    if isinstance(ended, int):
        return ended
    now_ns = time.time_ns()
    deadline = window.get("deadline_ns")
    return min(now_ns, deadline) if isinstance(deadline, int) else now_ns


def begin_agent_window(inst, label: str = "agent", strict: bool = False) -> dict:
    """Abre a janela de proteção antes de rodar o agente e grava `harvest-guard.json` (0600).

    Janela anterior que nenhum render consumiu (dois jobs do painel sem "regenerar views" no meio) não é
    descartada: para o que ela já tinha como edição de agente, o "antes" continua sendo o da janela mais antiga.
    Sobrescrever sem olhar faria a segunda janela adotar a edição do primeiro agente como ponto de partida, e o
    render seguinte a colheria como se fosse do dono.
    """
    started_ns = time.time_ns()
    deadline_ns = started_ns + (_timeout_min(inst) + 10) * 60 * 1_000_000_000
    ledger_seq = _ledger_seq(inst)
    previous = _read_guard(_guard_path(inst))
    files = snapshot_inputs(inst)
    if previous:
        strict = bool(strict) or bool(previous.get("strict"))
        old_end = _window_end(previous)
        if isinstance(previous.get("started_ns"), int):
            started_ns = previous["started_ns"]
        if isinstance(previous.get("ledger_seq"), int):
            ledger_seq = previous["ledger_seq"]
        paths = watched_paths(inst)
        for rel, entry in files.items():
            old = previous["files"].get(rel)
            path = paths.get(rel)
            if path is None or not path.is_file():
                continue  # apareceu ou sumiu entre a foto e a enumeração: não dá para julgar
            if old is not None and old.get("sha") is None:
                files[rel] = old  # nasceu dentro de uma janela de agente: continua sendo do agente
                continue
            changed = old is None or entry["sha"] != old.get("sha")
            if changed and _changed_before(path, old_end, bool(previous.get("strict"))):
                # Editado por agente na janela anterior. Arquivo que não existia lá (`old is None`) fica sem sha:
                # qualquer conteúdo dele é do agente.
                files[rel] = old if old is not None else {**entry, "sha": None}
    snap = {
        "label": label,
        "strict": bool(strict),
        "started_ns": started_ns,
        "deadline_ns": deadline_ns,
        "ledger_seq": ledger_seq,
        "files": files,
    }
    _write_guard(_guard_path(inst), snap)
    return snap


def end_agent_window(inst, snap: dict) -> dict:
    """Fecha a janela gravando `ended_ns` e devolve o mesmo dicionário."""
    snap["ended_ns"] = time.time_ns()
    _write_guard(_guard_path(inst), snap)
    return snap


def consume_agent_window(inst) -> dict | None:
    """Lê e remove `harvest-guard.json`. Se não foi finalizado (crash), limita `ended_ns` ao deadline."""
    path = _guard_path(inst)
    data = _read_guard(path)
    path.unlink(missing_ok=True)
    if data is not None and not isinstance(data.get("ended_ns"), int):
        data["ended_ns"] = _window_end(data)
    return data


def _changed_before(path: Path, end_ns: int, strict: bool) -> bool:
    """True quando a alteração do arquivo aconteceu até `end_ns` (fim da janela, ou deadline dela se não fechou).

    mtime dentro da janela: é do agente. mtime depois do fim: é do dono — exceto no modo estrito (noturno) quando o
    ctime ainda está dentro da janela: `touch -d` forja um mtime futuro, mas não forja o ctime, que o kernel grava
    na hora da alteração. Só mtime E ctime posteriores ao fim contam como edição do dono.
    """
    st = path.stat()
    if st.st_mtime_ns <= end_ns:
        return True
    return strict and st.st_ctime_ns <= end_ns


def _is_absorbed(rel: str, path: Path, window: dict | None) -> bool:
    """True quando o arquivo mudou na janela do agente e não é uma edição posterior do dono."""
    if window is None:
        return False
    before = (window.get("files") or {}).get(rel)
    cur_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if before is not None and cur_sha == before.get("sha"):
        return False
    ended_ns = window.get("ended_ns")
    if isinstance(ended_ns, int) and not _changed_before(path, ended_ns, bool(window.get("strict"))):
        return False
    return True


def _owner_event(t: str, aid: str, data: dict, source: str) -> dict:
    return {"type": t, "id": aid, "by": "owner", "prov": "declarado", "source": source, "data": data}


def _deliverable_event(did: str, d) -> dict:
    ev = {"type": "deliverable.updated", "id": did, "by": "owner", "prov": "declarado",
          "source": "PLANNING/goals.md (edição manual)", "data": {"status": d.status}}
    if d.status == "feito" and d.done_date:
        ev["date"] = d.done_date.isoformat()
    return ev


def _known_status(st, did: str) -> str:
    hist = st.deliverable_events.get(did, [])
    return hist[-1]["data"]["status"] if hist else "nao-iniciado"


def _skeleton(lines: list[str], plan) -> list[str]:
    """`goals.md` sem as linhas de entregável — para saber se o resto do arquivo mudou."""
    skip = {d.line_no - 1 for d in plan.deliverables.values()}
    return [ln for i, ln in enumerate(lines) if i not in skip]


def _project_block_end(lines: list[str], did: str) -> int:
    """Onde entra uma linha de entregável de `did` quando não sobrou vizinha conhecida: fim do bloco de
    entregáveis do projeto; sem bloco, depois dos metadados do cabeçalho do projeto; sem cabeçalho, fim do arquivo."""
    proj = did.rsplit(".", 1)[0]
    same = [i for i, ln in enumerate(lines)
            if (m := planning.DELIV_RE.match(ln)) and ids.normalize(m.group(4)).startswith(proj + ".")]
    if same:
        return max(same) + 1
    head = next((i for i, ln in enumerate(lines)
                 if (m := planning.PROJ_RE.match(ln)) and ids.normalize(m.group(1)) == proj), None)
    if head is None:
        return len(lines)
    pos = head + 1
    while pos < len(lines) and lines[pos].startswith("- ") and not planning.DELIV_RE.match(lines[pos]):
        pos += 1
    return pos


def _reinsert_deleted(lines: list[str], before_list: list[str], before_plan, missing: list[str]) -> None:
    """Repõe em `lines`, no lugar, linha de entregável que sumiu na janela.

    O lugar se acha pelas vizinhas que sobraram e já existiam no arquivo de antes: depois da última que vinha
    antes dela; se ela era a primeira, antes da primeira que vinha depois. Sem vizinha conhecida,
    `_project_block_end`. As apagadas entram da última para a primeira, para a ordem antiga se refazer.
    """
    cur = planning.parse("\n".join(lines))
    # índice em `lines` → posição (line_no) que a linha ocupava no arquivo de antes
    where = {d.line_no - 1: before_plan.deliverables[d.id].line_no
             for d in cur.deliverables.values() if d.id in before_plan.deliverables}
    for did in sorted(missing, key=lambda x: before_plan.deliverables[x].line_no, reverse=True):
        bd = before_plan.deliverables[did]
        earlier = [i for i, v in where.items() if v < bd.line_no]
        later = [i for i, v in where.items() if v > bd.line_no]
        pos = max(earlier) + 1 if earlier else min(later) if later else _project_block_end(lines, did)
        lines.insert(pos, before_list[bd.line_no - 1])
        where = {(i + 1 if i >= pos else i): v for i, v in where.items()}
        where[pos] = bd.line_no


def _absorb_goals(brain, goals_path: Path, window: dict, events: list[dict], notices: list[dict]) -> None:
    """`goals.md` mudou durante a janela do agente.

    Linha de entregável que mudou na janela só fica se o ledger tem evento dela registrado DEPOIS do ponto em que
    a janela abriu e o estado da linha confere com esse evento: é comando com gate (`brain plan deliverable`
    reescreve a linha e registra o evento na mesma chamada). Sem evento, é edição direta no arquivo — volta ao que
    era (ou sai, se a linha foi plantada) e nada vira fato do dono. O resto do arquivo é mantido, com aviso: pode
    ser cadastro com gate (`brain plan add`), e desfazer deixaria ledger e arquivo divergentes.
    """
    st = brain.state
    before_entry = (window.get("files") or {}).get("PLANNING/goals.md") or {}
    before_text = before_entry.get("text")
    before_lines: dict[str, str] = before_entry.get("deliverable_lines") or {}
    since = window.get("ledger_seq")
    lines = planning._lines(goals_path.read_text(encoding="utf-8"))
    plan = planning.parse("\n".join(lines))
    before_plan = planning.parse(before_text) if isinstance(before_text, str) else None
    restored: list[str] = []
    kept: list[str] = []
    planted: list[tuple[str, str]] = []
    drop: list[int] = []
    for did, d in plan.deliverables.items():
        i = d.line_no - 1
        cur_line = lines[i] if 0 <= i < len(lines) else ""
        known = _known_status(st, did)
        hist = st.deliverable_events.get(did, [])
        if isinstance(since, int):
            gated = bool(hist) and hist[-1].get("seq", 0) > since and d.status == hist[-1]["data"]["status"]
        else:
            gated = d.status == known  # janela sem a marca do ledger: só o último estado do ledger serve de prova
        if did not in before_lines:
            if not gated and d.status != known:
                drop.append(i)
                planted.append((did, cur_line))
            continue
        if cur_line == before_lines[did]:
            if d.status != known:
                events.append(_deliverable_event(did, d))  # edição do dono feita ANTES da janela, ainda não colhida
            continue
        if gated:
            kept.append(did)
            continue
        if 0 <= i < len(lines):
            lines[i] = before_lines[did]
        restored.append(did)
        bd = before_plan.deliverables.get(did) if before_plan else None
        if bd is not None and bd.status != known:
            events.append(_deliverable_event(did, bd))  # o dono tinha marcado essa linha antes da janela
    for i in sorted(drop, reverse=True):
        del lines[i]
    missing = [did for did in before_lines if did not in plan.deliverables] if before_plan is not None else []
    if missing:
        _reinsert_deleted(lines, planning._lines(before_text), before_plan, missing)
    if restored or planted or missing:
        util.atomic_write(goals_path, "\n".join(lines) + "\n")
        brain._plan = None
    title = "colheita"
    if restored:
        notices.append({"level": "warn", "title": title,
                        "detail": f"PLANNING/goals.md alterado durante a janela do agente ({', '.join(restored)}) — "
                                  "linha restaurada (se foi você, marque novamente)"})
    if missing:
        notices.append({"level": "warn", "title": title,
                        "detail": "PLANNING/goals.md: linha de entregável apagada durante a janela do agente "
                                  f"({', '.join(missing)}) — repostas"})
    for did, cur_line in planted:
        notices.append({"level": "warn", "title": title,
                        "detail": "PLANNING/goals.md: entregável novo na janela do agente sem evento no ledger "
                                  f"({did}) — linha removida: {cur_line!r}"})
    if kept:
        notices.append({"level": "warn", "title": title,
                        "detail": "PLANNING/goals.md: linha de entregável mudou na janela do agente e tem evento no "
                                  f"ledger ({', '.join(kept)}) — mantida"})
    if before_plan is not None:
        now_plan = planning.parse("\n".join(lines))
        if _skeleton(lines, now_plan) != _skeleton(planning._lines(before_text), before_plan):
            notices.append({"level": "warn", "title": title,
                            "detail": "PLANNING/goals.md: linhas fora de entregáveis mudaram na janela do agente — "
                                      "mantidas; revise o arquivo"})


def _opportunity_events(brain, last: dict, notices: list[dict], window: dict | None = None) -> list[dict]:
    from .schema import OPP_REASON_STATUS, OPP_STATUS
    out = []
    rec_dir = brain.inst.fresh / "records" / "opportunities"
    for path in sorted(rec_dir.glob("OPP-*.md")) if rec_dir.exists() else []:
        oid = path.stem
        o = brain.state.opportunities.get(oid)
        prev = last.get("records", {}).get(oid)
        m = FRONT_STATUS.search(path.read_text(encoding="utf-8"))
        if not o or not m or prev is None:
            continue
        now_val = util.fold(m.group(1))
        if now_val == util.fold(prev) or now_val == o.status:
            continue
        src = f"FRESH/records/opportunities/{oid}.md"
        if _is_absorbed(src, path, window):
            notices.append({"level": "warn", "title": "colheita",
                            "detail": f"{src} alterado durante a janela do agente ({oid}: status '{m.group(1)}') — "
                                      "ignorado (se foi você, marque novamente)"})
            continue
        if now_val not in OPP_STATUS:
            notices.append({"level": "warn", "title": "ficha", "detail": f"{oid}: status '{m.group(1)}' inválido — "
                            f"nada gravado (use {', '.join(sorted(OPP_STATUS))})"})
        elif now_val == "em-andamento" and not o.promoted:
            notices.append({"level": "warn", "title": "ficha", "detail": f"{oid}: 'em-andamento' só depois de promover "
                            "(`brain opportunity promote`, qualquer nível) — nada gravado"})
        else:
            data = {"status": now_val}
            if now_val in OPP_REASON_STATUS:
                data["reason"] = "alterado na ficha (status)"
            out.append(_owner_event("opportunity.status", oid, data, src))
    return out


def collect(brain, notices: list[dict] | None = None, window: dict | None = None) -> list[dict]:
    st = brain.state
    fresh = brain.inst.fresh
    last = load_state(fresh)
    notices = notices if notices is not None else []
    events: list[dict] = []
    touched: set[str] = set()

    rec_dir = fresh / "records" / "actions"
    for path in sorted(rec_dir.glob("TASK-*.md")) if rec_dir.exists() else []:
        aid = path.stem
        a = st.actions.get(aid)
        prev = last.get("records", {}).get(aid)
        m = FRONT_STATUS.search(path.read_text(encoding="utf-8"))
        if not a or not m or prev is None:
            continue
        now_val = util.fold(m.group(1))
        if now_val == util.fold(prev) or now_val not in KANBAN_TO_EVENT:
            continue
        t, data = KANBAN_TO_EVENT[now_val]
        if t in ("action.closed", "action.dropped") and not a.open:
            continue
        src = f"FRESH/records/actions/{aid}.md"
        if _is_absorbed(src, path, window):
            notices.append({"level": "warn", "title": "colheita",
                            "detail": f"{src} alterado durante a janela do agente ({aid}: status '{m.group(1)}') — "
                                      "ignorado (se foi você, marque novamente)"})
            continue
        if t == "action.updated" and not a.open:
            events.append(_owner_event("action.reopened", aid, {"reason": data["note"]}, src))
        events.append(_owner_event(t, aid, dict(data), src))
        touched.add(aid)

    todo = fresh / "todo.md"
    if todo.exists():
        prev_todo = last.get("todo", {})
        todo_absorbed = _is_absorbed("FRESH/todo.md", todo, window)
        absorbed_todo_ids: list[str] = []
        for ln in todo.read_text(encoding="utf-8").split("\n"):
            m = TODO_LINE.match(ln)
            if not m:
                continue
            checked, aid = m.group(1) in "xX", ids.normalize(m.group(2))
            a = st.actions.get(aid)
            if not a or aid in touched or aid not in prev_todo or prev_todo[aid] == checked:
                continue
            if not ((checked and a.open) or (not checked and not a.open)):
                continue
            if todo_absorbed:
                absorbed_todo_ids.append(aid)
                touched.add(aid)
                continue
            if checked and a.open:
                events.append(_owner_event("action.closed", aid, {"how": "marcada como feita em todo.md"},
                                           "FRESH/todo.md"))
            elif not checked and not a.open:
                events.append(_owner_event("action.reopened", aid, {"reason": "desmarcada em todo.md"},
                                           "FRESH/todo.md"))
            touched.add(aid)
        if absorbed_todo_ids:
            notices.append({"level": "warn", "title": "colheita",
                            "detail": f"FRESH/todo.md alterado durante a janela do agente ({', '.join(absorbed_todo_ids)}) — "
                                      "ignorado (se foi você, marque novamente)"})

    events += _opportunity_events(brain, last, notices, window=window)

    goals_path = brain.inst.planning_file
    if window is not None and goals_path.exists() and _is_absorbed("PLANNING/goals.md", goals_path, window):
        _absorb_goals(brain, goals_path, window, events, notices)
    else:
        plan = brain.plan
        for did, d in plan.deliverables.items():
            if d.status != _known_status(st, did):
                events.append(_deliverable_event(did, d))
    return events


def run(brain, notices: list[dict] | None = None, window: dict | None = None) -> list[dict]:
    events = collect(brain, notices, window=window)
    return brain.record(events) if events else []


def save_state(fresh: Path, todo: dict[str, bool], records: dict[str, str]) -> None:
    util.write_json(fresh / STATE_FILE, {"rendered_at": util.iso_now(), "todo": todo, "records": records})
