"""Catálogo de modelos do LLM da memória — a lista viva de cada provedor, o mais novo de cada linha e os
níveis de esforço de cada modelo.

Três perguntas, uma fonte:
  • Quais modelos existem? A API do fornecedor quando há chave no config/.env (a da Anthropic diz também os
    níveis de esforço exatos de cada modelo); sem chave, o catálogo público do OpenRouter. Cache de 24 h em
    `<instância>/.models-catalog.json` — dado derivado, refeito a qualquer momento.
  • Qual é o mais novo da linha? Linha = família de mesmo porte (claude-haiku, gpt-luna, grok, gemini-flash-lite…);
    o padrão do Brain é uma SEMENTE (o modelo curado no registro) e vale o mais novo da mesma linha com versão
    igual ou maior. Haiku 5.6 publicado ⇒ quem está no padrão passa a usar o 5.6 (`follow`, na checagem diária).
  • Que esforço o modelo aceita? Regras por linha/versão a partir das tabelas dos fornecedores; versão mais nova
    que a última conhecida herda os níveis da anterior (marcada `inferred`). A API da Anthropic, quando lida,
    vence a regra.

Por onde o esforço chega ao servidor (Hindsight 1.3.0, sondado na imagem pinada):
  reasoning  → HINDSIGHT_API_[<OP>_]LLM_REASONING_EFFORT (claude-code --effort, OpenAI chat, ChatGPT Responses,
               xAI; o servidor descarta `none` no xAI)
  anthropic  → HINDSIGHT_API_[<OP>_]LLM_EXTRA_BODY = {"output_config": {"effort": …}} — o lane da API Anthropic
               ignora REASONING_EFFORT; o extra body é mesclado em profundidade e mantém o schema (#6640)
  gemini     → HINDSIGHT_API_[<OP>_]LLM_EXTRA_BODY = {"thinking_config": {"thinking_level": …}} — o lane Gemini
               ignora REASONING_EFFORT e semeia o GenerateContentConfig com o extra body
Operação sem valor próprio herda o global no servidor (`retain_… or llm_…`).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from . import util

TTL_S = 24 * 3600
CACHE_FILE = ".models-catalog.json"
MOVES_KEPT = 10

LEVEL_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
LEVEL_LABELS = {"none": "nenhum (sem raciocínio)", "minimal": "mínimo", "low": "baixo", "medium": "médio",
                "high": "alto", "xhigh": "muito alto", "max": "máximo"}

# provedor do slot LLM → fornecedor do catálogo e lane do esforço. Fora daqui: sem catálogo vivo (lista do
# registro) e sem esforço ajustável pelo Brain (o modelo recomendado não expõe o parâmetro).
VENDOR = {"anthropic": "anthropic", "claude-code": "anthropic", "openai": "openai", "chatgpt": "openai",
          "xai-oauth": "xai", "gemini": "google"}
EFFORT_LANE = {"claude-code": "reasoning", "anthropic": "anthropic", "openai": "chat", "chatgpt": "reasoning",
               "xai-oauth": "reasoning", "gemini": "gemini", "custom": "chat"}
OPENROUTER_PREFIX = {"anthropic": "anthropic/", "openai": "openai/", "xai": "x-ai/", "google": "google/"}
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"

_L5 = ("low", "medium", "high", "xhigh", "max")

# Última versão que as regras conhecem por linha — acima disso os níveis são herdados (`inferred`).
KNOWN_MAX = {"claude-haiku": (5, 5), "claude-sonnet": (5, 5), "claude-opus": (5, 5), "claude-fable": (5, 2),
             "claude-mythos": (5, 2), "gpt-luna": (6, 0), "gpt-sol": (6, 2), "gpt-terra": (6, 1),
             "gpt-astra": (6, 2), "gpt": (5, 6), "gpt-nano": (5, 0), "gpt-mini": (5, 0), "grok": (4, 7),
             "gemini-neon": (4, 0), "gemini-hydrogen": (4, 0), "gemini-carbon": (4, 0),
             "gemini-flash-lite": (3, 5), "gemini-flash": (3, 8), "gemini-pro": (3, 1)}

_RX = (
    ("anthropic", re.compile(r"^claude-(haiku|sonnet|opus|fable|mythos)-(\d+)(?:[-.](\d{1,2}))?$")),
    ("openai", re.compile(r"^gpt-(\d+)(?:\.(\d+))?(?:-(luna|sol|terra|astra|nano|mini))?$")),
    ("xai", re.compile(r"^grok-(\d+)(?:\.(\d+))?(?:-(fast|mini))?$")),
    ("google", re.compile(r"^gemini-(\d+)(?:\.(\d+))?-(flash-lite|flash|pro|neon|hydrogen|carbon|argon)$")),
)


def parse(model_id: str) -> dict | None:
    """`claude-haiku-5-5` → {vendor, line, version, id}. Snapshot datado, preview, variante (`:batch`) e modelo
    fora das quatro casas = None: não entram na escolha do mais novo."""
    mid = (model_id or "").strip()
    for vendor, rx in _RX:
        m = rx.match(mid)
        if not m:
            continue
        g = m.groups()
        if vendor == "anthropic":
            line, ver = f"claude-{g[0]}", (int(g[1]), int(g[2] or 0))
            mid = f"claude-{g[0]}-{g[1]}" + (f"-{g[2]}" if g[2] else "")      # forma canônica da API
        elif vendor == "openai":
            line, ver = ("gpt-" + g[2]) if g[2] else "gpt", (int(g[0]), int(g[1] or 0))
        elif vendor == "xai":
            line, ver = ("grok-" + g[2]) if g[2] else "grok", (int(g[0]), int(g[1] or 0))
        else:
            line, ver = f"gemini-{g[2]}", (int(g[0]), int(g[1] or 0))
        return {"vendor": vendor, "line": line, "version": ver, "id": mid}
    return None


def _rule(p: dict) -> tuple[tuple[str, ...], str] | None:
    """Níveis e padrão do fornecedor por linha/versão (tabelas públicas de 2026-11). None = sem esforço."""
    line, v = p["line"], p["version"]
    if line in ("claude-fable", "claude-mythos"):
        return _L5, "high"
    if line == "claude-opus":
        if v >= (5, 5):
            return _L5, "medium"
        if v >= (4, 7):
            return _L5, "high"
        if v == (4, 6):
            return ("low", "medium", "high", "max"), "high"
        if v == (4, 5):
            return ("low", "medium", "high"), "high"
        return None
    if line == "claude-sonnet":
        if v >= (5, 0):
            return _L5, "high"
        if v == (4, 6):
            return ("low", "medium", "high", "max"), "high"
        return None
    if line == "claude-haiku":
        return (_L5, "medium") if v >= (5, 5) else None
    if line.startswith("gpt"):
        tier = line.partition("-")[2]
        if v >= (6, 0):
            no_none = tier == "astra" or (tier == "sol" and v >= (6, 1))
            return (_L5 if no_none else ("none",) + _L5), "medium"
        if v >= (5, 6):
            return ("none",) + _L5, "medium"
        if v >= (5, 4):
            return ("none", "low", "medium", "high", "xhigh"), "medium"
        if v >= (5, 1):
            return ("none", "low", "medium", "high"), "medium"
        if v == (5, 0):
            return ("minimal", "low", "medium", "high"), "medium"
        return None
    if line == "grok":
        return (("low", "medium", "high", "xhigh"), "high") if v >= (4, 7) else None
    if line in ("gemini-neon", "gemini-hydrogen"):
        return ("low", "medium", "high", "xhigh"), "high"
    if line == "gemini-carbon":
        return ("low", "medium", "high"), "medium"
    if line == "gemini-flash-lite":
        if v >= (3, 5):
            return ("low", "medium", "high"), "high"
        return (("minimal", "low", "medium", "high"), "high") if v >= (3, 0) else None
    if line == "gemini-flash":
        return (("minimal", "low", "medium", "high"), "high") if v >= (3, 0) else None
    if line == "gemini-pro":
        return (("low", "high"), "high") if v >= (3, 0) else None
    return None


def lane(provider: str) -> str:
    return EFFORT_LANE.get(provider, "")


def efforts(provider: str, model_id: str, catalog_entry: dict | None = None) -> dict:
    """O que o seletor de esforço oferece para `model_id` no provedor. `levels` vazio = sem esforço ajustável;
    `known` False = modelo fora das regras (o Brain não inventa níveis — a CLI aceita a escala genérica com aviso);
    `inferred` = versão mais nova que a última conhecida, níveis herdados da linha."""
    ln = lane(provider)
    out = {"lane": ln, "levels": [], "default": "", "known": False, "inferred": False, "source": "regra"}
    if not ln:
        return out
    if catalog_entry and catalog_entry.get("levels") is not None and catalog_entry.get("levels_source") == "api":
        out.update(levels=list(catalog_entry["levels"]), default=catalog_entry.get("default", ""), known=True,
                   source="api")
        return out
    p = parse(model_id)
    if not p:
        return out
    r = _rule(p)
    if r is None:
        out["known"] = True
        return out
    levels, default = r
    if ln == "chat" and provider == "openai":
        levels = tuple(x for x in levels if x != "max")      # `max` só pela Responses API; o lane OpenAI é chat
    if ln == "reasoning" and provider == "xai-oauth":
        levels = tuple(x for x in levels if x != "none")     # o servidor descarta `none` no xAI
    if ln == "reasoning" and provider == "claude-code":
        levels = tuple(x for x in levels if x in _L5)        # o CLI aceita low…max (_CLI_EFFORT_LEVELS)
    out.update(levels=list(levels), default=default if default in levels else (levels[0] if levels else ""),
               known=True, inferred=p["version"] > KNOWN_MAX.get(p["line"], p["version"]))
    return out


def check_effort(provider: str, model_id: str, level: str, catalog_entry: dict | None = None) -> str:
    """Valida o nível pedido para o modelo. Devolve aviso (texto) quando o Brain não tem como confirmar."""
    level = (level or "").strip().lower()
    if not level:
        return ""
    if level not in LEVEL_ORDER:
        raise util.BrainError(f"esforço inválido: {level!r} — use {', '.join(LEVEL_ORDER)}", code=4)
    e = efforts(provider, model_id, catalog_entry)
    if not e["lane"]:
        raise util.BrainError(f"o provedor {provider!r} não tem esforço ajustável pelo Brain", code=4)
    if e["known"] and not e["levels"]:
        raise util.BrainError(f"{model_id} não aceita esforço ajustável", code=4)
    if e["known"] and level not in e["levels"]:
        raise util.BrainError(f"{model_id} aceita esforço {', '.join(e['levels'])} — não {level!r}", code=4)
    if not e["known"]:
        return f"níveis de esforço de {model_id} não constam no catálogo do Brain — {level!r} vai como pedido"
    return ""


# ── o catálogo vivo ──────────────────────────────────────────────────────────────────────────────────────────

def _http_json(url: str, headers: dict | None = None, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "segundo-cerebro", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:                    # noqa: S310 — URLs fixas acima
        return json.loads(r.read().decode("utf-8"))


def _anthropic_levels(caps: dict) -> tuple[list[str] | None, str]:
    eff = (caps or {}).get("effort")
    if not isinstance(eff, dict):
        return None, ""
    if not eff.get("supported"):
        return [], ""
    lv = [x for x in _L5 if isinstance(eff.get(x), dict) and eff[x].get("supported")]
    return lv, ""


def _from_vendor(vendor: str, key: str, http, oauth: bool = False) -> list[dict]:
    out: list[dict] = []
    if vendor == "anthropic":
        hdr = {"anthropic-version": "2023-06-01"}
        hdr.update({"Authorization": f"Bearer {key}", "anthropic-beta": "oauth-2025-04-20"} if oauth
                   else {"x-api-key": key})
        after = ""
        for _ in range(10):
            d = http("https://api.anthropic.com/v1/models?limit=1000" + (f"&after_id={after}" if after else ""), hdr)
            for m in d.get("data") or []:
                lv, _df = _anthropic_levels(m.get("capabilities") or {})
                out.append({"id": m.get("id", ""), "created": m.get("created_at", ""), "line_api": m.get("line"),
                            "levels": lv, "levels_source": "api" if lv is not None else ""})
            if not d.get("has_more"):
                break
            after = d.get("last_id") or ""
            if not after:
                break
    elif vendor == "openai":
        d = http("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
        out = [{"id": m.get("id", ""), "created": m.get("created", 0)} for m in d.get("data") or []]
    elif vendor == "google":
        token = ""
        for _ in range(10):
            d = http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
                     + (f"&pageToken={token}" if token else ""), {"x-goog-api-key": key})
            out += [{"id": str(m.get("name", "")).removeprefix("models/"), "created": ""}
                    for m in d.get("models") or []]
            token = d.get("nextPageToken") or ""
            if not token:
                break
    return out


def _from_openrouter(vendor: str, http) -> list[dict]:
    pre = OPENROUTER_PREFIX[vendor]
    out = []
    for m in (http(OPENROUTER_URL, {}).get("data") or []):
        mid = str(m.get("id", ""))
        if not mid.startswith(pre) or ":" in mid:
            continue
        out.append({"id": mid.removeprefix(pre), "created": m.get("created", 0)})
    return out


def _cache_path(brain):
    return brain.inst.root / CACHE_FILE


def load_cache(brain) -> dict:
    try:
        return json.loads(_cache_path(brain).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(brain, data: dict) -> None:
    util.atomic_write(_cache_path(brain), json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _key_for(brain, provider: str) -> tuple[str, bool]:
    """Chave do fornecedor para LER a lista — só a que já está no .env para o provedor em uso (nunca impressa)."""
    from . import config
    mem = brain.inst.cfg["memory"]
    if mem.get("llm_provider") != provider:
        return "", False
    tok = config.load_env(brain.inst).get("HINDSIGHT_API_LLM_API_KEY", "")
    if provider in ("anthropic", "openai", "gemini"):
        return tok, False
    if provider == "claude-code" and tok.startswith("sk-ant-oat"):
        return tok, True
    return "", False


def catalog(brain, provider: str, *, refresh: bool = False, http=None, now: float | None = None) -> dict:
    """Modelos de `provider`: {source, at, models: [{id, line, version, levels?, levels_source?}], error}.
    Cache de 24 h; `refresh` força. Falha de rede devolve o cache (ou vazio) com `error` — nunca derruba quem chama."""
    vendor = VENDOR.get(provider)
    now = time.time() if now is None else now
    data = load_cache(brain)
    ent = (data.get("providers") or {}).get(provider) or {}
    if not vendor:
        return {"source": "registro", "at": 0, "models": [], "error": ""}
    if ent and not refresh and now - float(ent.get("at") or 0) < TTL_S:
        return ent
    http = http or _http_json
    key, oauth = _key_for(brain, provider)
    raw, source, err = [], "", ""
    if key:
        try:
            raw, source = _from_vendor(vendor, key, http, oauth=oauth), vendor
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            err = f"API do fornecedor: {type(e).__name__}"
    if not raw:
        try:
            raw, source = _from_openrouter(vendor, http), "openrouter"
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            err = (err + " · " if err else "") + f"OpenRouter: {type(e).__name__}"
    if not raw:
        if ent:
            return {**ent, "error": err or "lista vazia"}
        return {"source": "", "at": 0, "models": [], "error": err or "lista vazia"}
    models: dict[str, dict] = {}
    for m in raw:
        p = parse(m.get("id", ""))
        if not p or p["vendor"] != vendor:
            continue
        cur = {"id": p["id"], "line": p["line"], "version": list(p["version"])}
        if m.get("levels_source") == "api":
            cur.update(levels=m["levels"], levels_source="api")
        models[p["id"]] = {**models.get(p["id"], {}), **cur}
    ent = {"source": source, "at": now, "error": err,
           "models": sorted(models.values(), key=lambda x: (x["line"], [-n for n in x["version"]]))}
    data.setdefault("providers", {})[provider] = ent
    _save_cache(brain, data)
    return ent


def entry(cat: dict | None, model_id: str) -> dict | None:
    return next((m for m in (cat or {}).get("models") or [] if m["id"] == model_id), None)


def newest(seed: str, models: list[dict]) -> str:
    """O mais novo da linha de `seed` com versão ≥ à dela; sem catálogo (ou fora das regras) = a própria semente."""
    p = parse(seed)
    if not p:
        return seed
    best, best_v = p["id"], p["version"]
    for m in models or []:
        v = tuple(m.get("version") or ())
        if m.get("line") == p["line"] and v > best_v:
            best, best_v = m["id"], v
    return best


def resolve(brain, provider: str, seed: str) -> str:
    """Modelo efetivo de uma semente pelo cache (sem rede: quem atualiza é o `catalog`/`follow`)."""
    if not seed or provider not in VENDOR:
        return seed
    ent = ((load_cache(brain).get("providers") or {}).get(provider) or {})
    return newest(seed, ent.get("models") or [])


def record_move(brain, move: dict) -> None:
    data = load_cache(brain)
    data["moves"] = ([move] + list(data.get("moves") or []))[:MOVES_KEPT]
    _save_cache(brain, data)


def moves(brain) -> list[dict]:
    return list(load_cache(brain).get("moves") or [])
