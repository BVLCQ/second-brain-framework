"""Teclas e formulários da face Configurações (provedores da memória, harnesses, saúde).

Mixin do BrainApp — entra ANTES dos demais na MRO e delega face≠2 ao PortfolioKeys via super().
Cada tecla monta uma linha `brain …` (o TUI nunca escreve config na mão); o wizard interativo
abre num terminal suspenso (self.external), o mesmo caminho do $EDITOR.
"""
from __future__ import annotations

import sys

from .. import providers as prov


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
                    add("i", "conectar" if not it.data["wired"] else "reinstalar",
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
        self.open_form("memory.provider", {"provider": cur.get("embeddings", {}).get("provider", "local")},
                       render=False, show="Provedores")

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
