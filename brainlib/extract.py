"""Extração por LLM local (endpoint OpenAI-compatible — LM Studio, etc.).

Produz RASCUNHO de eventos no formato de `./brain add`. Nunca grava sozinho:
o dry-run valida cada item contra o estado real (schema + referências) e o
modelo que erra, o CLI recusa. `--record` grava apenas o que passou.

A qualidade vem do funil, não do modelo: prompt curto por tipo → JSON →
resolução determinística de aliases → validação do ledger. Um modelo pequeno
(4B) basta para reunião/nota; documento longo ainda é melhor no agente da sessão.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import people, schema, util
from .core import Brain

KINDS = ("reuniao", "documento", "nota", "conector")
# Só o que o extrator pode propor. Fecho de ação, pessoas novas e mudanças de
# PLANNING continuam sendo do dono/agente da sessão (proposta ou /done).
ALLOWED_TYPES = {"action.opened", "decision.made", "delivery.recorded"}
CONNECTOR_PREFIXES = ("gcal-", "gmail-", "slack-", "jira-", "drive-", "github-")

SYSTEM = (
    "Você é o extrator do Segundo Cérebro. Recebe o texto de uma fonte de trabalho "
    "e devolve UM array JSON de eventos — nada mais: sem markdown, sem comentários, "
    "sem texto antes ou depois.\n"
    "Regras:\n"
    "1. Só proponha o que o texto sustenta. Conhecimento de mundo e suposição: nunca.\n"
    "2. Datas SEMPRE em AAAA-MM-DD. Se a fonte só diz relativo ('quinta', 'semana que vem') "
    "e a data absoluta não consta, OMITA o campo.\n"
    "3. owner: 'eu' quando a tarefa é do dono do cérebro; senão o nome da pessoa como citado.\n"
    "4. list: 'mine' (dono deve), 'waiting' (terceiro deve ao dono), 'watching' (só contexto).\n"
    "5. effort_min: inteiro em minutos ('90m'→90, '2h'→120). Sem tempo citado, omita.\n"
    "6. Prefira array vazio a inventar. Ruído social/saudação não é evento.\n"
    "Formato dos itens:\n"
    '{"type":"action.opened","data":{"title":"…","owner":"…","list":"mine|waiting|watching",'
    '"due":"AAAA-MM-DD","effort_min":90,"project":"P1"}}\n'
    '{"type":"decision.made","data":{"title":"…","decided_by":["Nome"],"project":"P1","rationale":"…"}}\n'
    '{"type":"delivery.recorded","data":{"title":"…","ref":"P1.1"}}'
)

KIND_EXTRA = {
    "reuniao": ("Fonte: reunião (transcrição/ata). Extraia decisões com quem decidiu "
                "(decided_by), ações por dono, entregas concluídas citadas. A base da "
                "decisão vai no rationale."),
    "documento": ("Fonte: documento longo (política, spec, apresentação). Extraia apenas "
                  "decisões registradas, ações exigidas do dono e prazos explícitos. "
                  "Resumo/TL;DR NÃO é evento."),
    "nota": ("Fonte: nota curta do dono. Se a nota pedir algo de alguém, vira ação; "
             "senão, array vazio."),
    "conector": ("Fonte: snapshot de conector (e-mail, Slack, Jira, agenda). Extraia só "
                 "mudanças que geram ação ou decisão do dono. Ignore acks e ruído."),
}


# ── heurística de tipo ───────────────────────────────────────────────────
def guess_kind(path: Path) -> str:
    name = path.name.lower()
    if name.startswith(CONNECTOR_PREFIXES):
        return "conector"
    head = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        head = ""
    low = (name + " " + head[:600]).lower()
    if path.suffix.lower() in {".vtt", ".srt"} or "transcri" in low or re.search(r"ata[\s_-]*reuni", low):
        return "reuniao"
    try:
        size = path.stat().st_size
    except OSError:
        size = len(head)
    return "documento" if size > 6000 else "nota"


# ── cliente OpenAI-compatible (stdlib) ───────────────────────────────────
def _cfg(brain: Brain) -> dict:
    cfg = brain.inst.cfg["extractor"]
    if not cfg.get("enabled"):
        raise util.BrainError("extrator desligado — [extractor] enabled = true no config/brain.toml "
                              "(setup.md §4)", code=4)
    if not cfg.get("model"):
        raise util.BrainError("[extractor] model vazio — `lms ls` lista os modelos no LM Studio",
                              code=4)
    return cfg


def chat(cfg: dict, system: str, user: str) -> str:
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    key_env = cfg.get("api_key_env") or ""
    if key_env and os.environ.get(key_env):
        headers["Authorization"] = f"Bearer {os.environ[key_env]}"
    body = {"model": cfg["model"], "temperature": cfg.get("temperature", 0.1),
            "max_tokens": int(cfg.get("max_tokens") or 4096),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout_s") or 180)) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise util.BrainError(f"extrator: {url} não respondeu ({e}) — o LM Studio está no ar? "
                              f"(`lms server start`)", code=2) from e
    except json.JSONDecodeError as e:
        raise util.BrainError(f"extrator: resposta não-JSON de {url}: {e}", code=2) from e
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise util.BrainError(f"extrator: resposta sem choices/content: {str(data)[:300]}", code=2) from e


# ── parse tolerante ──────────────────────────────────────────────────────
def parse_json(text: str) -> list[dict]:
    """Extrai o array (ou objeto único) de uma resposta que pode ter cerca/markdown."""
    s = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    for a, b, wrap in (("[", "]", False), ("{", "}", True)):
        i, j = s.find(a), s.rfind(b)
        if i != -1 and j > i:
            try:
                parsed = json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                continue
            return parsed if isinstance(parsed, list) else ([parsed] if wrap else [])
    raise util.BrainError("extrator: resposta sem JSON utilizável — primeiro o modelo, "
                          "depois a validação; tente de novo ou use o agente da sessão", code=2)


# ── refinamento determinístico ───────────────────────────────────────────
def _resolve_person(brain: Brain, value: str) -> str:
    if not isinstance(value, str) or not value:
        return value
    if util.fold(value) in ("eu", "voce", "dono", "owner"):
        return brain.owner
    if value in brain.state.people:
        return value
    cands = people.resolve(brain.state, value)
    return cands[0] if len(cands) == 1 else value  # 0 ou ambíguo: fica o nome, a validação explica


def refine(brain: Brain, items: list[dict], source: str) -> tuple[list[dict], list[str]]:
    """Normaliza a proposta do modelo para o formato de `brain add`."""
    out: list[dict] = []
    dropped: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            dropped.append("item não-objeto")
            continue
        t = raw.get("type")
        if t not in ALLOWED_TYPES:
            dropped.append(f"tipo fora do escopo do extrator: {t!r}")
            continue
        data = {k: v for k, v in (raw.get("data") or {}).items() if v not in (None, "", [])}
        if isinstance(data.get("decided_by"), str):
            data["decided_by"] = [data["decided_by"]]
        for key in ("owner",):
            if data.get(key):
                data[key] = _resolve_person(brain, data[key])
        if isinstance(data.get("decided_by"), list):
            data["decided_by"] = [_resolve_person(brain, p) for p in data["decided_by"] if p]
            if not data["decided_by"]:
                dropped.append(f"{t}: decided_by vazio — descartado")
                continue
        ev = {"type": t, "by": "agent", "prov": "observado", "source": source, "data": data}
        out.append(ev)
    return out, dropped


# ── dry-run: valida sem gravar ───────────────────────────────────────────
def dry_run(brain: Brain, items: list[dict]) -> tuple[list[dict], list[str]]:
    """Separa (válidos, erros) usando a MESMA validação do record()."""
    ok: list[dict] = []
    errs: list[str] = []
    for it in items:
        try:
            ev = brain._normalize(dict(it), brain.state)
            schema.validate(ev, brain.state, brain.plan)
            ok.append(ev)
        except util.BrainError as e:
            errs.append(f"{it.get('type')}: {e}")
        except KeyError as e:
            errs.append(f"{it.get('type')}: campo ausente {e}")
    return ok, errs


# ── orquestração ─────────────────────────────────────────────────────────
def _vault_rel(brain: Brain, path: Path) -> str:
    p = path.resolve()
    vault = brain.inst.vault.resolve()
    if vault not in p.parents:
        raise util.BrainError(f"{path}: fora do vault — passe um arquivo de RAW/", code=4)
    return str(p.relative_to(vault))


def extract(brain: Brain, path: Path, kind: str = "auto") -> dict:
    cfg = _cfg(brain)
    source = _vault_rel(brain, path)
    if not path.is_file():
        raise util.BrainError(f"{path}: arquivo não encontrado", code=3)
    kind = kind if kind != "auto" else guess_kind(path)
    if kind not in KINDS:
        raise util.BrainError(f"tipo inválido: {kind!r} — use {'|'.join(KINDS)}", code=1)
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise util.BrainError(f"{path}: vazio", code=3)
    user = (f"Tipo: {kind}\nArquivo: {source}\n\n{KIND_EXTRA[kind]}\n\n"
            f"--- FONTES DISPONÍVEIS (para project, use só se tiver certeza) ---\n"
            f"projetos: {', '.join(sorted(brain.plan.projects)) or 'nenhum'}\n\n"
            f"--- TEXTO ---\n{text[:60000]}")
    raw = chat(cfg, SYSTEM, user)
    items, dropped = refine(brain, parse_json(raw), source)
    ok, errs = dry_run(brain, items)
    return {"kind": kind, "source": source, "proposed": len(items), "dropped": dropped,
            "events": ok, "errors": errs}


def selftest(brain: Brain) -> dict:
    """Extrai de uma reunião do vault de demo e valida — prova o funil ponta a ponta."""
    from . import demo as demo_mod
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "demo"
        demo_mod.build(target)
        demo_brain = Brain(_load_inst(target))
        # o demo nasce com o extrator desligado — o selftest testa o extrator da instância real
        demo_brain.inst.cfg["extractor"] = dict(brain.inst.cfg["extractor"])
        raws = sorted((target / "vault" / "RAW").rglob("*.md"))
        raws = [r for r in raws if r.name != ".keep.md"]
        # prefere uma reunião de verdade para provar o funil completo
        meeting = next((r for r in raws if guess_kind(r) == "reuniao" and r.stat().st_size > 200), None)
        if meeting:
            raws.remove(meeting)
            raws.insert(0, meeting)
        if not raws:
            raise util.BrainError("selftest: demo não gerou RAW — bug no demo", code=5)
        result = extract(demo_brain, raws[0])
    result["selftest"] = "ok" if result["proposed"] else "ok (modelo não achou eventos — veja 'dropped')"
    return result


def _load_inst(root: Path):
    from . import config
    return config.load(root)


def cli(args, brain: Brain) -> None:
    if getattr(args, "selftest", False):
        result = selftest(brain)
    else:
        if not args.path:
            raise util.BrainError("uso: brain extract <arquivo-raw> [--kind auto] [--record]", code=1)
        result = extract(brain, Path(args.path), kind=args.kind)
        if getattr(args, "record", False) and result["events"]:
            recorded = brain.record(result["events"])
            result["recorded"] = [f"{e['type']} {e.get('id', '')}" for e in recorded]
    if getattr(args, "json", False):
        printable = {**result, "events": [{k: v for k, v in e.items() if k != "data"} | {"data": e["data"]}
                                          for e in result["events"]]}
        print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
        return
    print(f"tipo: {result['kind']} · fonte: {result['source']} · propostos: {result['proposed']}")
    for d in result.get("dropped", []):
        print(f"– descartado: {d}")
    for e in result["events"]:
        d = e.get("data", {})
        print(f"✓ {e['type']} · {d.get('title', '')[:80]}" +
              (f" · {d.get('owner', '')}" if d.get("owner") else ""))
    for e in result.get("errors", []):
        print(f"✗ {e}")
    if result.get("recorded"):
        print(f"gravados: {len(result['recorded'])} — {', '.join(result['recorded'])}")
    elif not getattr(args, "selftest", False):
        print("\nRascunho pronto. Revise e grave com:\n  ./brain add <<'JSON'\n  [...]\n  JSON")
