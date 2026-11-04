"""Roteador de perguntas por tipo (Fase 2/4 do plano da memória) — o mesmo classificador
para o hook de recall, o /ask e o eval.

Rotas:
  ledger  — pergunta de ESTADO (prazo, atraso, quem deve) ou com ID/título de PROJ/GOAL:
            a resposta é uma conta sobre o ledger, não uma busca semântica. O hook injeta
            até 3 linhas compactas (⟶ ledger/<ID>) e silencia para todo o resto.
Sem índice SQLite: o hook silencia (nada injeta) — nunca bloqueia a mensagem.

O classificador é determinístico (regex + tabelas do índice): zero LLM.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import ids, util

# vocabulário de estado/tempo (pt · es) — sinal de que a pergunta é uma CONTA, não um texto
STATE_WORDS = re.compile(
    r"\b(atrasad\w*|prazo\w*|venc\w*|pendente\w*|pendências?|quem deve|deve ao? mim|bloquead\w*|"
    r"status|quando (?:vence|entrega|fica pronto)|o que falta|falta fazer|em aberto|abertas?|"
    r"fechad\w*|concluíd\w*|progresso|andamento|"
    r"vencid\w*|plazo\w*|pendiente\w*|atrasad\w*|abiert\w*|cerrad\w*|progreso)\b", re.I)

# ID novo ou antigo (A-0146, D-3, G1, P3.2) — o ids.normalize traduz na hora
ID_TOKEN = re.compile(r"\b([A-Za-z]{1,8})-?(\d+(?:\.\d+)?)\b")
NORMAL_ID = re.compile(r"^(TASK|DEC|WIN|PROP|MSG|PUB|FOCUS|PROC|OPP|ASK|FB|GOAL|PROJ)-\d+(\.\d+)?$")


def _find_db() -> Path | None:
    import os
    env = os.environ.get("BRAIN_HOME")
    cands = [Path(env)] if env else []
    here = Path.cwd().resolve()
    cands += [here, *here.parents]
    for cand in cands:
        db = cand / "vault" / "FRESH" / "_index" / "brain.sqlite"
        if db.exists():
            return db
    return None


def classify(question: str, db: Path | None = None) -> dict:
    """{'route': 'ledger'|None, 'ids': [...], 'people': [...], 'why': str}"""
    out: dict = {"route": None, "ids": [], "people": [], "why": ""}
    q = util.fold(question)
    seen_ids: set[str] = set()
    for pre, num in ID_TOKEN.findall(question):
        u = pre.upper()
        if len(u) == 1 and u in "GP":                          # G1 · P3.2: sem traço
            raw = f"{u}{num}"
        else:                                                  # TASK-0146 · A-0146: com traço
            raw = f"{u}-{num}"
        cand = ids.normalize(raw)
        if isinstance(cand, str) and NORMAL_ID.match(cand) and cand not in seen_ids:
            seen_ids.add(cand)
            out["ids"].append(cand)
    if out["ids"]:
        out["route"] = "ledger"
        out["why"] = "ID de entidade na pergunta"
        return out
    if STATE_WORDS.search(question):
        out["route"] = "ledger"
        out["why"] = "vocabulário de estado/tempo"
        return out
    db = db or _find_db()
    if db is None:
        return out
    words = {w for w in re.findall(r"\w{3,}", question)}
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        con.execute("PRAGMA busy_timeout=2000")
        con.execute("PRAGMA query_only=1")
        with con:
            for w in words:
                row = con.execute("SELECT person_id FROM aliases WHERE alias_fold = ?", (util.fold(w),)).fetchone()
                if row:
                    out["people"].append(row[0])
            # títulos de PROJ/GOAL dobrados (R6): título inteiro na pergunta, OU duas palavras
            # distintas da pergunta no título, OU uma palavra longa (≥8) — "galeria" sozinho não basta
            for pid, title, kind in con.execute("SELECT id, title, kind FROM planning WHERE kind IN ('project','goal')"):
                tf = util.fold(title)
                if len(tf) < 6:
                    continue
                in_title = [w for w in words if len(util.fold(w)) >= 5 and util.fold(w) in tf]
                strong = tf in q or len(in_title) >= 2 or any(len(util.fold(w)) >= 8 for w in in_title)
                if strong:
                    out["ids"].append(pid)
                    out["why"] = f"título de {kind} na pergunta"
    except sqlite3.Error:
        return out
    finally:
        if con is not None:
            con.close()
    if out["ids"] or out["people"]:
        out["route"] = "ledger"
    return out


def _fmt(row: dict, fields: list[str]) -> str:
    return " · ".join(str(row.get(f) or "-") for f in fields)


def ledger_lines(question: str, db: Path | None = None, limit: int = 3) -> list[str]:
    """Até `limit` linhas compactas do ledger para a pergunta — silêncio se nada é estado."""
    c = classify(question, db)
    if c["route"] != "ledger":
        return []
    db = db or _find_db()
    if db is None:
        return []
    lines: list[str] = []
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        con.execute("PRAGMA busy_timeout=2000")
        con.execute("PRAGMA query_only=1")
        cols = [r[1] for r in con.execute("PRAGMA table_info(actions)")]
        with con:
            for eid in c["ids"][:limit]:
                pre = re.match(r"^[A-Z]+", eid)
                if not pre:
                    continue
                p = pre.group(0)
                if p == "TASK":
                    row = con.execute("SELECT * FROM actions WHERE id = ?", (eid,)).fetchone()
                    if row:
                        d = dict(zip(cols, row))
                        lines.append(f"{eid} · {d['title']} · {d['status']}"
                                     + (f" · vence {d['due']}" if d.get("due") else "")
                                     + f" · dono {d['owner']} ⟶ ledger/{eid}")
                elif p == "DEC":
                    row = con.execute("SELECT title, date, status FROM decisions WHERE id = ?", (eid,)).fetchone()
                    if row:
                        lines.append(f"{eid} · {row[0]} · {row[2]} · {row[1]} ⟶ ledger/{eid}")
                elif p in ("GOAL", "PROJ"):
                    row = con.execute("SELECT title, status, progress FROM planning WHERE id = ?", (eid,)).fetchone()
                    if row:
                        pct = f"{(row[2] or 0):.0%}" if row[2] is not None else "-"
                        lines.append(f"{eid} · {row[0]} · {row[1]} · progresso {pct} ⟶ ledger/{eid}")
            if len(lines) < limit:
                for pid in dict.fromkeys(c["people"]):
                    overdue = con.execute(
                        "SELECT id, title, due FROM actions WHERE owner = ? AND is_open = 1 "
                        "AND due < date('now', 'localtime') ORDER BY due LIMIT ?",
                        (pid, limit - len(lines))).fetchall()
                    for r in overdue:
                        if len(lines) >= limit:
                            break
                        lines.append(f"{r[0]} · {r[1]} · atrasada (vence {r[2]}) ⟶ ledger/{r[0]}")
            if len(lines) < limit and not c["ids"]:
                for r in con.execute(
                        "SELECT id, title, due FROM actions WHERE is_open = 1 "
                        "AND due < date('now', 'localtime') ORDER BY due LIMIT ?", (limit - len(lines),)):
                    lines.append(f"{r[0]} · {r[1]} · atrasada (vence {r[2]}) ⟶ ledger/{r[0]}")
    except sqlite3.Error:
        return []
    finally:
        if con is not None:
            con.close()
    return lines[:limit]
