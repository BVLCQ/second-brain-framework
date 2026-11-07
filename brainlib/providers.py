"""Provedores da memória — LLM · embeddings · reranker (plano guides/plans/memory-providers.md).

Escolha do dono, gravada em três lugares coerentes:
  • config/.env  — o segredo e a "wire" (HINDSIGHT_API_*) que o compose lê (nunca volta em output);
  • [memory]     — a ESCOLHA (provedor/modelo) para status, painel e doctor: llm_provider,
                   embeddings_provider, reranker_provider… nunca chave;
  • compose      — sobe com --env-file config/.env; a base interpola ${VAR:-default}.

Curadoria: poucos provedores testáveis por slot + `custom` via base_url compatível.
`jina-mlx` fica fora do menu — benchmark 2026-11-07 reprovou no gate de latência (§4.2 do
plano da memória). Reranker de nuvem e embeddings de nuvem mandam texto do vault para fora:
o wizard diz isso na tela e o doctor narra enquanto ativos.
"""
from __future__ import annotations

import json

from . import config, util

SLOTS = ("llm", "embeddings", "reranker")

# LLM por operação (cenário B do plano da memória): barato no alto volume, maior na síntese.
LLM_OPS = (("retain", "RETAIN_LLM_MODEL"), ("consolidation", "CONSOLIDATION_LLM_MODEL"),
           ("mental_models", "MENTAL_MODEL_REFRESH_LLM_MODEL"), ("reflect", "REFLECT_LLM_MODEL"),
           ("default", "LLM_MODEL"))

_EMB = "HINDSIGHT_API_EMBEDDINGS_"
_RER = "HINDSIGHT_API_RERANKER_"

# key_env: onde a chave mora no .env (para o doctor conferir presença, nunca valor).
PROVIDERS: dict[str, dict[str, dict]] = {
    "llm": {
        "anthropic": {"label": "Anthropic", "recommended": True,
                      "models": {"retain": "claude-haiku-5-5", "consolidation": "claude-haiku-5-5",
                                 "mental_models": "claude-sonnet-5-5", "reflect": "claude-sonnet-5-5",
                                 "default": "claude-haiku-5-5"},
                      "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "openai": {"label": "OpenAI", "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "fireworks": {"label": "Fireworks", "recommended": True, "model": "accounts/fireworks/models/deepseek-v4p1-flash",
                      "base_url": "https://api.fireworks.ai/inference/v1", "wire": "openai",
                      "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "zai": {"label": "Z.ai (GLM, plano coding)", "base_url": "https://api.z.ai/api/coding/paas/v4",
                "wire": "openai", "key_env": "HINDSIGHT_API_LLM_API_KEY"},
        "lmstudio": {"label": "LM Studio (local, sem chave)", "local": True,
                     "base_url": "http://host.docker.internal:1234/v1", "key_env": ""},
        "custom": {"label": "Outro (OpenAI-compatível)", "wire": "openai", "key_env": "HINDSIGHT_API_LLM_API_KEY"},
    },
    "embeddings": {
        "local": {"label": "Local — LM Studio bge-m3 (zero egress)", "recommended": True, "local": True,
                  "model": "text-embedding-bge-m3", "base_url": "http://host.docker.internal:1234/v1",
                  "key_env": ""},
        "fireworks": {"label": "Fireworks — Qwen3-Embedding-8B", "recommended_cloud": True,
                      "model": "fireworks/qwen3-embedding-8b", "dimensions": 1536,
                      "base_url": "https://api.fireworks.ai/inference/v1", "wire": "openai",
                      "key_env": _EMB + "OPENAI_API_KEY"},
        "openai": {"label": "OpenAI", "model": "text-embedding-3-small", "wire": "openai",
                   "key_env": _EMB + "OPENAI_API_KEY"},
        "cohere": {"label": "Cohere", "model": "embed-multilingual-v3.0", "wire": "cohere",
                   "key_env": _EMB + "COHERE_API_KEY"},
        "custom": {"label": "Outro (OpenAI-compatível)", "wire": "openai", "key_env": _EMB + "OPENAI_API_KEY"},
    },
    "reranker": {
        "off": {"label": "Desligado — fusão RRF (recomendado; veredito 2026-11-07)", "recommended": True},
        "fireworks": {"label": "Fireworks — Qwen3-Reranker-8B", "recommended_cloud": True,
                      "model": "fireworks_ai/fireworks/qwen3-reranker-8b", "wire": "litellm-sdk",
                      "base_url": "https://api.fireworks.ai/inference/v1", "candidates": 50,
                      "key_env": _RER + "LITELLM_SDK_API_KEY"},
        "cohere": {"label": "Cohere", "model": "rerank-v3.5", "wire": "cohere", "key_env": _RER + "COHERE_API_KEY"},
        "zeroentropy": {"label": "ZeroEntropy", "model": "zerank-2", "wire": "zeroentropy",
                        "key_env": _RER + "ZEROENTROPY_API_KEY"},
        "openrouter": {"label": "OpenRouter", "model": "cohere/rerank-v3.5", "wire": "openrouter",
                       "key_env": _RER + "OPENROUTER_API_KEY"},
        "custom": {"label": "Outro (endpoint compatível com Cohere /rerank — Jina, Voyage, BGE próprio…)",
                   "wire": "cohere", "key_env": _RER + "COHERE_API_KEY"},
    },
}

CLOUD_FLAGS = {"embeddings": "cloud_embeddings", "reranker": "cloud_reranker"}


def _emb_env(p: dict, model: str, base_url: str, dimensions: int, key: str) -> dict:
    env: dict[str, str] = {}
    wire = p.get("wire", "openai")
    env[_EMB + "PROVIDER"] = wire
    pref = _EMB + ("OPENAI_" if wire == "openai" else wire.upper() + "_")
    env[pref + "MODEL"] = model
    if wire == "openai":
        env[pref + "BASE_URL"] = base_url or p.get("base_url", "")
    dimensions = dimensions or p.get("dimensions", 0)
    if dimensions:
        env[pref + "DIMENSIONS"] = str(dimensions)
    if key:
        env[p.get("key_env", pref + "API_KEY")] = key
    return env


def _rer_env(p: dict, model: str, base_url: str, candidates: int, key: str) -> dict:
    if p is PROVIDERS["reranker"]["off"]:
        return {_RER + "PROVIDER": "rrf"}
    env = {_RER + "PROVIDER": p["wire"]}
    pref = _RER + p["wire"].upper().replace("-", "_") + "_"
    env[pref + "MODEL"] = model
    if p["wire"] == "litellm-sdk":
        env[_RER + "LITELLM_SDK_API_BASE"] = base_url or p.get("base_url", "")
    elif base_url:
        env[pref + "BASE_URL"] = base_url
    candidates = candidates or p.get("candidates", 0)
    if candidates:
        env[_RER + "MAX_CANDIDATES"] = str(candidates)
    if key:
        env[p.get("key_env", pref + "API_KEY")] = key
    return env


def slot_env(slot: str, provider: str, *, model: str = "", models: dict | None = None,
             base_url: str = "", dimensions: int = 0, candidates: int = 0, key: str = "") -> dict:
    """Env do .env para a escolha (sem tocar disco). Valores vazios caem fora — segredo nunca ecoa."""
    p = PROVIDERS[slot][provider]
    if slot == "llm":
        env = {"HINDSIGHT_API_LLM_PROVIDER": "lmstudio" if p.get("local") else ("openai" if p.get("wire") == "openai" else provider)}
        if p.get("local") or p.get("wire") == "openai":
            env["HINDSIGHT_API_LLM_BASE_URL"] = base_url or p.get("base_url", "")
        ops = models or {}
        for op, envk in LLM_OPS:
            m = ops.get(op) or (model if op == "default" else "")
            if m:
                env[f"HINDSIGHT_API_{envk}"] = m
        if p.get("local"):
            env.setdefault("HINDSIGHT_API_LLM_API_KEY", "lm-studio")
        elif key:
            env[p["key_env"]] = key
        return env
    if slot == "embeddings":
        return _emb_env(p, model or p.get("model", ""), base_url, dimensions, key)
    return _rer_env(p, model or p.get("model", ""), base_url, candidates, key)


def set_slot(brain, slot: str, provider: str, *, model: str = "", models: dict | None = None,
             base_url: str = "", dimensions: int = 0, candidates: int = 0, key: str = "") -> dict:
    """Grava a escolha: .env (wire + chave) + [memory] (provedor/modelo/flags). Devolve o resumo."""
    if slot not in SLOTS:
        raise util.BrainError(f"slot inválido: {slot!r} — use {', '.join(SLOTS)}", code=4)
    if provider not in PROVIDERS[slot]:
        raise util.BrainError(f"provedor inválido para {slot}: {provider!r} — "
                              f"{', '.join(PROVIDERS[slot])}", code=4)
    p = PROVIDERS[slot][provider]
    if slot == "llm" and provider != "lmstudio" and not (models or model):
        rec = PROVIDERS["llm"]["anthropic"]["models"] if provider == "anthropic" else {}
        if not rec:
            raise util.BrainError(f"provedor {provider!r} precisa de --model (ou --models por operação)", code=4)
    if slot == "embeddings" and provider in ("custom",) and not (model and (base_url or p.get("base_url"))):
        raise util.BrainError("embeddings custom exige --model e --base-url", code=4)

    mem = brain.inst.cfg["memory"]
    prev = {"provider": mem.get(f"{slot}_provider", ""), "model": mem.get(f"{slot}_model", "")}
    if slot == "llm" and not (models or model) and p.get("models"):
        models = dict(p["models"])              # recomendados por operação (cenário B) como default
    env_updates = slot_env(slot, provider, model=model, models=models, base_url=base_url,
                           dimensions=dimensions, candidates=candidates, key=key)
    from .setup import set_env                     # lazy: setup importa memory em tempo de execução
    changed_env = set_env(brain.inst, env_updates)

    cfg_updates: dict = {f"{slot}_provider": provider}
    if slot == "llm":
        cfg_updates["llm_models"] = ",".join(f"{op}={m}" for op, m in (models or {}).items() if m) \
            if models else ("" if provider == "lmstudio" else model)
    else:
        if model or p.get("model"):
            cfg_updates[f"{slot}_model"] = model or p.get("model", "")
        if base_url or (provider not in ("local",) and p.get("base_url")):
            cfg_updates[f"{slot}_base_url"] = base_url or p.get("base_url", "")
        if slot == "embeddings" and (dimensions or p.get("dimensions")):
            cfg_updates["embeddings_dimensions"] = dimensions or p.get("dimensions", 0)
        if slot == "reranker" and (candidates or p.get("candidates")):
            cfg_updates["reranker_max_candidates"] = candidates or p.get("candidates", 0)
    flag = CLOUD_FLAGS.get(slot)
    if flag:
        cfg_updates[flag] = provider not in ("local", "off")
    changed_cfg = config.set_keys(brain.inst, "memory", cfg_updates)
    from .core import Brain                       # recarga completa (lição do _apply_mode)
    brain.inst = config.load(brain.inst.root)
    brain.reload()

    rebuild = (slot == "embeddings"
               and mem.get("engine") == "hindsight"
               and (prev["provider"] != provider or (prev["model"] and prev["model"] != (model or p.get("model", ""))))
               and (brain.inst.root / ".memory-state.json").exists())
    return {"slot": slot, "provider": provider, "label": p["label"],
            "cloud": bool(flag and cfg_updates.get(flag)) or (slot == "llm" and provider not in ("lmstudio",)),
            "env": sorted(changed_env), "cfg": sorted(changed_cfg), "rebuild_needed": rebuild}


def stack(brain) -> dict:
    """O stack atual, para status/TUI/painel/doctor. Chaves: só presença, nunca valor."""
    mem = brain.inst.cfg["memory"]
    env = config.load_env(brain.inst)
    out: dict = {}
    for slot in SLOTS:
        provider = mem.get(f"{slot}_provider", "") or ("off" if slot == "reranker" else
                                                       "local" if slot == "embeddings" else "")
        p = PROVIDERS[slot].get(provider, {})
        if slot == "llm":
            models = mem.get("llm_models", "")
            detail = models if models else (p.get("models") and "recomendados (cenário B)") or (p.get("model") or "")
        else:
            detail = mem.get(f"{slot}_model", "") or p.get("model", "") or ("—" if provider == "off" else "")
        kenv = p.get("key_env", "")
        out[slot] = {"provider": provider, "label": p.get("label", provider), "model": detail,
                     "cloud": (slot != "llm" and provider not in ("local", "off"))
                              or (slot == "llm" and provider not in ("", "lmstudio")),
                     "key_env": kenv, "key_present": bool(kenv and env.get(kenv)),
                     "local": bool(p.get("local"))}
    return out


def _fmt_models(s: str) -> str:
    return s.replace(",", " · ") if s else ""


def cli(args, brain) -> None:
    if getattr(args, "pcmd", "") == "set":
        res = set_slot(brain, args.slot, args.provider, model=args.model or "",
                       models=_parse_models(args.models) if args.models else None,
                       base_url=args.base_url or "", dimensions=args.dimensions or 0,
                       candidates=args.candidates or 0, key=args.key or "")
        print(f"✓ {res['slot']} → {res['label']}")
        if res["env"]:
            print(f"  .env: {', '.join(res['env'])} (valor não impresso)")
        if res["cfg"]:
            print(f"  [memory]: {', '.join(res['cfg'])}")
        if res["cloud"]:
            print("  ⚠ egress: texto do vault vai para a API do provedor — recreate do container "
                  "aplica (docker compose -f services/compose.yaml --env-file config/.env up -d)")
        if res["rebuild_needed"]:
            print("  ⚠ embeddings mudaram: vetores antios são incompatíveis — `brain memory rebuild` "
                  "re-deriva tudo do vault")
        return
    st = stack(brain)
    if getattr(args, "json", False):
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return
    icons = {"llm": "LLM (extração/consolidação/mental models)", "embeddings": "Embeddings",
             "reranker": "Reranker"}
    for slot in SLOTS:
        s = st[slot]
        key = " · chave ok" if s["key_present"] else (" · sem chave" if s["key_env"] else "")
        cloud = " · ☁ egress" if s["cloud"] else (" · local" if s["local"] else "")
        name = s["label"] or "—"
        print(f"{icons[slot]}: {name}{cloud}{key}")
        if s["model"] and s["model"] != "—":
            print(f"  modelo: {_fmt_models(s['model'])}")


def _parse_models(spec: str) -> dict:
    """`retain=m1,consolidation=m2` → dict (ops válidas do LLM_OPS)."""
    out: dict = {}
    for part in spec.split(","):
        op, sep, m = part.partition("=")
        op = op.strip()
        if not sep or op not in dict(LLM_OPS) or not m.strip():
            raise util.BrainError(f"--models aceita {','.join(op for op, _ in LLM_OPS)} — veio {part!r}", code=4)
        out[op] = m.strip()
    return out
