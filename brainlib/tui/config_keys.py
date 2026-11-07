"""Teclas e formulários da face Configurações (provedores da memória, harnesses, saúde).

Mixin do BrainApp — entra ANTES dos demais na MRO e delega face≠2 ao PortfolioKeys via super().
Cada tecla monta uma linha `brain …` (o TUI nunca escreve config na mão); o wizard interativo
abre num terminal suspenso (self.external), o mesmo caminho do $EDITOR.
"""
from __future__ import annotations

import sys

from rich.text import Text

from .. import providers as prov
from .modals import Field, FormSpec


class ConfigKeys:
    # ── contexto de teclas (face 2) ─────────────────────────────────────────
    def ctx_keys_face(self, K: list, p: int, t: int, it, every: bool) -> None:
        if getattr(self, "face", 0) != 2:
            super().ctx_keys_face(K, p, t, it, every)     # Portfólio (face 1)
            return
        from .app import Key
        add = lambda k, label, fn, **kw: K.append(Key(k, label, fn, **kw))  # noqa: E731
        w = lambda cond: every or cond  # noqa: E731
        if p == 1:
            if t == 0:                                    # Provedores
                add("s", "mudar provedor", self.f_providers_set)
                add("w", "wizard da memória", self.f_wizard_memoria)
                if w(it):
                    add("enter", "ficha", self.toggle_zoom)
            else:                                         # Harnesses
                if w(it and it.kind == "hw"):
                    add("i", "cablar" if not it.data["wired"] else "reinstalar",
                        lambda: self.f_harness_install())
                add("v", "verificar conexão", lambda: self.exec(
                    [["memory", "harness", "verify"]], render=False, show="Harnesses"))
                if w(it):
                    add("enter", "ficha", self.toggle_zoom)
        elif p == 2:                                      # Saúde
            if w(it and it.extra.get("fix")):
                add("f", "corrigir", self.fix_doc)
            add("o", "testar online", lambda: self.run_sys("sys:doctor"))
            add("enter", "ampliar", self.toggle_zoom)

    # ── formulários ─────────────────────────────────────────────────────────
    def f_providers_set(self) -> None:
        """Muda um slot (llm · embeddings · reranker) — mesmo caminho do wizard, sem refazer setup."""
        cur = prov.stack(self.store.brain) if self.store else {}

        def provider_opts(v):
            slot = v.get("slot", "embeddings")
            return [(p, info.get("label") or p) for p, info in prov.PROVIDERS[slot].items()]

        def build(v):
            slot = v["slot"]
            c = ["memory", "providers", "set", slot, "--provider", v["provider"]]
            if v.get("model"):
                c += ["--model", v["model"]]
            if v.get("base_url"):
                c += ["--base-url", v["base_url"]]
            if v.get("key"):
                c += ["--key", v["key"]]
            if slot == "llm" and v.get("models"):
                c += ["--models", v["models"]]
            if slot == "reranker" and v.get("candidates"):
                c += ["--candidates", v["candidates"]]
            return [c]

        def res_model(v):
            info = prov.PROVIDERS[v.get("slot", "embeddings")].get(v.get("provider", ""), {})
            if info.get("models"):
                return "recomendados por operação (cenário B): " + " · ".join(
                    f"{op}={m}" for op, m in info["models"].items())
            return info.get("model", "— modelo default do provedor —")

        cur_slot = cur.get("embeddings", {}).get("provider", "local")
        self.form(FormSpec(
            "Provedor da memória",
            [Field("slot", "slot", value="embeddings",
                   choice=[("llm", "LLM — só vale no modo full"),
                           ("embeddings", "embeddings"), ("reranker", "reranker")]),
             Field("provider", "provedor", value=cur_slot, options=provider_opts, depends="slot"),
             Field("model", "modelo", ph="vazio = recomendado do provedor", res=res_model),
             Field("base_url", "base URL", ph="custom / openai-wire",
                   show=lambda v: v.get("provider") == "custom"),
             Field("key", "API key", ph="vazio = mantém a do config/.env",
                   show=lambda v: v.get("provider") not in ("local", "off", "")),
             Field("models", "modelos por operação", ph="retain=…,consolidation=… (vazio = recomendados)",
                   show=lambda v: v.get("slot") == "llm"),
             Field("candidates", "top-N candidatos", ph="vazio = default do provedor",
                   show=lambda v: v.get("slot") == "reranker" and v.get("provider") != "off")],
            build,
            sub="A escolha vai ao config/.env (chave nunca volta em output) e ao [memory]. "
                "Trocou embeddings? vetores antigos ficam incompatíveis — brain memory rebuild. "
                "Depois recrie o container: docker compose -f services/compose.yaml --env-file config/.env up -d",
            render=False, show="Provedores"))

    def f_wizard_memoria(self) -> None:
        """Abre o passo Memória do wizard num terminal suspenso (interativo)."""
        from .bridge import FRAMEWORK
        self.log_line("$ brain setup --only memoria  (terminal interativo)", "cyan")
        self.external([sys.executable, str(FRAMEWORK / "brain"), "setup", "--only", "memoria"])

    def f_harness_install(self) -> None:
        it = self.cur()
        if not (it and it.kind == "hw"):
            return
        name = it.data["name"]
        self.exec([["memory", "harness", "install", name]], render=False,
                  show="Harnesses")
