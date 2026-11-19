"""Ranqueamento temporal, proveniência e detecção determinística de contradições no recall.

Opera 100% client-side sobre o payload retornado pelo Hindsight (ou mock equivalente),
sem chamadas de rede e sem LLM. Toda data de referência (`today`) é injetável para
testes determinísticos.
"""
from __future__ import annotations

import re
from datetime import date

from . import util

_fold = util.fold

DECAY_CLASSES = frozenset({"estado", "config", "compromisso"})
PERENNIAL_CLASSES = frozenset({"preferencia", "identidade", "decisao"})
_ALL_CLASSES = DECAY_CLASSES | PERENNIAL_CLASSES

# Ordem importa: predicados mais específicos primeiro.
PREDICATE_PATTERNS: dict[re.Pattern[str], str] = {
    re.compile(r"\b(?:prazo|vencimento|data\s+limite|entrega\s+em|due)\b", re.I): "prazo",
    re.compile(r"\b(?:dono|respons[aá]vel|owner|atribu[ií]do\s+a)\b", re.I): "dono",
    re.compile(r"\b(?:status|estado|situa[cç][aã]o|etapa|est[aá]gio|fase)\b", re.I): "status",
    re.compile(r"\b(?:local|endere[cç]o|lugar|sede|unidade|sala)\b", re.I): "local",
    re.compile(r"\b(?:config(?:ura[cç][aã]o)?|modo|engine|modelo|provedor|provider|porta|url|banco)\b", re.I): "config",
    re.compile(r"\b(?:hor[aá]rio|hora(?:s)?|turno|expediente|almo[cç]o|janela)\b", re.I): "horario",
    re.compile(r"\b(?:valor|pre[cç]o|custo|or[cç]amento|limite|teto|meta|peso|nota)\b", re.I): "valor",
}

_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_VALID_PROVS = frozenset({"doc", "observado", "declarado"})
_ENTITY_ID_RE = re.compile(
    r"\b((?:TASK|DEC|WIN|PROP|MSG|PUB|FOCUS|PROC|OPP|ASK|FB)-\d{3,}|GOAL-\d+|PROJ-\d+(?:\.\d+)?)\b",
    re.I,
)
_TAG_ENTITY_RE = re.compile(r"^(?:proj|goal|pessoa|area|proc|opp|task):(.+)$", re.I)

_COLON_VAL_RE = re.compile(r"^\s*(?::|=|->|→)\s*(.+)$")
_COPULA_VAL_RE = re.compile(
    r"^\s*(?:(?:d[oae]s?|n[oae]s?|sobre)\s+[^\s:=→|;]+(?:\s+[^\s:=→|;]+){0,3}\s+)?"
    r"(?:[eé]|eh|foi|ficou(?:\s+em)?|ser[aá]|est[aá](?:\s+em)?|"
    r"passou\s+(?:a\s+ser|para)|mudou\s+para|alterad[oa]\s+para|definid[oa]\s+como)\s+(.+)$",
    re.I,
)
_CLAUSE_END_RE = re.compile(r"(?:\n|;|\||—|\.\s|\.$)")
_PREFIX_STOPWORDS = frozenset({
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem", "sobre", "entre", "ate", "e", "ou", "que",
    "decidimos", "vamos", "precisa", "precisamos", "ficou", "esta", "foi", "tem",
})


def _meta(item: dict) -> dict:
    m = item.get("metadata")
    return m if isinstance(m, dict) else {}


def _tags(item: dict) -> list[str]:
    meta = _meta(item)
    raw = item.get("tags") or meta.get("tags") or []
    return [str(t).strip() for t in raw if t]


def _doc_id(item: dict) -> str | None:
    meta = _meta(item)
    chunk = item.get("chunk") if isinstance(item.get("chunk"), dict) else {}
    for cand in (item.get("document_id"), meta.get("document_id"), chunk.get("document_id")):
        if isinstance(cand, str):
            s = cand.strip()
            if s and s != "?":
                return s
    return None


def _valid_iso_date(val) -> str | None:
    if not val:
        return None
    m = _ISO_DATE_RE.search(str(val))
    if not m:
        return None
    try:
        date.fromisoformat(m.group(1))
        return m.group(1)
    except ValueError:
        return None


def _base_score(item: dict) -> float:
    scores = item.get("scores")
    if isinstance(scores, dict):
        for k in ("semantic", "reranked", "rrf", "score"):
            if scores.get(k) is not None:
                return float(scores[k])
    for k in ("score", "similarity", "weight"):
        if item.get(k) is not None:
            return float(item[k])
    return 1.0


def _item_ref(item: dict, idx: int) -> str:
    meta = _meta(item)
    for cand in (item.get("id"), item.get("document_id"), meta.get("id"), meta.get("document_id")):
        if isinstance(cand, str) and cand.strip() and cand.strip() != "?":
            return cand.strip()
    return f"item-{idx}"


def _item_refs(item: dict) -> set[str]:
    meta = _meta(item)
    refs: set[str] = set()
    for cand in (
        item.get("id"),
        item.get("document_id"),
        meta.get("id"),
        meta.get("fact_id"),
        meta.get("document_id"),
        item.get("text"),
    ):
        if isinstance(cand, str) and cand.strip() and cand.strip() != "?":
            refs.add(cand.strip())
    return refs


def classify_fact(item: dict) -> str:
    """Infere a classe determinística do fato (`estado` por padrão)."""
    meta = _meta(item)
    explicit = _fold(str(meta.get("fact_class") or item.get("fact_class") or ""))
    if explicit in _ALL_CLASSES:
        return explicit

    doc_id = _doc_id(item) or ""
    doc_f = _fold(doc_id)
    tags_f = [_fold(t) for t in _tags(item)]
    text_f = _fold(item.get("text") or "")

    if doc_f.startswith("profile/") or "/profile/" in doc_f:
        if "prefer" in doc_f or "prefer" in text_f or any("prefer" in t for t in tags_f):
            return "preferencia"
        return "identidade"
    if "dec-" in doc_f:
        return "decisao"
    if "task-" in doc_f or "focus-" in doc_f:
        return "compromisso"
    if doc_f.startswith("config/") or "/config/" in doc_f:
        return "config"

    for t in tags_f:
        clean = t.split(":", 1)[-1] if ":" in t else t
        if clean in _ALL_CLASSES:
            return clean
        if t in ("tipo:decisao",):
            return "decisao"
        if t in ("tipo:acao", "tipo:foco"):
            return "compromisso"
        if t in ("tipo:config",):
            return "config"

    if re.search(r"\b(prefir[oa]|prefere|preferencia|gosta de|nao gosta|estilo pessoal)\b", text_f):
        return "preferencia"
    if re.search(r"\b(identidade|perfil|meu papel|cargo:|relacao:)\b", text_f):
        return "identidade"
    if re.search(r"\b(decidimos|decisao|decidido por|ficou decidido)\b", text_f):
        return "decisao"
    if re.search(r"\b(compromisso|combinamos|agendado|reuniao marcada)\b", text_f):
        return "compromisso"
    if re.search(r"\b(configuracao|brain\.toml|recall_hook)\b", text_f):
        return "config"

    return "estado"


def extract_anchor_and_meta(item: dict) -> dict:
    """Extrai `document_id`, `fact_date`, `prov` e `grounded` de um item de recall."""
    meta = _meta(item)
    doc_id = _doc_id(item)
    grounded = bool(doc_id)

    fact_date = None
    for cand in (
        item.get("occurred_start"),
        item.get("date"),
        meta.get("date"),
        meta.get("occurred_start"),
        item.get("mentioned_at"),
        doc_id,
    ):
        fact_date = _valid_iso_date(cand)
        if fact_date:
            break

    prov = None
    for cand in (meta.get("prov"), item.get("prov")):
        cf = _fold(str(cand or ""))
        if cf in _VALID_PROVS:
            prov = cf
            break

    if prov is None:
        for t in _tags(item):
            tf = _fold(t)
            if tf.startswith("prov:"):
                tf = tf.split(":", 1)[1]
            if tf in _VALID_PROVS:
                prov = tf
                break

    if prov is None and doc_id:
        doc_f = _fold(doc_id)
        text_f = _fold(item.get("text") or "")
        if doc_f.startswith(("profile/", "planning/", "config/")) or "/documents/" in doc_f or doc_f.startswith("documents/"):
            prov = "doc"
        elif "/notes/" in doc_f or doc_f.startswith("notes/"):
            prov = "declarado"
        elif doc_f.startswith("ledger/"):
            for p in ("doc", "observado", "declarado"):
                if f"[{p}]" in text_f:
                    prov = p
                    break
            if prov is None:
                prov = "declarado"
        elif doc_f.startswith("raw/") or any(k in doc_f for k in ("/meetings/", "/slack/", "/videos/", "/images/", "/artifacts/")):
            prov = "observado"

    return {
        "document_id": doc_id,
        "fact_date": fact_date,
        "prov": prov or "sem-fonte",
        "grounded": grounded,
    }


def decay_factor(fact_class: str, fact_date: str | None, half_life_days: float, today: date | None = None) -> float:
    """Fator multiplicativo de decaimento exponencial (1.0 para classes perenes ou sem data/meia-vida)."""
    if fact_class in PERENNIAL_CLASSES or not half_life_days or half_life_days <= 0 or not fact_date:
        return 1.0
    ref_today = today or util.today()
    try:
        parsed = date.fromisoformat(fact_date[:10])
    except ValueError:
        return 1.0
    age_days = (ref_today - parsed).days
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / float(half_life_days))


def _match_predicate(text: str) -> str | None:
    for pat, canon in PREDICATE_PATTERNS.items():
        if pat.search(text):
            return canon
    return None


def _trim_value(tail: str) -> str:
    m = _CLAUSE_END_RE.search(tail)
    clause = tail[: m.start()] if m else tail
    clause = clause.strip(" \t\r\n.,:;-")
    return _fold(clause)


def _extract_subject(raw_text: str, pred_start: int, item: dict) -> str:
    m_id = _ENTITY_ID_RE.search(raw_text)
    if m_id:
        return _fold(m_id.group(1))

    for t in _tags(item):
        mt = _TAG_ENTITY_RE.match(t)
        if mt and _fold(mt.group(1)):
            return _fold(mt.group(1))

    meta = _meta(item)
    entities = item.get("entities") or meta.get("entities") or []
    if isinstance(entities, list):
        for ent in entities:
            if isinstance(ent, dict):
                val = _fold(str(ent.get("id") or ent.get("text") or ""))
                if val:
                    return val
            elif isinstance(ent, str) and _fold(ent):
                return _fold(ent)

    prefix = raw_text[:pred_start].strip(" \t:-[]()")
    if prefix:
        tokens = [tok.strip(",.:;[]()") for tok in prefix.split() if tok.strip(",.:;[]()")]
        while tokens and _fold(tokens[0]) in _PREFIX_STOPWORDS:
            tokens.pop(0)
        while tokens and _fold(tokens[-1]) in _PREFIX_STOPWORDS:
            tokens.pop()
        if 1 <= len(tokens) <= 2:
            cand = _fold(" ".join(tokens))
            if len(cand) >= 2 and all(_fold(t) not in _PREFIX_STOPWORDS for t in tokens):
                return cand

    doc_id = _doc_id(item) or ""
    if _fold(doc_id).startswith(("config/", "profile/")):
        return _fold(doc_id)

    return ""


def extract_spv(item: dict) -> tuple[str, str, str]:
    """Extrai `(subject_key, predicate_key, value_key)` deterministicamente sem LLM."""
    meta = _meta(item)
    ms = _fold(str(meta.get("subject") or ""))
    mp = _fold(str(meta.get("predicate") or ""))
    mv = _fold(str(meta.get("value") or ""))
    if ms and mp and mv:
        return (ms, _match_predicate(mp) or mp, mv)

    raw_text = " ".join((item.get("text") or "").split())
    if not raw_text:
        return ("", "", "")

    for pat, canon_pred in PREDICATE_PATTERNS.items():
        for m in pat.finditer(raw_text):
            tail = raw_text[m.end():]
            vm = _COLON_VAL_RE.match(tail) or _COPULA_VAL_RE.match(tail)
            if not vm:
                continue
            val = _trim_value(vm.group(1))
            if not val or len(val) > 120:
                continue
            subj = _extract_subject(raw_text, m.start(), item)
            if not subj or val in (subj, canon_pred):
                continue
            return (subj, canon_pred, val)

    return ("", "", "")


def mark_contradictions(items: list[dict], explicit_supersedes: dict[str, str] | None = None) -> list[dict]:
    """Marca contradições (`vale` / `supercedado`) sem apagar nenhum item."""
    out = [dict(it) for it in items]
    spvs: list[tuple[str, str, str]] = []
    dates: list[str | None] = []
    refs: list[str] = []
    ref_sets: list[set[str]] = []

    for idx, it in enumerate(out):
        it["conflict_status"] = None
        it["superseded_by"] = None
        it["conflict_key"] = None
        spv = extract_spv(it)
        spvs.append(spv)
        dates.append(it.get("fact_date") or extract_anchor_and_meta(it)["fact_date"])
        refs.append(_item_ref(it, idx))
        ref_sets.append(_item_refs(it))

    groups: dict[tuple[str, str], list[int]] = {}
    for idx, (s, p, v) in enumerate(spvs):
        if s and p and v:
            groups.setdefault((s, p), []).append(idx)

    for (s, p), idxs in groups.items():
        distinct_vals = {spvs[i][2] for i in idxs}
        if len(distinct_vals) < 2:
            continue
        ordered = sorted(
            idxs,
            key=lambda i: (1 if dates[i] else 0, dates[i] or "", _base_score(out[i]), -i),
            reverse=True,
        )
        winner_idx = ordered[0]
        winner_val = spvs[winner_idx][2]
        winner_ref = refs[winner_idx]
        ckey = f"{s}:{p}"
        for i in ordered:
            out[i]["conflict_key"] = ckey
            if spvs[i][2] == winner_val:
                out[i]["conflict_status"] = "vale"
                out[i]["superseded_by"] = None
            else:
                out[i]["conflict_status"] = "supercedado"
                out[i]["superseded_by"] = winner_ref

    pairs: list[tuple[str, str]] = []
    for old_ref, new_ref in (explicit_supersedes or {}).items():
        if isinstance(old_ref, str) and old_ref.strip() and isinstance(new_ref, str) and new_ref.strip():
            pairs.append((old_ref.strip(), new_ref.strip()))

    for idx, it in enumerate(out):
        meta = _meta(it)
        sup = meta.get("supersedes") if meta.get("supersedes") is not None else it.get("supersedes")
        targets = sup if isinstance(sup, list) else ([sup] if sup else [])
        for target in targets:
            if isinstance(target, str) and target.strip():
                pairs.append((target.strip(), refs[idx]))

    for old_ref, new_ref in pairs:
        old_idxs = [i for i, rs in enumerate(ref_sets) if old_ref in rs]
        new_idxs = [i for i, rs in enumerate(ref_sets) if new_ref in rs]
        corrector_ref = refs[new_idxs[0]] if new_idxs else new_ref
        for i in old_idxs:
            out[i]["conflict_status"] = "supercedado"
            out[i]["superseded_by"] = corrector_ref
            if not out[i]["conflict_key"]:
                out[i]["conflict_key"] = f"supersedes:{old_ref}"
        for j in new_idxs:
            if out[j]["conflict_status"] != "supercedado":
                out[j]["conflict_status"] = "vale"
                if not out[j]["conflict_key"]:
                    out[j]["conflict_key"] = f"supersedes:{old_ref}"

    return out


def rerank(
    items: list[dict],
    *,
    half_life_days: float = 45,
    today: date | None = None,
    explicit_supersedes: dict[str, str] | None = None,
) -> list[dict]:
    """Enriquece, marca contradições, aplica decaimento seletivo e reordena o recall."""
    ref_today = today or util.today()
    marked = mark_contradictions(items, explicit_supersedes=explicit_supersedes)
    enriched: list[tuple[int, dict]] = []
    for orig_idx, it in enumerate(marked):
        anchor = extract_anchor_and_meta(it)
        fclass = classify_fact(it)
        factor = decay_factor(fclass, anchor["fact_date"], half_life_days, ref_today)
        score_adj = round(_base_score(it) * factor, 6)
        it["document_id"] = anchor["document_id"]
        it["fact_date"] = anchor["fact_date"]
        it["prov"] = anchor["prov"]
        it["fact_class"] = fclass
        it["grounded"] = anchor["grounded"]
        it["decay_factor"] = factor
        it["score_adjusted"] = score_adj
        enriched.append((orig_idx, it))

    enriched.sort(
        key=lambda pair: (
            0 if pair[1]["grounded"] else 1,
            1 if pair[1]["conflict_status"] == "supercedado" else 0,
            -pair[1]["score_adjusted"],
            pair[0],
        )
    )
    return [it for _, it in enriched]


def format_line(item: dict) -> str:
    """Formata item de recall para exibição textual / hook (`[memória · as of ...]` ou `[pista · sem âncora]`)."""
    text = " ".join((item.get("text") or "").split())
    if "grounded" not in item or "prov" not in item or "fact_date" not in item:
        anchor = extract_anchor_and_meta(item)
        grounded = anchor["grounded"]
        fact_date = anchor["fact_date"]
        prov = anchor["prov"]
    else:
        grounded = bool(item.get("grounded"))
        fact_date = item.get("fact_date")
        prov = item.get("prov") or "sem-fonte"

    if not grounded:
        return f"[pista · sem âncora] {text}"

    as_of = fact_date or "sem-data"
    parts = ["memória", f"as of {as_of}", prov]
    cstatus = item.get("conflict_status")
    if cstatus == "vale":
        parts.append("vale")
    elif cstatus == "supercedado":
        parts.append("supercedado")
    return f"[{' · '.join(parts)}] {text}"
