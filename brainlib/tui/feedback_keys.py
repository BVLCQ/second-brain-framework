"""Sugestões e bugs do próprio cérebro pela TUI (`FB-####`, porta 7): registrar, publicar, ver a fila.

Mixin do BrainApp. Toda escrita é `./brain …` (a linha aparece no log): `feedback add` registra **e
publica** a issue no repo público do framework — o dono digitando no formulário é a aprovação. Sem
token/rede o item fica pendente e `p` tenta de novo. O texto é público: a porta recusa dado do dono.
"""

from __future__ import annotations

KINDS = [("sugestao", "💡 sugestão"), ("bug", "🐞 bug")]


class FeedbackKeys:
    def f_feedback_new(self) -> None:
        from .modals import Field, FormSpec
        self.form(FormSpec("Sugestão ou bug", [
            Field("kind", "Tipo", choice=KINDS),
            Field("title", "Título", req=True, ph="curto e claro"),
            Field("body", "Descrição", multi=True, ph="o que, onde, como reproduzir")],
            lambda v: [["feedback", "add", v["title"] or "…", "--kind", v["kind"],
                        *(["--body", v["body"]] if v.get("body") else []), "--by", "owner"]],
            sub="porta 7 — vira issue pública no repo do framework; sem dados pessoais (a porta recusa)"))

    def f_feedback_push(self) -> None:
        f = self.cur().data
        self.exec([["feedback", "push", f.id]])
