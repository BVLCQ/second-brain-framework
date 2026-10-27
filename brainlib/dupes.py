"""Ações duplicadas: candidatos determinísticos, sem LLM.

O CLI só aponta pares parecidos (radicais do título ponderados pela raridade no ledger, mesmo link, mesmo
entregável/projeto, pessoas em comum). Quem julga se é a mesma coisa é o agente; quem decide é o dono, por
proposta (`descartar-acao` / `unificar-acao`, `--target` = a duplicada, `--into` = a que fica).

Par já julgado não volta: `not_dup` na ação (agente disse "não é", com motivo) ou proposta já feita sobre o par
(aberta, aceita ou rejeitada — rejeitada só volta com evidência nova, e isso é o agente quem traz).
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

from . import util
from .portfolio import STOPWORDS

STRONG = 0.6            # na criação: recusa (código 2) sem --force
CANDIDATE = 0.3         # na varredura: o agente julga cada par a partir daqui
RECENT_CLOSED_DAYS = 30  # na criação, também compara com o que foi fechado há pouco ("já foi feito")
DUP_KINDS = {"descartar-acao", "unificar-acao"}
# verbos genéricos de ação: dizem pouco sobre "o quê"
GENERIC = {"fazer", "ver", "falar", "conversar", "sobre", "pedir", "enviar", "mandar", "checar", "verificar",
           "alinhar", "definir", "criar", "revisar", "time"}
# radicais que dizem a mesma coisa (só equivalências genéricas; nada de nome próprio do dono)
SYNONYMS = {"git": "githu", "monor": "repos", "repo": "repos", "reuni": "encon", "call": "encon", "docs": "docum",
            "plani": "sheet"}
TASK_REF = re.compile(r"\bTASK-\d{4,}\b")


def stems(text: str) -> set[str]:
    """Radicais (5 letras) do título: 'repositório'/'repositorios' e 'onboarding'/'onboard' caem juntos."""
    words = re.findall(r"[a-z0-9]+", util.fold(TASK_REF.sub(" ", text)))
    out = {w[:5] for w in words if w not in STOPWORDS and w not in GENERIC and len(w) > 1 and not w.isdigit()}
    return {SYNONYMS.get(w, w) for w in out}


class Index:
    """Pesos IDF sobre todas as ações do ledger: palavra rara em comum ('bigquery') pesa mais que comum ('reunião')."""

    def __init__(self, actions):
        self.n = 0
        self.df: dict[str, int] = {}
        for a in actions:
            self.n += 1
            for w in stems(a.title):
                self.df[w] = self.df.get(w, 0) + 1

    def w(self, s: str) -> float:
        return math.log((self.n + 1) / (self.df.get(s, 0) + 0.5)) + 0.1

    def score(self, a: dict, b: dict) -> tuple[float, list[str]]:
        """(similaridade 0–1, motivos) entre dois perfis {title, link, project, deliverable, people}."""
        why = []
        if a["link"] and a["link"] == b["link"]:
            return 1.0, [f"mesmo link ({a['link']})"]
        cites = (b.get("id") and b["id"] in TASK_REF.findall(a["title"])) or (a.get("id") and a["id"] in TASK_REF.findall(b["title"]))
        x, y = stems(a["title"]), stems(b["title"])
        union = sum(self.w(s) for s in x | y)
        s = sum(self.w(t) for t in x & y) / union if union else 0.0
        if x & y:
            why.append("título: " + ", ".join(sorted(x & y)))
        if a["deliverable"] and a["deliverable"] == b["deliverable"]:
            s += 0.15
            why.append(f"mesmo entregável {a['deliverable']}")
        elif a["project"] and a["project"] == b["project"]:
            s += 0.1
            why.append(f"mesmo projeto {a['project']}")
        pa, pb = set(a["people"]), set(b["people"])
        if pa and pb:
            if pa & pb:
                s += 0.05
                why.append("pessoas: " + ", ".join(sorted(pa & pb)))
            else:
                s *= 0.5      # "onboarding com Ana" ≠ "onboarding com Bia": vira candidata, não bloqueia
                why.append("pessoas diferentes")
        if cites:
            s += 0.4          # "(ver TASK-0052)" no título: quem escreveu já ligou as duas
            why.append("uma cita a outra no título")
        return round(min(s, 1.0), 2), why


def profile(a) -> dict:
    return {"id": a.id, "title": a.title, "link": a.link or "", "project": a.project or "", "deliverable": a.deliverable or "",
            "people": list(a.people)}


def judged(st) -> set[frozenset]:
    """Pares que já passaram pelo julgamento: `not_dup` nas ações e propostas de duplicata (qualquer status)."""
    out = set()
    for a in st.actions.values():
        for o in a.not_dup:
            out.add(frozenset((a.id, o)))
    for p in st.proposals.values():
        if p.kind in DUP_KINDS and p.target and p.into:
            out.add(frozenset((p.target, p.into)))
    return out


def similar(st, probe: dict, threshold: float = CANDIDATE, limit: int = 5, today: date | None = None) -> list[dict]:
    """Ações parecidas com uma ação que ainda vai nascer: abertas e as fechadas há até 30 dias."""
    today = today or util.today()
    cutoff = today - timedelta(days=RECENT_CLOSED_DAYS)
    idx = Index(st.actions.values())
    skip = set(probe.get("not_dup") or [])
    hits = []
    for a in st.actions.values():
        if a.id in skip:
            continue
        if not a.open and (a.status != "fechada" or not a.closed or a.closed < cutoff):
            continue
        s, why = idx.score(probe, profile(a))
        if s >= threshold:
            hits.append({"id": a.id, "title": a.title, "status": a.status, "list": a.list, "score": s, "why": why})
    hits.sort(key=lambda h: (-h["score"], h["id"]))
    return hits[:limit]


def pairs(st, threshold: float = CANDIDATE) -> list[dict]:
    """Pares de ações abertas parecidas, ainda não julgados, melhores primeiro."""
    idx = Index(st.actions.values())
    seen = judged(st)
    opened = sorted((a for a in st.actions.values() if a.open), key=lambda a: a.id)
    out = []
    for i, a in enumerate(opened):
        pa = profile(a)
        for b in opened[i + 1:]:
            if frozenset((a.id, b.id)) in seen:
                continue
            s, why = idx.score(pa, profile(b))
            if s >= threshold:
                out.append({"a": a.id, "b": b.id, "a_title": a.title, "b_title": b.title, "score": s, "why": why})
    out.sort(key=lambda p: (-p["score"], p["a"], p["b"]))
    return out


def require_checked(ev: dict, st) -> None:
    """Na gravação (CLI e `brain add`), não na revalidação: ação nova parecida demais com outra é recusada.

    Quem cria olha os candidatos e escolhe: é a mesma → não cria (atualiza a existente); é outra → repete com
    `--force` (ou `data.not_dup` no lote), e o par fica marcado como julgado."""
    if ev.get("type") != "action.opened":
        return
    data = ev.get("data") or {}
    hits = [h for h in similar(st, {**profile_from_data(data), "not_dup": data.get("not_dup")}, threshold=STRONG)]
    if not hits:
        return
    lines = "\n".join(f"  {h['id']} ({h['status']}) · {h['title']} · {h['score']:.2f} · {'; '.join(h['why'])}"
                      for h in hits)
    raise util.BrainError(
        f"possível ação duplicada — nada gravado:\n{lines}\n"
        "se for a mesma: não crie; acrescente à existente (`brain action update ID --note … --people …`)\n"
        "se for outra: repita com --force (CLI) ou data.not_dup = [ids] (brain add)", code=2)


def profile_from_data(data: dict) -> dict:
    return {"title": data.get("title", ""), "link": data.get("link") or "", "project": data.get("project") or "",
            "deliverable": data.get("deliverable") or "", "people": list(data.get("people") or [])}
