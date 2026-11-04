"""Projeção SQLite do ledger (Fase 1 do plano da memória) — `FRESH/_index/brain.sqlite`.

O JSONL continua sendo a verdade (append-only, grep-ável). Isto é **índice derivado**:
consultas de estado (prazo, atraso, quem deve) e busca por palavra deixam de refazer
a dobra do zero em cada processo. Reconstruível a qualquer momento (`brain index rebuild`).

Contrato multi-processo (emenda R1): update inteiro sob flock de `FRESH/_index/.update.lock`;
`last_seq` só avança (compare-and-set); `busy_timeout=2000` em TODA conexão, inclusive
leitura. Leitores usam mode=ro + query_only. Fallback final: sem índice, todo leitor
cai no caminho que já existia (refold).
"""
from __future__ import annotations

import fcntl
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import util

DIR_NAME = "_index"
DB_NAME = "brain.sqlite"
LOCK_NAME = ".update.lock"
SCHEMA_VERSION = "1"
BUSY_TIMEOUT_MS = 2000
RAW_TEXT = {".md", ".txt", ".csv", ".json", ".html", ".htm", ".vtt", ".srt", ".tsv"}
QUERY_LIMIT = 500

# eventos que são telemetria de fonte (ficam no ledger; nas views de índice, filtrados por classe)
TELEMETRY = re.compile(r"^(connector\.|snapshot|repos\.|nightly\.|render\.|index\.)")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY, ts TEXT, type TEXT, id TEXT, date TEXT,
  actor TEXT, by TEXT, prov TEXT, source TEXT, data TEXT,
  class TEXT
);
CREATE INDEX IF NOT EXISTS ev_id ON events(id);
CREATE INDEX IF NOT EXISTS ev_type_date ON events(type, date);

CREATE TABLE IF NOT EXISTS actions(
  id TEXT PRIMARY KEY, title TEXT, owner TEXT, list TEXT, status TEXT,
  due TEXT, due_suggested INTEGER, priority TEXT, parked INTEGER,
  project TEXT, deliverable TEXT, opened TEXT, closed TEXT, last_activity TEXT,
  source TEXT, prov TEXT, is_open INTEGER, is_overdue INTEGER, is_blocked INTEGER
);
CREATE INDEX IF NOT EXISTS act_open ON actions(is_open, due);
CREATE INDEX IF NOT EXISTS act_owner ON actions(owner, is_open);

CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, title TEXT, date TEXT, project TEXT,
  status TEXT, superseded_by TEXT, context TEXT, rationale TEXT, source TEXT, prov TEXT);
CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY, title TEXT, date TEXT, ref TEXT,
  result TEXT, impact TEXT, source TEXT, prov TEXT);
CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY, name TEXT, role TEXT, relation TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS aliases(alias_fold TEXT, person_id TEXT, PRIMARY KEY(alias_fold, person_id));
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, kind TEXT, title TEXT, date TEXT, raw TEXT,
  summary TEXT, link TEXT);
CREATE TABLE IF NOT EXISTS processes(id TEXT PRIMARY KEY, title TEXT, area TEXT, hours_month REAL, data TEXT);
CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, title TEXT, area TEXT, status TEXT,
  ice REAL, ice_suggested INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, text TEXT, status TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS feedbacks(id TEXT PRIMARY KEY, kind TEXT, title TEXT, status TEXT,
  number INTEGER, url TEXT, issue_state TEXT, source TEXT, prov TEXT);
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, kind TEXT, status TEXT, target TEXT);
CREATE TABLE IF NOT EXISTS planning(id TEXT PRIMARY KEY, kind TEXT, parent TEXT, title TEXT,
  status TEXT, due TEXT, done TEXT, weight REAL, progress REAL);
CREATE TABLE IF NOT EXISTS edges(src TEXT, rel TEXT, dst TEXT, PRIMARY KEY(src, rel, dst));
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, rel);

CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
  kind, ref, title, body, date UNINDEXED, path UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS fts_docs(path TEXT PRIMARY KEY, sha TEXT);
"""


def db_path(inst) -> Path:
    return inst.fresh / DIR_NAME / DB_NAME


@contextmanager
def connect(path: Path, ro: bool = False):
    uri = f"file:{path}?mode=ro" if ro else f"file:{path}"
    con = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        if ro:
            con.execute("PRAGMA query_only=1")
        else:
            con.execute("PRAGMA journal_mode=WAL")
        yield con
    finally:
        con.close()


@contextmanager
def _update_lock(inst):
    d = inst.fresh / DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    fh = open(d / LOCK_NAME, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _event_class(ev: dict) -> str:
    if TELEMETRY.match(str(ev.get("type") or "")):
        return "telemetria"
    return {"owner": "dono", "system": "sistema"}.get(str(ev.get("by") or ""), "fato")


def _dt(v) -> str | None:
    if v is None or v == "":
        return None
    return v if isinstance(v, str) else v.isoformat()


def _materialize_entities(con: sqlite3.Connection, brain) -> None:
    """Tabelas de entidade: rematerializadas do State dobrado numa transação."""
    st = brain.state
    plan = brain.plan
    cur = con.cursor()
    for t in ("actions", "decisions", "deliveries", "people", "aliases", "artifacts", "processes",
              "opportunities", "questions", "feedbacks", "proposals", "planning", "edges"):
        cur.execute(f"DELETE FROM {t}")
    today = util.today()
    for a in st.actions.values():
        blocked = bool(st.blocked(a))
        overdue = int(bool(a.open and a.due and a.due < today))
        cur.execute("INSERT OR REPLACE INTO actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            a.id, a.title, a.owner, a.list, a.status, _dt(a.due), int(a.due_suggested), a.priority,
            int(a.parked), a.project, a.deliverable, _dt(a.opened), _dt(a.closed), _dt(a.last_activity),
            a.source, a.prov, int(a.open), overdue, int(blocked)))
        for p in a.people:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (a.id, "person", p))
        if a.project:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (a.id, "project", a.project))
        if a.owner:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (a.id, "owner", a.owner))
        for b in a.blocked_by:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (a.id, "blocked_by", b))
        for u in a.unblocks:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (a.id, "unblocks", u))
    for d in st.decisions.values():
        cur.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?)", (
            d.id, d.title, _dt(d.date), d.project, d.status, d.superseded_by, d.context, d.rationale,
            d.source, d.prov))
        for p in d.decided_by:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (d.id, "decided_by", p))
        if d.project:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (d.id, "project", d.project))
        if d.supersedes:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (d.id, "supersedes", d.supersedes))
    for e in st.deliveries.values():
        cur.execute("INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?,?,?,?,?)", (
            e.id, e.title, _dt(e.date), e.ref, e.result, e.impact, e.source, e.prov))
        if e.ref:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (e.id, "action", e.ref))
    for p in st.people.values():
        cur.execute("INSERT OR REPLACE INTO people VALUES (?,?,?,?,?)", (
            p.id, p.name, getattr(p, "role", ""), getattr(p, "relation", ""), getattr(p, "email", "")))
        for alias in {p.name, *p.aliases}:
            if alias:
                cur.execute("INSERT OR IGNORE INTO aliases VALUES (?,?)", (util.fold(alias), p.id))
    for art in st.artifacts.values():
        cur.execute("INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?,?)", (
            art.id, art.kind, art.title, _dt(art.date), art.raw, art.summary, art.link))
        for p in art.people:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (art.id, "artifact_person", p))
        for pr in art.projects:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (art.id, "artifact_project", pr))
    for pr in st.processes.values():
        cur.execute("INSERT OR REPLACE INTO processes VALUES (?,?,?,?,?)", (
            pr.id, pr.title, pr.area, pr.hours_month, json.dumps({"io": pr.io}, ensure_ascii=False)))
    for o in st.opportunities.values():
        cur.execute("INSERT OR REPLACE INTO opportunities VALUES (?,?,?,?,?,?,?)", (
            o.id, o.title, o.area, o.status, o.score, int(bool(o.ice_suggested)),
            json.dumps({"problem": o.problem, "suggestion": o.suggestion, "gain": o.gain}, ensure_ascii=False)))
        if o.process:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (o.id, "opp_process", o.process))
        if o.area:
            cur.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (o.id, "opp_area", o.area))
    for q in st.questions.values():
        cur.execute("INSERT OR REPLACE INTO questions VALUES (?,?,?,?)", (q.id, q.text, q.status, q.kind))
    for f in st.feedbacks.values():
        cur.execute("INSERT OR REPLACE INTO feedbacks VALUES (?,?,?,?,?,?,?,?,?)", (
            f.id, f.kind, f.title, f.status, f.number, f.url, f.issue_state, f.source, f.prov))
    for p in st.proposals.values():
        cur.execute("INSERT OR REPLACE INTO proposals VALUES (?,?,?,?)", (p.id, p.kind, p.status, p.target))
    # PLANNING: progresso = peso dos feitos ÷ peso dos não cancelados
    for dl in plan.deliverables.values():
        cur.execute("INSERT OR REPLACE INTO planning VALUES (?,?,?,?,?,?,?,?,?)", (
            dl.id, "deliverable", dl.project_id, dl.title, dl.status, _dt(dl.due), _dt(dl.done_date),
            dl.weight, 1.0 if dl.done else 0.0))
    for pr in plan.projects.values():
        dls = [d for d in plan.deliverables.values() if d.project_id == pr.id and d.status != "cancelado"]
        w = sum(d.weight for d in dls)
        prog = (sum(d.weight for d in dls if d.done) / w) if w else None
        cur.execute("INSERT OR REPLACE INTO planning VALUES (?,?,?,?,?,?,?,?,?)", (
            pr.id, "project", pr.goal_id, pr.title, pr.status, None, None, None, prog))
    for g in plan.goals.values():
        dls = [d for d in plan.deliverables.values()
               if plan.projects.get(d.project_id) and plan.projects[d.project_id].goal_id == g.id
               and d.status != "cancelado"]
        w = sum(d.weight for d in dls)
        prog = (sum(d.weight for d in dls if d.done) / w) if w else None
        cur.execute("INSERT OR REPLACE INTO planning VALUES (?,?,?,?,?,?,?,?,?)", (
            g.id, "goal", None, g.title, g.status, None, None, None, prog))


def _fts_entity_rows(brain) -> list[tuple]:
    st, plan = brain.state, brain.plan
    rows = []
    for a in st.actions.values():
        rows.append(("ação", a.id, a.title,
                     " ".join(filter(None, [st.person_name(a.owner), a.how, a.outcome, a.origin,
                                            (plan.projects[a.project].title if a.project in plan.projects else "")])),
                     _dt(a.due) or _dt(a.opened), None))
    for d in st.decisions.values():
        names = " ".join(st.person_name(p) for p in d.decided_by)
        rows.append(("decisão", d.id, d.title, " ".join([names, d.context, d.rationale]), _dt(d.date), None))
    for e in st.deliveries.values():
        rows.append(("entrega", e.id, e.title, " ".join([e.result, e.evidence, e.impact]), _dt(e.date), None))
    for p in st.people.values():
        rows.append(("pessoa", p.id, p.name,
                     " ".join([*p.aliases, getattr(p, "role", ""), getattr(p, "relation", ""),
                               getattr(p, "email", "")]), None, None))
    for g in plan.goals.values():
        rows.append(("goal", g.id, g.title, g.meta.get("por quê", ""), None, None))
    for pr in plan.projects.values():
        rows.append(("projeto", pr.id, pr.title, " ".join(d.title for d in plan.deliverables.values()
                                                          if d.project_id == pr.id), None, None))
    for pr in st.processes.values():
        rows.append(("processo", pr.id, pr.title, " ".join([pr.io, *pr.pains, *pr.tools, *pr.notes]), None, None))
    for o in st.opportunities.values():
        rows.append(("oportunidade", o.id, o.title, " ".join([o.problem, o.suggestion, o.gain, *o.notes]), None, None))
    for art in st.artifacts.values():
        rows.append(("artefato", art.id, art.title, art.summary, _dt(art.date), art.id))
    for f in st.feedbacks.values():
        rows.append(("feedback", f.id, f.title, f.kind, _dt(f.added), None))
    # NOTA: notas avulsas NÃO entram aqui — são entidade de arquivo (sem evento), o search as
    # mergulha ao vivo (search._note_hits) para não ficarem velhas entre updates.
    return rows


def _fts_doc_rows(brain, fts_docs: dict[str, str]) -> list[tuple]:
    """PROCESSED (md), RAW (tipos §3.2) e PLANNING/PROFILE por sha — só o que mudou."""
    inst = brain.inst
    out: list[tuple] = []

    def want(path: Path, rel: str) -> tuple | None:
        if not path.is_file() or path.suffix.lower() not in RAW_TEXT or path.name.startswith("."):
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        sha = util.sha(text)
        if fts_docs.get(rel) == sha:
            return None
        return (rel, sha, text)

    for path in sorted(inst.processed.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/*.md")):
        rel = inst.rel(path)
        got = want(path, rel)
        if got:
            out.append(("artefato-md", rel, path.stem, got[2], None, rel, got[1]))
    raw = inst.vault / "RAW"
    from . import notes as notes_mod
    note_paths = {Path(n.path).name for n in notes_mod.scan(inst)}   # a nota já entra como kind "nota"
    if raw.exists():
        for path in sorted(raw.rglob("*")):
            if "inbox" in path.relative_to(raw).parts or path.name in note_paths:
                continue
            rel = inst.rel(path)
            got = want(path, rel)
            if got:
                out.append(("raw", rel, path.stem, got[2], None, rel, got[1]))
    for rel in ("PLANNING/goals.md", "PLANNING/log.md", "PROFILE/profile.md"):
        got = want(inst.vault / rel, rel)
        if got:
            out.append(("planejamento" if rel.startswith("PLANNING") else "perfil", rel, rel,
                        got[2], None, rel, got[1]))
    return out


def _ledger_tail_sha(path: Path) -> str | None:
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, path.stat().st_size - 8192))
            tail = fh.read().rstrip(b"\n").split(b"\n")[-1]
        return util.sha(tail.decode("utf-8", errors="replace"))
    except OSError:
        return None


def update(brain) -> dict:
    """Atualização incremental (seq > last_seq); ledger encolheu/última linha mudou → rebuild."""
    path = db_path(brain.inst)
    ledger = brain.inst.processed / "_ledger" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _update_lock(brain.inst):
        con = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            con.execute("PRAGMA journal_mode=WAL")       # persistente: leitor ro não trava o escritor
            con.executescript(SCHEMA)
            meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
            size = ledger.stat().st_size if ledger.exists() else 0
            tail = _ledger_tail_sha(ledger)
            full = (not meta.get("last_seq")
                    or (int(meta.get("ledger_size") or 0) > size)
                    or (meta.get("ledger_sha_tail") not in (None, tail)))
            events = brain.state.events
            last = 0 if full else int(meta.get("last_seq") or 0)
            new = events if full else [ev for ev in events if int(ev.get("seq") or 0) > last]
            with con:
                if full:
                    con.execute("DELETE FROM events")
                    con.execute("DELETE FROM fts")
                    con.execute("DELETE FROM fts_docs")
                con.executemany(
                    "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(ev.get("seq"), ev.get("ts"), ev.get("type"), ev.get("id"), _dt(ev.get("date")),
                      ev.get("actor"), ev.get("by"), ev.get("prov"), ev.get("source"),
                      json.dumps(ev.get("data") or {}, ensure_ascii=False), _event_class(ev))
                     for ev in new])
                _materialize_entities(con, brain)
                # FTS: entidades sempre; documentos por sha (só o que mudou entra de novo)
                con.execute("DELETE FROM fts WHERE path IS NULL")
                con.executemany("INSERT INTO fts (kind, ref, title, body, date, path) VALUES (?,?,?,?,?,NULL)",
                                [(k, r, t, b or "", d) for k, r, t, b, d, p in _fts_entity_rows(brain)])
                fts_docs = {p: s for p, s in con.execute("SELECT path, sha FROM fts_docs")}
                for kind, rel, title, text, date_, path_, sha in _fts_doc_rows(brain, fts_docs):
                    con.execute("DELETE FROM fts WHERE path = ?", (path_,))
                    con.execute("INSERT INTO fts (kind, ref, title, body, date, path) VALUES (?,?,?,?,?,?)",
                                (kind, rel, title, text, date_, path_))
                    con.execute("INSERT OR REPLACE INTO fts_docs VALUES (?,?)", (path_, sha))
                # documento que saiu do vault (stat barato — sem reler texto)
                for doc in list(fts_docs):
                    if not (brain.inst.vault / doc).exists():
                        con.execute("DELETE FROM fts WHERE path = ?", (doc,))
                        con.execute("DELETE FROM fts_docs WHERE path = ?", (doc,))
                max_seq = max((int(ev.get("seq") or 0) for ev in events), default=0)
                # CAS (R1): last_seq só avança; empatou/perdeu → outro processo passou na frente
                cur = con.execute("SELECT value FROM meta WHERE key='last_seq'").fetchone()
                cur = int(cur[0]) if cur else 0
                if max_seq > cur:
                    con.execute("UPDATE meta SET value = ? WHERE key = 'last_seq' AND CAST(value AS INTEGER) < ?",
                                (str(max_seq), max_seq))
                    now_val = con.execute("SELECT value FROM meta WHERE key='last_seq'").fetchone()
                    if not now_val or int(now_val[0]) < max_seq:   # primeira construção ou alguém na frente (sob flock): grava
                        con.execute("INSERT OR REPLACE INTO meta VALUES ('last_seq', ?)", (str(max_seq),))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('ledger_size', ?)", (str(size),))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('ledger_sha_tail', ?)", (str(tail),))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)",
                            (util.now().isoformat(timespec="seconds"),))
        finally:
            con.close()
    return status(brain)


def rebuild(brain) -> dict:
    path = db_path(brain.inst)
    path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    return update(brain)


def status(brain) -> dict:
    path = db_path(brain.inst)
    if not path.exists():
        return {"ok": False, "detail": "índice ausente — `brain index rebuild`"}
    try:
        with connect(path, ro=True) as con:
            meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
            n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    except sqlite3.Error as e:
        return {"ok": False, "detail": f"índice ilegível: {e}"}
    max_seq = brain.state.max_seq() if callable(getattr(brain.state, "max_seq")) else brain.state.max_seq
    last = int(meta.get("last_seq") or 0)
    return {"ok": last >= max_seq, "last_seq": last, "ledger_seq": max_seq, "events": n,
            "built_at": meta.get("built_at"),
            "detail": "em dia" if last >= max_seq else f"atrasado ({last} < {max_seq}) — rode `brain index update`"}


# ── leitura ─────────────────────────────────────────────────────────────────
def fts_terms(query: str) -> str:
    """Sanitização FTS5 (R2): cada termo entre aspas (aspas internas dobradas),
    prefixo no último. `kind:x` vira busca literal — nunca filtro de coluna."""
    words = [w for w in util.fold(query).split() if w]
    if not words:
        return '""'
    quoted = ['"' + w.replace('"', '""') + '"' for w in words]
    quoted[-1] += "*"
    return " ".join(quoted)


def search_index(brain, query: str, limit: int = 20) -> list[dict] | None:
    """Busca pelo índice (bm25, título 3×). None = sem índice (leitor cai no refold)."""
    path = db_path(brain.inst)
    if not path.exists():
        return None
    terms = [t for t in util.fold(query).split() if len(t) > 1]
    if not terms:
        return []

    def run(expr: str, partial: bool):
        sql = ("SELECT kind, ref, title, date, path, bm25(fts, 3.0, 1.0, 1.0, 0.0, 0.0) AS score "
               "FROM fts WHERE fts MATCH ? ORDER BY score LIMIT ?")
        with connect(path, ro=True) as con:
            return [{"kind": k, "id": r, "title": t, "date": d, "path": p, "score": -s,
                     **({"match": "parcial"} if partial else {})}
                    for k, r, t, d, p, s in con.execute(sql, (expr, limit * 3))]

    hits = run(fts_terms(query), partial=False)
    if not hits and len(terms) > 1:        # AND não achou: refaz termo a termo (OR), deduplicado
        seen: set[str] = set()
        merged = []
        for w in terms:
            for h in run(fts_terms(w), partial=True):
                if h["id"] not in seen:
                    seen.add(h["id"])
                    merged.append(h)
        merged.sort(key=lambda h: -h["score"])
        hits = merged
    return hits[:limit]


def resolve_person(con: sqlite3.Connection, ref: str) -> str | None:
    """id|alias → id da pessoa (tabela aliases)."""
    row = con.execute("SELECT person_id FROM aliases WHERE alias_fold = ?", (util.fold(ref),)).fetchone()
    return row[0] if row else (ref if ref in {r[0] for r in con.execute("SELECT id FROM people")} else None)


def query_actions(con, **f) -> list[dict]:
    sql, args = "SELECT * FROM actions WHERE 1=1", []
    if f.get("open"):
        sql += " AND is_open = 1"
    if f.get("overdue"):
        sql += " AND is_open = 1 AND due IS NOT NULL AND due < date('now', 'localtime')"
    if f.get("due_within") is not None:
        sql += " AND is_open = 1 AND due BETWEEN date('now', 'localtime') AND date('now', ?)"
        args.append(f"+{int(f['due_within'])} day")
    if f.get("person"):
        pid = resolve_person(con, f["person"])
        sql += " AND owner = ?"
        args.append(pid or f["person"])
    if f.get("project"):
        sql += " AND project = ?"
        args.append(f["project"])
    if f.get("list"):
        sql += " AND list = ?"
        args.append(f["list"])
    if f.get("blocked"):
        sql += " AND is_blocked = 1"
    sql += f" ORDER BY (due IS NULL), due LIMIT {int(f.get('limit') or 50)}"
    cols = [c[1] for c in con.execute("PRAGMA table_info(actions)")]
    return [dict(zip(cols, r)) for r in con.execute(sql, args)]


def query_decisions(con, project: str | None = None, person: str | None = None,
                    since: str | None = None, active: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM decisions WHERE 1=1", []
    if project:
        sql += " AND project = ?"
        args.append(project)
    if person:
        sql += " AND id IN (SELECT src FROM edges WHERE rel = 'decided_by' AND dst = ?)"
        args.append(resolve_person(con, person) or person)
    if since:
        sql += " AND date >= ?"
        args.append(since)
    if active:
        sql += " AND status = 'ativa'"
    sql += " ORDER BY date DESC LIMIT 50"
    cols = [c[1] for c in con.execute("PRAGMA table_info(decisions)")]
    return [dict(zip(cols, r)) for r in con.execute(sql, args)]


def query_person(con, ref: str) -> dict | None:
    pid = resolve_person(con, ref)
    if not pid:
        return None
    row = con.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    if not row:
        return None
    cols = [c[1] for c in con.execute("PRAGMA table_info(people)")]
    p = dict(zip(cols, row))
    p["aliases"] = [a[0] for a in con.execute(
        "SELECT alias_fold FROM aliases WHERE person_id = ? AND alias_fold != ?", (pid, util.fold(p["name"])))]
    p["actions_open"] = con.execute(
        "SELECT COUNT(*) FROM actions WHERE owner = ? AND is_open = 1", (pid,)).fetchone()[0]
    p["actions_overdue"] = con.execute(
        "SELECT COUNT(*) FROM actions WHERE owner = ? AND is_open = 1 AND due < date('now', 'localtime')",
        (pid,)).fetchone()[0]
    return p


ENTITY_TABLES = {"TASK": "actions", "DEC": "decisions", "WIN": "deliveries", "PROC": "processes",
                 "OPP": "opportunities", "FB": "feedbacks", "PROP": "proposals", "ASK": "questions"}
PLANNING_KINDS = ("GOAL", "PROJ")


def query_entity(con, eid: str) -> dict | None:
    m = re.match(r"^([A-Z]+)[-]?(\d+(?:\.\d+)?)$", eid.upper())
    if not m:
        return None
    pfx, num = m.group(1), m.group(2)
    if pfx in PLANNING_KINDS:
        row = con.execute("SELECT * FROM planning WHERE id = ?", (eid.upper(),)).fetchone()
        table = "planning"
    else:
        table = ENTITY_TABLES.get(pfx)
        if table:
            row = con.execute(f"SELECT * FROM {table} WHERE id = ?", (eid.upper(),)).fetchone()
        else:
            row = None                                       # MSG/PUB/FOCUS…: sem tabela própria
    if not row and table not in ("planning",):
        # MSG/PUB/FOCUS e afins não têm tabela própria: a ficha mínima vem do próprio evento
        ev = con.execute("SELECT type, ts, date, by, prov, source FROM events WHERE id = ? "
                         "ORDER BY seq DESC LIMIT 1", (eid.upper(),)).fetchone()
        if ev:
            return {"entity": eid.upper(), "found": True, "type": ev[0], "ts": ev[1], "date": ev[2],
                    "by": ev[3], "prov": ev[4], "source": ev[5], "note": "entidade sem tabela própria — último evento"}
    if not row:
        return {"entity": eid.upper(), "found": False}
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
    out = dict(zip(cols, row))
    out.pop("data", None)
    return {"entity": eid.upper(), "found": True, **out}


FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|attach|detach|pragma|create|alter|vacuum|reindex)\b",
                           re.I)


def query_sql(con, stmt: str) -> list[dict]:
    stmt = stmt.strip().rstrip(";")
    if ";" in stmt or FORBIDDEN_SQL.search(stmt) or not stmt.lower().startswith("select"):
        raise util.BrainError("query sql: uma instrução SELECT apenas, sem ; extra (índice é somente-leitura)",
                              code=4)
    cur = con.execute(f"SELECT * FROM ({stmt}) LIMIT {QUERY_LIMIT}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
