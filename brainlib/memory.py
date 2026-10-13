"""Camada de memória para IA — Hindsight, alimentado SÓ pelo vault (mão única) e reconstruível.

Dois bancos (config [memory]):
  raw_bank · arquivos do RAW como estão (retain_extraction_mode = chunks — sem LLM, sem interpretação)
  mem_bank · artefatos do PROCESSED + entidades do ledger + PLANNING/PROFILE, com extração de fatos
document_id = caminho no vault (ou ledger/<ID>): toda lembrança aponta para algo citável.
O vault é a verdade; `brain memory rebuild` apaga os bancos e reconstrói do zero.
O LLM de extração é configurado no servidor Hindsight (guides/memory.md), não aqui.
"""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import config, model, util

STATE_NAME = ".memory-state.json"
RAW_TEXT = {".md", ".txt", ".csv", ".json", ".html", ".htm", ".vtt", ".srt", ".tsv"}
RAW_FILES = {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls", ".odt", ".rtf"}

MEM_MISSION = ("Memória de trabalho de {owner}: goals, projetos, decisões (quem decidiu e quando), ações "
               "(quem deve o quê e até quando), entregas e pessoas. Conteúdo em português do Brasil. "
               "O document_id de cada memória é o caminho do arquivo no vault — cite-o ao responder.")
RETAIN_MISSION = ("Extraia fatos duráveis: decisões e quem decidiu, compromissos com dono e prazo, entregas e "
                  "resultados, mudanças de plano, papéis e preferências observadas das pessoas. Preserve datas, "
                  "nomes e números exatamente. Ignore logística de reunião, cumprimentos e conversa social.")
OBS_MISSION = "Observações são fatos estáveis sobre pessoas, projetos e o modo de trabalho do dono."


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
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise util.BrainError(f"Hindsight fora do ar em {self.url} ({e}) — suba o servidor "
                                  f"(guides/memory.md) ou use [memory] engine = \"none\"", code=2) from e

    def _bank(self, bank: str) -> str:
        return f"/v1/default/banks/{urllib.parse.quote(bank)}"

    def health(self) -> dict:
        return self._req("GET", "/health")

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
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n\r\n{request}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{path.name}\"\r\n"
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


def client(brain) -> Hindsight:
    mem = brain.inst.cfg["memory"]
    env = config.load_env(brain.inst)
    return Hindsight(mem["url"], mem["timeout_s"], env.get("HINDSIGHT_API_TOKEN") or None)


# ── documentos que o vault oferece à memória ────────────────────────────────
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


def documents(brain) -> list[dict]:
    inst, st = brain.inst, brain.state
    mem_cfg = inst.cfg["memory"]
    max_bytes = mem_cfg["max_file_mb"] * 2**20
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
                     "date": art.date.isoformat() if art and art.date else None, "tags": tags})
    for rel in ("PLANNING/goals.md", "PLANNING/log.md", "PROFILE/profile.md"):
        p = inst.vault / rel
        if p.exists():
            docs.append({"bank": "mem", "id": rel, "text": p.read_text(encoding="utf-8"), "date": None,
                         "tags": ["tipo:planejamento" if rel.startswith("PLANNING") else "tipo:perfil"]})
    for doc_id, text, date, tags in _entity_docs(brain):
        docs.append({"bank": "mem", "id": doc_id, "text": text, "date": date, "tags": tags})
    raw = inst.vault / "RAW"
    for path in sorted(raw.rglob("*")) if raw.exists() else []:
        if not path.is_file() or "inbox" in path.relative_to(raw).parts or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        size = path.stat().st_size
        rel = inst.rel(path)
        if ext in RAW_TEXT and size <= max_bytes:
            docs.append({"bank": "raw", "id": rel, "text": path.read_text(encoding="utf-8", errors="replace"),
                         "date": None, "tags": ["tipo:raw", f"ext:{ext[1:]}"]})
        elif ext in RAW_FILES and size <= max_bytes:
            # RAW é imutável: tamanho+mtime bastam para detectar mudança sem reler binários a cada render
            docs.append({"bank": "raw", "id": rel, "file": path, "date": None,
                         "tags": ["tipo:raw", f"ext:{ext[1:]}"], "sha": f"{size}:{int(path.stat().st_mtime)}"})
    for d in docs:
        d.setdefault("sha", util.sha(d.get("text", "")))
    return docs


def _state_path(brain) -> Path:
    return brain.inst.config_dir / STATE_NAME


def pending(brain) -> list[dict]:
    state = util.read_json(_state_path(brain), {})
    return [d for d in documents(brain) if state.get(d["bank"], {}).get(d["id"]) != d["sha"]]


def setup(brain, hs: Hindsight | None = None) -> list[str]:
    hs = hs or client(brain)
    mem = brain.inst.cfg["memory"]
    owner = brain.inst.cfg["owner"]["name"]
    hs.put_bank(mem["mem_bank"], {"name": "Segundo Cérebro — conhecimento", "mission": MEM_MISSION.format(owner=owner),
                                  "retain_mission": RETAIN_MISSION, "observations_mission": OBS_MISSION})
    hs.patch_config(mem["mem_bank"], {"retain_extraction_mode": "concise"})
    hs.put_bank(mem["raw_bank"], {"name": "Segundo Cérebro — RAW (texto original)",
                                  "mission": "Arquivo bruto do vault: texto original, sem interpretação."})
    hs.patch_config(mem["raw_bank"], {"retain_extraction_mode": "chunks"})
    return [mem["mem_bank"], mem["raw_bank"]]


def sync(brain, limit: int | None = None, dry_run: bool = False, hs: Hindsight | None = None) -> dict:
    todo = pending(brain)
    if limit:
        todo = todo[:limit]
    if dry_run:
        return {"would_send": [f"{d['bank']}:{d['id']}" for d in todo], "sent": 0}
    hs = hs or client(brain)
    mem = brain.inst.cfg["memory"]
    banks = {"mem": mem["mem_bank"], "raw": mem["raw_bank"]}
    state = util.read_json(_state_path(brain), {})
    sent, errors = 0, []
    for d in todo:
        meta = {"document_id": d["id"], "tags": d["tags"], "metadata": {"vault_path": d["id"]}}
        if d.get("date"):
            meta["timestamp"] = f"{d['date']}T12:00:00"
        try:
            if "file" in d:
                hs.retain_file(banks[d["bank"]], d["file"], meta)
            else:
                hs.retain(banks[d["bank"]], [{"content": d["text"], "context": d["id"], **meta}])
        except util.BrainError as e:
            errors.append(f"{d['id']}: {e}")
            if "fora do ar" in str(e):
                break
            continue
        state.setdefault(d["bank"], {})[d["id"]] = d["sha"]
        sent += 1
        if sent % 20 == 0:
            util.write_json(_state_path(brain), state)
    util.write_json(_state_path(brain), state)
    return {"sent": sent, "errors": errors, "remaining": len(pending(brain))}


def rebuild(brain, limit: int | None = None, dry_run: bool = False) -> dict:
    if dry_run:
        return sync(brain, limit, dry_run=True)
    hs = client(brain)
    mem = brain.inst.cfg["memory"]
    for bank in (mem["mem_bank"], mem["raw_bank"]):
        try:
            hs.delete_bank(bank)
        except util.BrainError as e:
            if "404" not in str(e):
                raise
    _state_path(brain).unlink(missing_ok=True)
    setup(brain, hs)
    return sync(brain, limit, hs=hs)


def status(brain, online: bool = False) -> dict:
    mem = brain.inst.cfg["memory"]
    if mem["engine"] != "hindsight":
        return {"level": "ok", "detail": "desligada ([memory] engine = \"none\") — /ask usa índice → artefato → RAW"}
    n = len(pending(brain))
    detail = f"Hindsight em {mem['url']} · {n} documentos do vault ainda não enviados"
    if online:
        try:
            client(brain).health()
            detail += " · servidor no ar"
        except util.BrainError as e:
            return {"level": "error", "detail": str(e)}
    return {"level": "warn" if n > 50 else "ok", "detail": detail + ("" if n <= 50 else " — rode `brain memory sync`")}


def cli(args, brain) -> None:
    c = args.mcmd
    mem = brain.inst.cfg["memory"]
    if mem["engine"] != "hindsight" and c not in ("status",):
        raise util.BrainError("memória desligada: ponha [memory] engine = \"hindsight\" no config/brain.toml "
                              "depois de subir o servidor (guides/memory.md)", code=1)
    if c == "setup":
        banks = setup(brain)
        print(f"✓ bancos prontos: {', '.join(banks)}")
    elif c in ("sync", "rebuild"):
        res = (sync if c == "sync" else rebuild)(brain, args.limit, args.dry_run)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.dry_run:
            print(f"{len(res['would_send'])} documentos seriam enviados:\n  " + "\n  ".join(res["would_send"][:50]))
        else:
            print(f"✓ {res['sent']} documentos enviados · {res['remaining']} pendentes"
                  + (f" · {len(res['errors'])} erros (ex.: {res['errors'][0]})" if res["errors"] else ""))
    elif c == "status":
        s = status(brain, online=True)
        print(("✓ " if s["level"] == "ok" else "⚠ ") + s["detail"])
    elif c in ("recall", "reflect"):
        hs = client(brain)
        bank = mem["mem_bank"] if args.bank == "mem" else mem["raw_bank"]
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
