"""Sugestões e bugs do próprio cérebro pela TUI (`FB-####`, porta 7): registrar, publicar, ver a fila.

Mixin do BrainApp. Toda escrita é `./brain …` (a linha aparece no log): `feedback add` registra **e
publica** a issue no repo público do framework — o dono digitando no formulário é a aprovação. Sem
token/rede o item fica pendente e `p` tenta de novo. O texto é público: a porta recusa dado do dono.
Campos iguais aos da CLI: tipo, título, descrição, contexto (`--context`), publicar agora ou depois
(`--no-push`); título repetido do mesmo tipo avisa no formulário e só passa com "criar mesmo assim"
(`--force`).
"""

from __future__ import annotations

from .. import util

KINDS = [("sugestao", "💡 sugestão"), ("bug", "🐞 bug")]
PUB = [("agora", "agora — cria a issue já"), ("depois", "depois — só registra (--no-push)")]


class FeedbackKeys:
    def _fb_dup(self, vals: dict):
        """FB existente com mesmo tipo+título (a mesma comparação do CLI) — None se não há."""
        key = " ".join(util.fold(vals.get("title") or "").split())
        if not key:
            return None
        kind = vals.get("kind") or "sugestao"
        return next((f for f in self.store.brain.state.feedbacks.values()
                     if f.kind == kind and " ".join(util.fold(f.title).split()) == key), None)

    def f_feedback_new(self) -> None:
        from .modals import Field, FormSpec

        def title_check(_v, vals):
            f = self._fb_dup(vals)
            if f and vals.get("force") != "sim":
                return (f"mesmo título e tipo de {f.id} — acrescente detalhe ao existente "
                        f"(`brain feedback show {f.id}`) ou marque “criar mesmo assim”")
            return ""

        self.form(FormSpec("Sugestão ou bug", [
            Field("kind", "Tipo", choice=KINDS),
            Field("title", "Título", req=True, ph="curto e claro", check=title_check),
            Field("body", "Descrição", multi=True, ph="o que, onde, como reproduzir"),
            Field("context", "Contexto", ph="TASK-####, PROC-####, OPP-#### (vírgula ou repetido)"),
            Field("pub", "Publicar", choice=PUB),
            Field("force", "Criar mesmo assim", choice=[("nao", "não"), ("sim", "sim (--force)")],
                  show=lambda v: self._fb_dup(v) is not None)],
            lambda v: [["feedback", "add", v["title"] or "…", "--kind", v["kind"],
                        *(["--body", v["body"]] if v.get("body") else []),
                        *(["--context", v["context"]] if v.get("context") else []),
                        *(["--no-push"] if v.get("pub") == "depois" else []),
                        *(["--force"] if v.get("force") == "sim" else []),
                        "--by", "owner"]],
            sub="porta 7 — vira issue pública no repo do framework; sem dados pessoais (a porta recusa)"))

    def f_feedback_push(self) -> None:
        f = self.cur().data
        self.exec([["feedback", "push", f.id]])

    def f_feedback_sync(self) -> None:
        self.exec([["feedback", "sync"]])
