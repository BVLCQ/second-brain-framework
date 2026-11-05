"""Camada de memória para IA — Hindsight, alimentado SÓ pelo vault (mão única) e reconstruível.

Dois setups (guides/memory.md · guides/plans/memory-setups.md), escolha livre e reversível,
com BANCO ÚNICO `brain` nos dois modos (decisão 8 do dono, 2026-11-05):

  embed · sem LLM em qualquer operação — chunks do vault (conhecimento + RAW) no `bank`,
    sem consolidação nem observações (NO_LLM_CONFIG)
  full · extração de fatos (chave do dono no .env, cloud_llm = true): retain em modo custom
    com contexto de identidades do ledger, observações e consolidação ligadas; RAW sem
    artefato fica retido até o /dump (raw_awaiting_dump = "hold").

document_id = caminho no vault (ou ledger/<ID>): toda lembrança aponta para algo citável.
O vault é a verdade; `brain memory rebuild` apaga o banco e reconstrói do zero. Os nomes
legados de dois bancos (mem_bank/raw_bank) não são lidos: o rebuild os apaga do servidor.
"""
from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import config, model, util

STATE_NAME = ".memory-state.json"
OPS_KEY = "_ops"          # no state: {bank: {doc_id: {ids, sha, ts, tries, failed}}} — rastro dos retains assíncronos
MAX_TRIES = 3             # depois disso o documento deixa de ser reenviado sozinho (o doctor segue avisando)
STUCK_HOURS = 2           # operação em `processing` sem andar há mais que isso é suspeita
RAW_TEXT = {".md", ".txt", ".csv", ".json", ".html", ".htm", ".vtt", ".srt", ".tsv"}
RAW_FILES = {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls", ".odt", ".rtf"}

MEM_MISSION = ("Memória de trabalho de {owner}: goals, projetos, decisões (quem decidiu e quando), ações "
               "(quem deve o quê e até quando), entregas e pessoas. Conteúdo em português do Brasil. "
               "O document_id de cada memória é o caminho do arquivo no vault — cite-o ao responder.")
RETAIN_MISSION = ("Extraia fatos duráveis: decisões e quem decidiu, compromissos com dono e prazo, entregas e "
                  "resultados, mudanças de plano, papéis e preferências observadas das pessoas. Preserve datas, "
                  "nomes e números exatamente. Ignore logística de reunião, cumprimentos e conversa social. "
                  "Escreva cada fato no MESMO idioma do documento de origem (pt-BR, es ou en) — nunca "
                  "traduza; termos internos e citações ficam como no original.")
OBS_MISSION = "Observações são fatos estáveis sobre pessoas, projetos e o modo de trabalho do dono."

# Modo full: instruções da extração custom (Fase 7 do plano) — o contexto de identidades viaja
# no item de retain; a instrução manda usá-lo e nunca inventar nome/ID fora dele.
EXTRACT_INSTRUCTIONS = (
    "Extraia fatos duráveis deste documento: decisões e quem decidiu, compromissos com dono e prazo, "
    "entregas e números, objeções e argumentos, mudanças de plano, preferências. Ignore logística de "
    "reunião, cumprimentos e ruído de transcrição. Use SOMENTE nomes e IDs do bloco CONTEXTO que "
    "acompanha o documento — nunca invente, nunca troque grafias. Preserve datas, números e citações "
    "exatamente como estão. Atribua cada fala a quem falou quando identificado no CONTEXTO. "
    "Escreva cada fato no MESMO idioma do documento de origem (pt-BR, es ou en) — nunca traduza."
)

# Embed: bancos só de embeddings — o retain guarda os trechos como estão e não há consolidação
# nem observações: nada no brain consome `reflect`/observações, e eram elas que mantinham o LLM ocupado.
NO_LLM_CONFIG = {"retain_extraction_mode": "chunks", "enable_auto_consolidation": False, "enable_observations": False}
FULL_CONFIG = {"retain_extraction_mode": "custom", "retain_custom_instructions": EXTRACT_INSTRUCTIONS,
               "enable_auto_consolidation": True, "enable_observations": True}


def mode(mem: dict) -> str:
    """none · embed · full — derivado de [memory] (engine + extract)."""
    if mem.get("engine") != "hindsight":
        return "none"
    return "full" if mem.get("extract") else "embed"


def validate(mem: dict) -> str:
    """Contratos do [memory]. Devolve o modo validado ou levanta BrainError."""
    m = mode(mem)
    if m == "full" and not mem.get("cloud_llm"):
        raise util.BrainError("[memory] extract = true exige cloud_llm = true — a extração envia texto do "
                              "vault à API de LLM do dono (chave no config/.env; plano da memória §4.3). "
                              "Sem chave, use o modo embed", code=4)
    if mem.get("raw_awaiting_dump") not in ("degraded", "hold"):
        raise util.BrainError('[memory] raw_awaiting_dump inválido — use "degraded" (embed) ou "hold" (full)', code=4)
    return m


class Hindsight:
    def __init__(self, url: str, timeout: int = 120, token: str | None = None):
        self.url, self.timeout, self.token = url.rstrip("/"), timeout, token

    def _req(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None,
             ctype: str = "application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Content-Type": ctype}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                txt = r.read().decode() or "{}"
                return json.loads(txt)
        except urllib.error.HTTPError as e:
            raise util.BrainError(f"Hindsight {method} {path} → {e.code}: "
                                  f"{e.read().decode(errors='replace')[:300]}", code=2) from e
        except json.JSONDecodeError as e:
            raise util.BrainError(f"Hindsight {method} {path}: resposta não é JSON ({e})", code=2) from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise util.BrainError(f"Hindsight fora do ar em {self.url} ({e}) — suba o servidor "
                                  f"(guides/memory.md) ou use [memory] engine = \"none\"", code=2) from e

    def _bank(self, bank: str) -> str:
        return f"/v1/default/banks/{urllib.parse.quote(bank)}"

    def health(self) -> dict:
        return self._req("GET", "/health")

    def banks(self) -> dict:
        return self._req("GET", "/v1/default/banks")

    def version(self) -> dict:
        return self._req("GET", "/version")

    def put_bank(self, bank: str, body: dict) -> dict:
        return self._req("PUT", self._bank(bank), body)

    def patch_config(self, bank: str, updates: dict) -> dict:
        return self._req("PATCH", self._bank(bank) + "/config", {"updates": updates})

    def delete_bank(self, bank: str) -> dict:
        return self._req("DELETE", self._bank(bank))

    def retain(self, bank: str, items: list[dict], async_: bool = True) -> dict:
        return self._req("POST", self._bank(bank) + "/memories", {"items": items, "async": async_})

    def retain_file(self, bank: str, path: Path, meta: dict) -> dict:
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        request = json.dumps({"files_metadata": [meta]})
        # nome de arquivo do dono pode ter aspas/quebra de linha: cru, quebraria o cabeçalho multipart
        fname = path.name.replace("\\", "_").replace('"', "%22").replace("\r", " ").replace("\n", " ")
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n\r\n{request}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{fname}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return self._req("POST", self._bank(bank) + "/files/retain", raw=b"".join(parts),
                         ctype=f"multipart/form-data; boundary={boundary}")

    def recall(self, bank: str, query: str, tags: list[str] | None = None, budget: str = "mid") -> dict:
        body: dict = {"query": query, "budget": budget, "include": {"chunks": {"max_tokens": 2000}}}
        if tags:
            body["tags"] = tags
        return self._req("POST", self._bank(bank) + "/memories/recall", body)

    def reflect(self, bank: str, query: str, tags: list[str] | None = None, budget: str = "mid") -> dict:
        body: dict = {"query": query, "budget": budget}
        if tags:
            body["tags"] = tags
        return self._req("POST", self._bank(bank) + "/reflect", body)

    def stats(self, bank: str) -> dict:
        return self._req("GET", self._bank(bank) + "/stats")

    def operation(self, bank: str, op_id: str) -> dict:
        return self._req("GET", self._bank(bank) + f"/operations/{urllib.parse.quote(op_id)}")

    def delete_document(self, bank: str, doc_id: str) -> dict:
        return self._req("DELETE", self._bank(bank) + "/documents/" + urllib.parse.quote(doc_id, safe=""))

    def health_llm(self, bank: str) -> dict:
        """Valida o LLM por operação sem gastar retain (porta do modo full)."""
        return self._req("POST", self._bank(bank) + "/health/llm", {})

    def llm_stats(self, bank: str) -> dict:
        return self._req("GET", self._bank(bank) + "/llm-requests/stats")

    def operations(self, bank: str, status: str, page: int = 100, max_pages: int = 20) -> list[dict]:
        """Todas as operações com esse status (pagina; o servidor limita `limit`)."""
        out: list[dict] = []
        for i in range(max_pages):
            res = self._req("GET", self._bank(bank) + "/operations?" + urllib.parse.urlencode(
                {"status": status, "limit": page, "offset": i * page}))
            out += res.get("operations", [])
            if len(out) >= res.get("total", 0) or not res.get("operations"):
                break
        return out


def client(brain) -> Hindsight:
    mem = brain.inst.cfg["memory"]
    env = config.load_env(brain.inst)
    return Hindsight(mem["url"], mem["timeout_s"], env.get("HINDSIGHT_API_TOKEN") or None)


# ── documentos que o vault oferece à memória ────────────────────────────────
_STAMP_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})(?:T\d{6})?\.")     # carimbo no nome: …-2026-10-19.md / …-2026-10-19T182906.md
_HEADER_DATE_RE = re.compile(r"^(?:capturado|criada|data):\s*(\d{4}-\d{2}-\d{2})", re.M)
MAX_CONTEXT_ALIASES = 3        # R8: só nome canônico + aliases principais no contexto; completos ficam no /aliases


def _fold(s: str) -> str:
    return (s or "").casefold().strip()


def _raw_parts(rel: str) -> list[str]:
    """Partes de um caminho RAW sem o prefixo: [ano, mês, tipo, …]."""
    parts = list(Path(rel).parts)
    return parts[1:] if parts and parts[0] == "RAW" else parts


def _alias_index(brain) -> tuple[list[dict], list[dict]]:
    """Pessoas (nome + aliases) e projetos (id + título) para casamento literal, sem LLM."""
    st = brain.state
    ppl = []
    for p in st.people.values():
        names = [_fold(a) for a in ([p.name] + list(p.aliases)) if a and _fold(a)]
        ppl.append({"id": p.id, "name": p.name, "folds": sorted(set(names), key=len, reverse=True)})
    projs = [{"id": pr.id, "name": pr.title,
              "folds": sorted({_fold(pr.id), _fold(pr.title)}, key=len, reverse=True)}
             for pr in brain.plan.projects.values() if pr.status != "cancelado"]
    return ppl, projs


def _raw_date(path: Path, rel: str, st) -> str | None:
    """Data do mundo de um RAW (ordem do plano §3.2): artefato → carimbo no nome →
    cabeçalho `capturado:`/`criada:` → primeiro dia do RAW/<ano>/<mês>/."""
    art_id = st.raw_index.get(rel)
    if art_id and st.artifacts.get(art_id) and st.artifacts[art_id].date:
        return st.artifacts[art_id].date.isoformat()
    m = _STAMP_RE.search(path.name)
    if m:
        return m.group(1)
    if path.suffix.lower() in RAW_TEXT:
        m = _HEADER_DATE_RE.search(path.read_text(encoding="utf-8", errors="replace")[:800])
        if m:
            return m.group(1)
    parts = _raw_parts(rel)
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}-{parts[1]}-01"
    return None


def _identity_block(art, ppl_idx, projs_idx, text_fold: str) -> tuple[str, list[dict]]:
    """(contexto de identidades, entidades anexadas por casamento de alias no texto) — modo full."""
    person_ids = list(getattr(art, "people", []) or []) if art else []
    project_ids = list(getattr(art, "projects", []) or []) if art else []
    lines, entities = [], []
    for p in ppl_idx:
        hit = p["id"] in person_ids or any(f and f in text_fold for f in p["folds"])
        if not hit:
            continue
        aliases = ", ".join(a for a in p["folds"][:MAX_CONTEXT_ALIASES]) or "—"
        lines.append(f"- pessoa: {p['name']} (id {p['id']}; grafias: {aliases})")
        entities.append({"name": p["name"], "type": "PERSON", "id": p["id"]})
    for pr in projs_idx:
        if pr["id"] in project_ids or any(f and f in text_fold for f in pr["folds"]):
            lines.append(f"- projeto: {pr['name']} ({pr['id']})")
            entities.append({"name": pr["name"], "type": "PROJECT", "id": pr["id"]})
    return ("\n".join(lines) or "—"), entities


def documents(brain) -> list[dict]:
    inst, st = brain.inst, brain.state
    mem_cfg = inst.cfg["memory"]
    m = validate(mem_cfg)
    single = m == "full"
    exclude = set(mem_cfg.get("exclude_types") or [])
    hold = single and mem_cfg.get("raw_awaiting_dump") == "hold"
    max_bytes = mem_cfg["max_file_mb"] * 2**20
    ppl_idx, projs_idx = (_alias_index(brain) if single else ([], []))
    docs: list[dict] = []
    art_by_path = st.artifacts
    for path in sorted(inst.processed.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/*.md")):
        rel = inst.rel(path)
        art = art_by_path.get(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        tags = ["tipo:" + (art.kind if art else "artefato")]
        if art:
            tags += [f"proj:{p}" for p in art.projects] + [f"pessoa:{p}" for p in art.people]
        docs.append({"bank": "mem", "id": rel, "text": text,
                     "date": art.date.isoformat() if art and art.date else None, "tags": tags, "art": art})
    for rel in ("PLANNING/goals.md", "PLANNING/log.md", "PROFILE/profile.md"):
        p = inst.vault / rel
        if p.exists():
            docs.append({"bank": "mem", "id": rel, "text": p.read_text(encoding="utf-8"), "date": None,
                         "tags": ["tipo:planejamento" if rel.startswith("PLANNING") else "tipo:perfil"], "art": None})
    for doc_id, text, date, tags in _entity_docs(brain):
        docs.append({"bank": "mem", "id": doc_id, "text": text, "date": date, "tags": tags, "art": None})
    raw = inst.vault / "RAW"
    for path in sorted(raw.rglob("*")) if raw.exists() else []:
        if not path.is_file() or "inbox" in path.relative_to(raw).parts or path.name.startswith("."):
            continue
        rel = inst.rel(path)
        parts = _raw_parts(rel)
        if len(parts) >= 3 and parts[2] in exclude:      # RAW/<ano>/<mês>/<tipo>/ — §3.2: connectors/github não vão
            continue
        art_id = st.raw_index.get(rel)
        art = st.artifacts.get(art_id) if art_id else None
        if hold and art is None:
            continue        # full + hold: RAW sem /dump não nasce sem identidade (Fase 7)
        ext = path.suffix.lower()
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="replace") if ext in RAW_TEXT and size <= max_bytes else None
        if text is None and not (ext in RAW_FILES and size <= max_bytes):
            continue
        tags = ["tipo:raw", f"ext:{ext[1:]}"] + ([f"artefato:{art.id}"] if art else [])
        d = {"bank": "mem", "id": rel, "date": _raw_date(path, rel, st), "tags": tags, "art": art}
        if text is not None:
            d["text"] = text
        else:
            # RAW é imutável: tamanho+mtime bastam para detectar mudança sem reler binários a cada render
            d["file"] = path
            d["sha"] = f"{size}:{int(path.stat().st_mtime)}"
        docs.append(d)
    for d in docs:
        d.setdefault("sha", util.sha(d.get("text", "")))
        if single:
            block, entities = _identity_block(d.get("art"), ppl_idx, projs_idx, _fold(d.get("text", "")))
            head = f"{d['id']}"
            if d.get("date"):
                head += f" · data: {d['date']}"
            d["context"] = f"CONTEXTO\n{head}\n{block}"
            if entities:
                d["entities"] = entities
    return docs


def awaiting_dump(brain) -> list[str]:
    """RAW arquivado sem artefato — no full+hold fica retido até o /dump (Fase 7)."""
    inst, st = brain.inst, brain.state
    mem_cfg = inst.cfg["memory"]
    if not (mode(mem_cfg) == "full" and mem_cfg.get("raw_awaiting_dump") == "hold"):
        return []
    exclude = set(mem_cfg.get("exclude_types") or [])
    raw = inst.vault / "RAW"
    out = []
    for path in sorted(raw.rglob("*")) if raw.exists() else []:
        if not path.is_file() or "inbox" in path.relative_to(raw).parts or path.name.startswith("."):
            continue
        rel = inst.rel(path)
        parts = _raw_parts(rel)
        if len(parts) >= 3 and parts[2] in exclude:
            continue
        if rel not in st.raw_index:
            out.append(rel)
    return out


def _entity_docs(brain) -> list[tuple[str, str, str, list[str]]]:
    """(doc_id, texto, data, tags) — uma página por ação/decisão/entrega/pessoa/projeto."""
    m = model.build(brain)
    out = []
    for a in m["actions"]:
        lines = [f"Ação {a['id']} — {a['title']}",
                 f"Dono: {a['owner_name']} · lista: {a['list']} · estado: {a['status']}"
                 + (f" · prazo: {a['due']}" if a["due"] else "")
                 + (f" · projeto: {a['project']} {a['project_title']}" if a["project"] else ""),
                 f"Origem: {a['source_label']} [{a['prov']}]", "Histórico:"]
        lines += [f"- {h['date']} {h['type']}: {h['note']} ({h['by']})" for h in a["history"]]
        if a["outcome"]:
            lines.append(f"Resultado: {a['outcome']}")
        tags = ["tipo:acao", f"lista:{a['list']}", f"pessoa:{a['owner']}"] + \
            ([f"proj:{a['project']}"] if a["project"] else [])
        out.append((f"ledger/{a['id']}", "\n".join(lines), a["closed"] or a["opened"], tags))
    for d in m["decisions"]:
        lines = [f"Decisão {d['id']} ({d['date']}) — {d['title']}",
                 f"Decidido por: {', '.join(d['decided_by_names'])} · estado: {d['status']}"
                 + (f" · projeto: {d['project']} {d['project_title']}" if d["project"] else "")]
        if d["context"]:
            lines.append(f"Contexto: {d['context']}")
        if d["rationale"]:
            lines.append(f"Por quê: {d['rationale']}")
        if d["superseded_by"]:
            lines.append(f"Substituída por {d['superseded_by']}")
        lines.append(f"Fonte: {d['source_label']} — {d['source']} [{d['prov']}]")
        tags = ["tipo:decisao"] + [f"pessoa:{p}" for p in d["decided_by"]] + \
            ([f"proj:{d['project']}"] if d["project"] else [])
        out.append((f"ledger/{d['id']}", "\n".join(lines), d["date"], tags))
    for e in m["deliveries"]:
        text = (f"Entrega {e['id']} ({e['date']}) — {e['title']}\nResultado: {e['result']}"
                + (f"\nImpacto: {e['impact']}" if e["impact"] else "") + f"\nFonte: {e['source_label']} [{e['prov']}]")
        out.append((f"ledger/{e['id']}", text, e["date"], ["tipo:entrega"] + ([f"proj:{e['project']}"] if e["project"] else [])))
    for p in m["people"]:
        text = (f"Pessoa: {p['name']} (id {p['id']}) · aliases: {', '.join(p['aliases']) or '—'}\n"
                f"Papel: {p['role'] or '—'} · relação: {p['relation'] or '—'} · e-mail: {p['email'] or '—'}")
        out.append((f"ledger/person/{p['id']}", text, None, ["tipo:pessoa", f"pessoa:{p['id']}"]))
    return out


def _state_path(brain) -> Path:
    return brain.inst.config_dir / STATE_NAME


# Bancos só de embeddings: o retain guarda os trechos como estão e não há consolidação nem observações —
# nada no brain consome `reflect`/observações, e eram elas que mantinham o LLM local ocupado.
NO_LLM_CONFIG = {"retain_extraction_mode": "chunks", "enable_auto_consolidation": False, "enable_observations": False}


def pending(brain) -> list[dict]:
    state = util.read_json(_state_path(brain), {})
    return [d for d in documents(brain) if state.get(d["bank"], {}).get(d["id"]) != d["sha"]]


def setup(brain, hs: Hindsight | None = None, mode_: str | None = None) -> list[str]:
    """Cria/configura o banco único do modo vigente (ou do modo pedido). embed = chunks
    (zero LLM); full = extração custom + observações. Banco único nos dois modos (decisão 8)
    — mem_bank/raw_bank são legados, apagados do servidor pelo rebuild."""
    hs = hs or client(brain)
    mem = brain.inst.cfg["memory"]
    m = mode_ or validate(mem)
    if m not in ("embed", "full"):
        raise util.BrainError(f"modo de memória inválido: {m!r} — use embed ou full", code=4)
    if m == "full":
        validate({**mem, "extract": True})         # contratos do full valem aqui também (cloud_llm do config)
        hs.put_bank(mem["bank"], {"name": "Segundo Cérebro — conhecimento (full)",
                                  "mission": MEM_MISSION.format(owner=brain.inst.cfg["owner"]["name"]),
                                  "retain_mission": RETAIN_MISSION, "observations_mission": OBS_MISSION})
        hs.patch_config(mem["bank"], FULL_CONFIG)
    else:
        hs.put_bank(mem["bank"], {"name": "Segundo Cérebro — conhecimento (chunks)",
                                  "mission": MEM_MISSION.format(owner=brain.inst.cfg["owner"]["name"]),
                                  "retain_mission": RETAIN_MISSION})
        hs.patch_config(mem["bank"], NO_LLM_CONFIG)
    return [mem["bank"]]


def _op_ids(res: dict) -> list[str]:
    """IDs das operações assíncronas que o servidor abriu (retain: operation_id[s]; arquivo: operation_ids)."""
    ids = [i for i in (res.get("operation_ids") or []) if isinstance(i, str)]
    first = res.get("operation_id")
    if isinstance(first, str) and first not in ids:
        ids.insert(0, first)
    return ids


def _banks(brain) -> dict[str, str]:
    return {"mem": brain.inst.cfg["memory"]["bank"]}   # banco único (decisão 8): embed e full


def _shadow_delete(brain, hs, state: dict) -> list[str]:
    """Deleção sombra (§3.3): documento que saiu de documents() sai também do banco."""
    current = {key: {d["id"] for d in documents(brain) if d["bank"] == key} for key in _banks(brain)}
    removed = []
    for key, bank in _banks(brain).items():
        done = state.setdefault(key, {})
        for doc in sorted(set(done) - current[key]):
            try:
                hs.delete_document(bank, doc)
            except util.BrainError as e:
                if "404" not in str(e):
                    continue        # sem servidor agora: continua pendente na próxima varredura
            done.pop(doc, None)
            state.get(OPS_KEY, {}).get(key, {}).pop(doc, None)
            removed.append(f"{key}:{doc}")
    return removed


def failed_docs(hs: Hindsight, bank: str) -> dict[str, dict]:
    """document_id → última operação falha, só dos documentos cuja ÚLTIMA tentativa falhou.

    Falha antiga já superada por um retain posterior (concluído, pendente ou em andamento) não conta."""
    failed = [o for o in hs.operations(bank, "failed") if o.get("document_id") and o.get("created_at")]
    if not failed:
        return {}
    latest_ok: dict[str, datetime] = {}
    for status in ("completed", "pending", "processing"):
        for o in hs.operations(bank, status):
            if o.get("document_id") and o.get("created_at"):
                t = util.parse_dt(o["created_at"])
                latest_ok[o["document_id"]] = max(latest_ok.get(o["document_id"], t), t)
    out: dict[str, dict] = {}
    for o in failed:
        doc, t = o["document_id"], util.parse_dt(o["created_at"])
        if t >= latest_ok.get(doc, t) and (doc not in out or t >= util.parse_dt(out[doc]["created_at"])):
            out[doc] = o
    return out


def stuck_ops(hs: Hindsight, bank: str) -> list[dict]:
    """Operações em `processing` sem atualização há mais de STUCK_HOURS."""
    limit = util.now() - timedelta(hours=STUCK_HOURS)
    return [o for o in hs.operations(bank, "processing")
            if (o.get("updated_at") or o.get("created_at")) and util.parse_dt(o.get("updated_at") or o["created_at"]) < limit]


def reconcile(brain, hs: Hindsight, state: dict) -> dict:
    """Confere os retains assíncronos já aceitos e tira do estado os que falharam (viram pendentes de novo).

    1) operações que nós abrimos (state[_ops]) são consultadas uma a uma até assentarem;
    2) rede de segurança: falhas no servidor sem rastro nosso (estado antigo; retain de arquivo, onde
       a falha é de uma operação filha) pelo `status=failed`. Depois de MAX_TRIES reenvios, desiste e avisa."""
    dropped, gave_up = [], []
    ops = state.setdefault(OPS_KEY, {})
    for key, bank in _banks(brain).items():
        tracked, done = ops.setdefault(key, {}), state.setdefault(key, {})
        bad: set[str] = set()
        for doc, t in list(tracked.items()):
            if t.get("failed"):
                continue  # já retirado do estado; espera o reenvio
            statuses = [hs.operation(bank, i).get("status") for i in t.get("ids", [])]
            if "failed" in statuses:
                bad.add(doc)
            elif not any(x in ("pending", "processing") for x in statuses):
                del tracked[doc]  # tudo concluído (ou o servidor já esqueceu): nada mais a vigiar
        bad |= {doc for doc in failed_docs(hs, bank) if doc in done}
        for doc in sorted(bad):
            t = tracked.setdefault(doc, {"ids": [], "sha": done.get(doc), "tries": 0})
            if t.get("tries", 0) >= MAX_TRIES:
                gave_up.append(f"{key}:{doc}")
                continue
            done.pop(doc, None)
            t["failed"] = True
            dropped.append(f"{key}:{doc}")
    return {"dropped": dropped, "gave_up": gave_up}


def sync(brain, limit: int | None = None, dry_run: bool = False, hs: Hindsight | None = None) -> dict:
    if dry_run:
        todo = pending(brain)[:limit] if limit else pending(brain)
        return {"would_send": [f"{d['bank']}:{d['id']}" for d in todo], "sent": 0}
    hs = hs or client(brain)
    banks = _banks(brain)
    state = util.read_json(_state_path(brain), {})
    sent, errors = 0, []
    try:
        rec = reconcile(brain, hs, state)
    except util.BrainError as e:
        if "fora do ar" in str(e):
            return {"sent": 0, "errors": [str(e)], "remaining": len(pending(brain)), "resent": [], "gave_up": []}
        rec = {"dropped": [], "gave_up": []}
        errors.append(f"conferência das operações: {e}")
    util.write_json(_state_path(brain), state)  # o que falhou já volta a ser pendente
    try:
        removed = _shadow_delete(brain, hs, state)
        util.write_json(_state_path(brain), state)
    except util.BrainError as e:
        if "fora do ar" in str(e):
            return {"sent": 0, "errors": [str(e)], "remaining": len(pending(brain)), "resent": [], "gave_up": []}
        removed = []
        errors.append(f"deleção sombra: {e}")
    todo = pending(brain)
    if limit:
        todo = todo[:limit]
    tracked_all = state.setdefault(OPS_KEY, {})
    for d in todo:
        meta = {"document_id": d["id"], "tags": d["tags"], "metadata": {"vault_path": d["id"]}}
        if d.get("entities"):
            # 1.2.0: valores do metadata de retain precisam ser strings — entities viaja como JSON
            meta["metadata"]["entities"] = json.dumps(d["entities"], ensure_ascii=False)
        if d.get("date"):
            meta["timestamp"] = f"{d['date']}T12:00:00"
        try:
            if "file" in d:
                res = hs.retain_file(banks[d["bank"]], d["file"], meta)
            else:
                res = hs.retain(banks[d["bank"]], [{"content": d["text"], "context": d.get("context") or d["id"], **meta}])
        except util.BrainError as e:
            errors.append(f"{d['id']}: {e}")
            if "fora do ar" in str(e):
                break
            continue
        state.setdefault(d["bank"], {})[d["id"]] = d["sha"]
        tracked = tracked_all.setdefault(d["bank"], {})
        prev = tracked.get(d["id"])
        tries = prev.get("tries", 0) + 1 if prev and prev.get("failed") and prev.get("sha") == d["sha"] else 0
        ids = _op_ids(res if isinstance(res, dict) else {})
        if ids or tries:
            tracked[d["id"]] = {"ids": ids, "sha": d["sha"], "ts": util.now().isoformat(timespec="seconds"),
                                "tries": tries}
        else:
            tracked.pop(d["id"], None)
        sent += 1
        if sent % 20 == 0:
            util.write_json(_state_path(brain), state)
    util.write_json(_state_path(brain), state)
    return {"sent": sent, "errors": errors, "remaining": len(pending(brain)),
            "resent": rec["dropped"], "gave_up": rec["gave_up"]}


def rebuild(brain, limit: int | None = None, dry_run: bool = False) -> dict:
    if dry_run:
        return sync(brain, limit, dry_run=True)
    hs = client(brain)
    mem = brain.inst.cfg["memory"]
    for bank in dict.fromkeys((mem["mem_bank"], mem["raw_bank"], mem["bank"])):   # troca de modo não herda lixo
        try:
            hs.delete_bank(bank)
        except util.BrainError as e:
            if "404" not in str(e):
                raise
    _state_path(brain).unlink(missing_ok=True)
    setup(brain, hs)
    return sync(brain, limit, hs=hs)


def op_problems(brain, hs: Hindsight | None = None) -> dict:
    """Retains assíncronos com problema. Sem servidor (hs=None) só o que o último sync/reconcile registrou."""
    state = util.read_json(_state_path(brain), {})
    failed, gave_up, stuck = set(), set(), []
    for key, tracked in state.get(OPS_KEY, {}).items():
        for doc, t in tracked.items():
            if t.get("failed"):
                failed.add(f"{key}:{doc}")
            elif t.get("tries", 0) >= MAX_TRIES:
                gave_up.add(f"{key}:{doc}")
    if hs is not None:
        mine = {(d["bank"], d["id"]) for d in documents(brain)}
        for key, bank in _banks(brain).items():
            # só documentos que ainda existem no vault — falha de documento removido não é acionável
            failed |= {f"{key}:{doc}" for doc in failed_docs(hs, bank) if (key, doc) in mine}
            stuck += [{"bank": bank, "id": o.get("id"), "doc": o.get("document_id")} for o in stuck_ops(hs, bank)]
    failed -= gave_up
    return {"failed": sorted(failed), "gave_up": sorted(gave_up), "stuck": stuck}


def _problems_text(p: dict) -> str:
    out = []
    if p["failed"]:
        out.append(f"{len(p['failed'])} documentos com retain falho no Hindsight ({', '.join(p['failed'][:3])}"
                   f"{'…' if len(p['failed']) > 3 else ''}) — rode `brain memory sync` para reenviar")
    if p["gave_up"]:
        out.append(f"{len(p['gave_up'])} documentos falharam mesmo após {MAX_TRIES} reenvios "
                   f"({', '.join(p['gave_up'][:3])}) — veja os logs do servidor")
    if p["stuck"]:
        out.append(f"{len(p['stuck'])} operações em processamento há mais de {STUCK_HOURS}h "
                   f"(ex.: {p['stuck'][0]['doc'] or p['stuck'][0]['id']})")
    return " · ".join(out)


def queue(brain, hs: Hindsight) -> dict:
    """Fila de trabalho do Hindsight por banco: o que está usando (ou vai usar) o LLM/embedding agora."""
    out = {}
    for key, bank in _banks(brain).items():
        st = hs.stats(bank)
        by_type: dict[str, dict[str, int]] = {}
        for status_ in ("processing", "pending"):
            for o in hs.operations(bank, status_):
                t = o.get("operation_type") or "?"
                by_type.setdefault(t, {"processing": 0, "pending": 0})[status_] += 1
        # Backlog sem operação de consolidação = consolidação desligada (NO_LLM_CONFIG): não é trabalho em curso.
        backlog = int(st.get("pending_consolidation") or 0) if "consolidation" in by_type else 0
        out[bank] = {"ops": by_type,
                     "pending_consolidation": backlog,
                     "failed_consolidation": int(st.get("failed_consolidation") or 0)}
    return out


def _queue_text(q: dict) -> str:
    parts, busy = [], False
    for bank, b in q.items():
        ops = [f"{t} {c['processing']} rodando" + (f" + {c['pending']} na fila" if c["pending"] else "")
               if c["processing"] else f"{t} {c['pending']} na fila"
               for t, c in sorted(b["ops"].items())]
        if b["pending_consolidation"]:
            ops.append(f"{b['pending_consolidation']} memórias aguardando consolidação")
        busy |= bool(ops)
        parts.append(f"{bank}: {', '.join(ops) if ops else 'ociosa'}")
    head = "fila: ocupada — LLM/embedding em uso" if busy else "fila: vazia — LLM livre"
    return head + " (" + " · ".join(parts) + ")"


# ── fresnness do servidor (plano memory-harness-wizard.md, Fase 3) ────────────
VERSION_CACHE = ".hindsight-check.json"     # em FRESH/ (derivado): última versão upstream
RELEASES_URL = "https://api.github.com/repos/vectorize-io/hindsight/releases/latest"
RELEASE_MAX_AGE_H = 24


def _read_version_cache(inst) -> dict:
    from . import util as _u
    p = inst.fresh / VERSION_CACHE
    if not p.exists():
        return {}
    try:
        return _u.read_json(p, {})
    except Exception:                                  # noqa: BLE001 — cache corrompido = sem cache
        return {}


def refresh_release_cache(inst) -> dict:
    """Busca a última versão do Hindsight upstream (≤1×/dia) e grava o cache em FRESH/.
    Alimentada pelo doctor online e pelo noturno; o status só LÊ. Nunca falha."""
    from . import util as _u
    cache = _read_version_cache(inst)
    ts = cache.get("checked_at")
    if ts:
        try:
            if (_u.now() - _u.parse_dt(ts)).total_seconds() < RELEASE_MAX_AGE_H * 3600:
                return cache
        except Exception:                              # noqa: BLE001
            pass
    out = {"checked_at": _u.now().isoformat(timespec="seconds")}
    try:
        req = urllib.request.Request(RELEASES_URL, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "segundo-cerebro"})
        with urllib.request.urlopen(req, timeout=10) as r:
            tag = (json.loads(r.read().decode()) or {}).get("tag_name") or ""
        out.update(latest=tag.lstrip("v"), stale=False)
    except Exception:                                  # noqa: BLE001 — offline é estado normal
        out.update(latest=cache.get("latest", ""), stale=True)
    try:
        _u.write_json(inst.fresh / VERSION_CACHE, out)
    except Exception:                                  # noqa: BLE001 — FRESH/ pode não existir ainda
        pass
    return out


def version_check(brain, hs: Hindsight) -> dict | None:
    """Servidor vs upstream — INFORMAÇÃO, nunca bloqueio (plano §4.4).

    None = sem como saber (servidor sem /version e sem cache). Sem rede aqui:
    a última versão vem do cache; quem o alimenta é o `refresh_release_cache`."""
    from .upstream import _vkey
    try:
        server = (hs.version() or {}).get("api_version") or ""
    except util.BrainError:
        return None
    latest = (_read_version_cache(brain.inst) or {}).get("latest") or ""
    if not latest:
        return {"server": server, "latest": "", "behind": False}
    return {"server": server, "latest": latest, "behind": _vkey(latest) > _vkey(server)}


def status(brain, online: bool = False, hs: Hindsight | None = None) -> dict:
    mem = brain.inst.cfg["memory"]
    if mem["engine"] != "hindsight":
        return {"level": "ok", "detail": "desligada ([memory] engine = \"none\") — /ask usa índice → artefato → RAW", "mode": "none"}
    m = mode(mem)
    n = len(pending(brain))
    detail = f"modo {m} · Hindsight em {mem['url']} · {n} documentos do vault ainda não enviados"
    if m == "full":
        hold = awaiting_dump(brain)
        detail += f" · {len(hold)} RAW aguardando /dump (hold)" if hold else " · nenhum RAW retido"
    warn = n > 50
    if warn:
        detail += " — rode `brain memory sync`"
    try:
        if online:
            hs = hs or client(brain)
            hs.health()
            detail += " · servidor no ar"
            legacy = sorted({b.get("bank_id") for b in hs.banks().get("banks", [])}
                            & {mem["mem_bank"], mem["raw_bank"]} - {mem["bank"]})
            if legacy:
                detail += (f" · ⚠ bancos legados no servidor ({', '.join(legacy)})"
                           " — brain memory rebuild consolida no banco único")
            vc = version_check(brain, hs)
            if vc and vc.get("latest"):
                detail += (f" · ⚠ servidor {vc['server']} < Hindsight {vc['latest']} — guides/memory.md §Atualizar o Hindsight"
                           if vc.get("behind") else f" · servidor {vc['server']} (última)")
        problems = op_problems(brain, hs if online else None)
        q = queue(brain, hs) if online else None
    except util.BrainError as e:
        return {"level": "error", "detail": str(e)}
    text = _problems_text(problems)
    failed_cons = {b: v["failed_consolidation"] for b, v in (q or {}).items() if v["failed_consolidation"]}
    if failed_cons:
        text = " · ".join(filter(None, [text, "memórias que desistiram da consolidação: " + ", ".join(
            f"{b} {n}" for b, n in failed_cons.items())
            + " — POST /v1/default/banks/<banco>/consolidation/recover recoloca na fila"]))
    if text:
        detail += " · ⚠ " + text
    res = {"level": "warn" if warn or text else "ok", "detail": detail, "problems": problems, "mode": m}
    if q is not None:
        res["queue"] = q
        res["queue_text"] = _queue_text(q)
    return res


# ── medidor mensal (decisão 3 do dono: sem teto, sem bloqueio — só informação) ─
def cost(brain, hs: Hindsight | None = None) -> dict:
    """Uso de LLM do mês por operação/modelo. embed não usa LLM: reporta US$ 0 e conta chunks."""
    mem = brain.inst.cfg["memory"]
    m = mode(mem)
    month = util.now().strftime("%Y-%m")
    if m != "full":
        n_docs = len(documents(brain)) if m == "embed" else 0
        return {"mode": m, "month": month, "usd": 0.0, "detail": f"US$ 0 — o modo {m} não usa LLM", "documents": n_docs}
    hs = hs or client(brain)
    stats = hs.llm_stats(mem["bank"])
    rows: dict[tuple[str, str], dict[str, float]] = {}
    for r in stats.get("requests", stats.get("items") or []):
        when = (r.get("created_at") or r.get("date") or "")[:7]
        if when and when != month:
            continue
        key = (r.get("operation") or r.get("operation_type") or "?", r.get("model") or "?")
        row = rows.setdefault(key, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        row["requests"] += int(r.get("requests") or r.get("count") or 1)
        row["input_tokens"] += int(r.get("input_tokens") or 0)
        row["output_tokens"] += int(r.get("output_tokens") or 0)
        row["cost_usd"] += float(r.get("cost_usd") or r.get("cost") or 0.0)
    total = sum(r["cost_usd"] for r in rows.values())
    return {"mode": m, "month": month, "usd": round(total, 4),
            "detail": f"US$ {total:.2f} em {month}" + ("" if total else " — sem uso registrado"),
            "rows": [{"operation": k[0], "model": k[1], **v} for k, v in sorted(rows.items())]}


def _cost_text(c: dict) -> str:
    if not c.get("rows"):
        return c["detail"]
    lines = [c["detail"]]
    for r in c["rows"]:
        lines.append(f"  {r['operation']} · {r['model']}: {r['requests']} chamadas · "
                     f"{r['input_tokens']:,} in/{r['output_tokens']:,} out tokens · US$ {r['cost_usd']:.2f}".replace(",", "."))
    return "\n".join(lines)


def _apply_mode(brain, new_mode: str) -> None:
    """`memory setup --mode` — grava as chaves do [memory] do modo pedido e valida os contratos.
    O modo full exige a chave do dono no config/.env (decisão 2: chave aprovada + nada público)."""
    if new_mode == "none":
        changed = config.set_keys(brain.inst, "memory", {"engine": "none"})
        print("✓ memória desligada" + (f" ({', '.join(changed)})" if changed else " (já estava)"))
        return
    updates: dict = {"engine": "hindsight"}
    if new_mode == "embed":
        updates.update({"extract": False, "cloud_llm": False, "mental_models": False, "raw_awaiting_dump": "degraded"})
    elif new_mode == "full":
        env = config.load_env(brain.inst)
        if not any(k.startswith("HINDSIGHT_API") and k.endswith("API_KEY") and v for k, v in env.items()):
            raise util.BrainError("modo full exige a chave de LLM do dono no config/.env (ex.: HINDSIGHT_API_LLM_API_KEY) — "
                                  "o compose lê o .env (services/compose.full.yaml); guides/memory.md", code=4)
        updates.update({"extract": True, "cloud_llm": True, "raw_awaiting_dump": "hold"})
    else:
        raise util.BrainError(f"modo inválido: {new_mode!r} — use none, embed ou full", code=4)
    validate({**brain.inst.cfg["memory"], **updates})
    changed = config.set_keys(brain.inst, "memory", updates)
    from .core import Brain                                        # recarga completa: o reload() do ledger não relê config
    brain.inst = config.load(brain.inst.root)
    brain.reload()
    print(f"✓ [memory] modo {new_mode}" + (f" ({', '.join(changed)})" if changed else " (já estava)"))


def cli(args, brain) -> None:
    c = args.mcmd
    mem = brain.inst.cfg["memory"]
    # --mode é justamente o que liga o engine: setup com --mode passa mesmo com engine = "none"
    if mem["engine"] != "hindsight" and c not in ("status", "cost") and not (c == "setup" and getattr(args, "mode", None)):
        raise util.BrainError("memória desligada: ponha [memory] engine = \"hindsight\" no config/brain.toml "
                              "depois de subir o servidor (guides/memory.md)", code=1)
    if c == "setup":
        if getattr(args, "mode", None):
            _apply_mode(brain, args.mode)      # grava [memory] e valida os contratos do modo
            brain.reload()
        banks = setup(brain)
        print(f"✓ bancos prontos ({mode(brain.inst.cfg['memory'])}): {', '.join(banks)}")
    elif c == "cost":
        c_ = cost(brain)
        if args.json:
            print(json.dumps(c_, ensure_ascii=False, indent=2))
        else:
            print(_cost_text(c_))
    elif c in ("sync", "rebuild"):
        res = (sync if c == "sync" else rebuild)(brain, args.limit, args.dry_run)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.dry_run:
            print(f"{len(res['would_send'])} documentos seriam enviados:\n  " + "\n  ".join(res["would_send"][:50]))
        else:
            print(f"✓ {res['sent']} documentos enviados · {res['remaining']} pendentes"
                  + (f" · {len(res['resent'])} reenviados por retain falho" if res.get("resent") else "")
                  + (f" · {len(res['gave_up'])} desistidos após {MAX_TRIES} reenvios: {', '.join(res['gave_up'][:3])}"
                     if res.get("gave_up") else "")
                  + (f" · {len(res['errors'])} erros (ex.: {res['errors'][0]})" if res["errors"] else ""))
    elif c == "status":
        s = status(brain, online=True)
        if args.json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
            return
        print(("✓ " if s["level"] == "ok" else "⚠ ") + s["detail"])
        if s.get("queue_text"):
            print("  " + s["queue_text"])
    elif c in ("recall", "reflect"):
        hs = client(brain)
        bank = mem["bank"]   # banco único (decisão 8) — --bank é legado, aceito e ignorado
        tags = util.split_csv(args.tags) or None
        res = (hs.recall if c == "recall" else hs.reflect)(bank, args.query, tags)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif c == "recall":
            for r in res.get("results", [])[:15]:
                print(f"- {r.get('text', '')}  ⟶ {r.get('document_id') or '?'} ({(r.get('occurred_start') or r.get('mentioned_at') or '')[:10]})")
            if not res.get("results"):
                print("não consta")
        else:
            print(res.get("text") or res.get("answer") or json.dumps(res, ensure_ascii=False)[:2000])
