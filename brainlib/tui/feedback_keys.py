"""Sugestões e bugs do próprio cérebro pela TUI (`FB-####`, porta 7): registrar, publicar, ver a fila.

Mixin do BrainApp. Toda escrita é `./brain …` (a linha aparece no log): `feedback add` registra **e
publica** a issue no repo público do framework — o dono digitando no formulário é a aprovação. Sem
token/rede o item fica pendente e `p` tenta de novo. O texto é público: a porta recusa dado do dono.
Campos iguais aos da CLI: tipo, título, descrição e publicar agora ou depois (`--no-push`); sem campo
de contexto de propósito — refs do vault (TASK/PROC/OPP) não saem para o issue público. Título
repetido do mesmo tipo avisa no formulário e só passa com "criar mesmo assim" (`--force`).
Os campos moram em brainlib/forms.py (`feedback.new`) — os mesmos do painel.
"""

from __future__ import annotations



class FeedbackKeys:
    def f_feedback_new(self) -> None:
        self.open_form("feedback.new")

    def f_feedback_push(self) -> None:
        f = self.cur().data
        self.run_cmds([["feedback", "push", f.id, "--approval", "tui"]])

    def f_feedback_withdraw(self) -> None:
        f = self.cur().data
        if f.status not in ("pendente", "falhou"):
            self.notify(f"{f.id} está {f.status} — retirar vale para rascunho pendente ou falhou", severity="warning")
            return
        self.open_form("feedback.withdraw", {"id": f.id, "title": f.title, "item": vars(f)})

    def f_feedback_retract(self) -> None:
        f = self.cur().data
        if f.status != "criado":
            self.notify(f"{f.id} está {f.status} — retratar vale para issue já criada", severity="warning")
            return
        self.open_form("feedback.retract", {"id": f.id, "title": f.title, "item": vars(f)})

    def f_feedback_sync(self) -> None:
        self.run_cmds([["feedback", "sync"]])
