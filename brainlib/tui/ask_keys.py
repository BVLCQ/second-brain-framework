"""Responder ao agente pela TUI: perguntas `ASK-####`, resposta livre, retomada da sessão e permissões negadas.

Mixin do BrainApp. Toda escrita é `./brain …` (a linha aparece no log). O agente é retomado na mesma sessão
(`claude -p --resume`); se não der, as respostas ficam na fila e o passo 0 do próximo /dump ou /update as aplica.
Permissão negada vira uma pergunta `kind=permissao` com o comando exato; "liberar sempre" grava a regra por
`brain agent allow`. Ferramenta MCP de ESCRITA no mundo exterior nunca é liberada daqui: a pergunta só explica.
"""
from __future__ import annotations

import asyncio
import json
import shlex

from rich.text import Text

from .. import config, util
from . import bridge
from .modals import ConfirmModal, Field, FormSpec, PickerModal, PickItem

OTHER = "outra resposta…"
ALLOW_YES, ALLOW_NO, UNDERSTOOD = "liberar sempre", "não liberar", "entendi"


def rule_for(denial: dict) -> str:
    """A regra de allowlist que cobriria a ferramenta negada (Bash → prefixo do comando; MCP → o próprio nome)."""
    tool, inp = denial.get("tool_name", ""), denial.get("tool_input") or {}
    if tool == "Bash":
        first = str(inp.get("command") or "").splitlines()[0] if inp.get("command") else ""
        try:
            words = shlex.split(first, posix=True)
        except ValueError:                         # aspas que fecham na linha seguinte (texto de várias linhas, heredoc)
            words = first.split()
        words = [w for w in words if w != "<<" and not w.startswith("<<")]
        if not words:
            return "Bash"
        head = " ".join(words[:2]) if words[0].startswith("./") and len(words) > 1 else words[0]
        return f"Bash({head}:*)"
    return tool


def detail_of(denial: dict) -> str:
    inp = denial.get("tool_input") or {}
    if denial.get("tool_name") == "Bash":
        return str(inp.get("command", "")).splitlines()[0][:140] if inp.get("command") else ""
    return json.dumps(inp, ensure_ascii=False)[:140]


def safe_rule(rule: str) -> str:
    """A regra que o TUI pode liberar, normalizada; '' quando não pode: inválida, MCP de escrita no mundo exterior, ou MCP
    amplo demais (servidor inteiro ou curinga, que incluiria as ferramentas de escrita). A regra vem do contexto da pergunta,
    que o agente escreve: aqui ela é conferida de novo, antes do `brain agent allow` e do `--allowedTools` do resume."""
    try:
        rule = config.check_allow_rule(rule)
    except util.BrainError:
        return ""
    if rule.startswith("mcp__") and (rule.count("__") < 2 or "*" in rule or config.is_external_write(rule)):
        return ""
    return rule


def scope_for(rule: str) -> str:
    """MCP de leitura vale para o noturno e o TUI ([runner].allow); o resto só para as ações ⚡ ([tui].agent_allow)."""
    return "runner" if rule.startswith("mcp__") else "tui"


class AskKeys:
    # ── responder ──────────────────────────────────────────────────────────
    def f_answer(self) -> None:
        q = self.cur().data
        if q.status != "aberta":
            return
        if not q.options:
            self._answer_text(q)
            return

        rule, scope = self._allow_rule(q) if q.kind == "permissao" else ("", "")
        where = "[runner].allow" if scope == "runner" else "[tui].agent_allow"

        def label(i: int, o: str) -> Text:
            t = Text.assemble((f"{i}  ", "dim"), (o, "bold"))
            if q.kind == "permissao" and o == ALLOW_YES:           # o dono vê a regra exata que vai gravar, não só o texto do agente
                t.append(f"  → {rule} em {where}" if rule else "  → nada: esta regra não é liberada por aqui", "yellow")
            return t

        def source(text: str) -> list[PickItem]:
            out = [PickItem(label(i, o), o) for i, o in enumerate(q.options, 1)
                   if not text or text.lower() in o.lower()]
            if not text or "outra" in text.lower():
                out.append(PickItem(Text(OTHER, "cyan"), None))
            return out

        def done(item) -> None:
            if item is None:
                return
            if item.data is None:
                self._answer_text(q)
            else:
                self.answer_question(q, item.data)
        self.push_screen(PickerModal(f"{q.id} · {q.text}", "escolha uma opção ou “outra resposta…”", source), done)

    def _answer_text(self, q) -> None:
        self.form(FormSpec(f"Responder {q.id}", [Field("answer", "resposta", req=True, ph="texto livre", multi=False)],
                           lambda v: self._answer_cmds(q, v["answer"] or "…"), sub=q.text,
                           after=lambda: self._after_answer(q)))

    def answer_question(self, q, text: str) -> None:
        self.exec(self._answer_cmds(q, text), after=lambda: self._after_answer(q))

    @staticmethod
    def _allow_rule(q) -> tuple[str, str]:
        """(regra, escopo) que "liberar sempre" gravaria; regra '' quando a pergunta não libera nada (escrita externa, regra
        inválida ou ampla demais), mesmo que a resposta digitada seja "liberar sempre"."""
        rule = next((c[len("allow:"):] for c in q.context if c.startswith("allow:")), "")
        rule = "" if "externo" in q.context else safe_rule(rule)
        return rule, scope_for(rule)

    def _answer_cmds(self, q, text: str) -> list[list[str]]:
        cmds = [["ask", "answer", q.id, text, "--by", "owner"]]
        if q.kind == "permissao":
            rule, scope = self._allow_rule(q)
            if text == ALLOW_YES and rule:
                cmds += [["agent", "allow", rule, "--scope", scope],
                         ["ask", "applied", q.id, "--how", f"regra {rule} liberada em {scope}", "--by", "system"]]
            else:
                cmds.append(["ask", "applied", q.id, "--how", "nada foi liberado" if text != UNDERSTOOD else "o dono leu a explicação", "--by", "system"])
        return cmds

    def f_ask_drop(self) -> None:
        q = self.cur().data
        self.form(FormSpec(f"Descartar {q.id}", [Field("reason", "motivo", req=True, ph="já resolvi / não importa")],
                           lambda v: [["ask", "drop", q.id, "--reason", v["reason"] or "…", "--by", "owner"]], sub=q.text))

    # ── retomar ────────────────────────────────────────────────────────────
    def _after_answer(self, q) -> None:
        """A seleção vai para a próxima pergunta aberta. Respondeu a última da rodada? Oferece retomar o agente na hora;
        senão, as respostas ficam na fila."""
        opens = self.store.open_asks()
        if opens and self.p == 4 and self.tab[4] == 0:
            ids = [i.id for i in self.items(4)]
            if opens[0].id in ids:
                self.set_sel(4, ids.index(opens[0].id))
                self.redraw()
        if not q.run or [x for x in self.store.open_asks() if x.run == q.run]:
            return
        answered = [x for x in self.store.answered_asks() if x.run == q.run]
        if not answered:
            return
        if not self._resumable() or self.last_run.id != q.run:
            self.log_line("respostas na fila: o próximo /update ou ⚡ as aplica no passo 0 (a sessão do agente que perguntou não está mais aqui)", "yellow")
            return
        body = "\n".join(f"{x.id} = {x.answer}" for x in answered)
        self.push_screen(ConfirmModal("Retomar o agente agora?", "Todas as perguntas desta rodada foram respondidas:\n" + body),
                         lambda ok: self.resume_now(answered) if ok else self.log_line("respostas na fila: o próximo /update ou ⚡ as aplica (passo 0)", "dim"))

    def _resumable(self) -> bool:
        return bool(self.last_run and self.last_run.session_id)

    def resume_with_answers(self) -> None:
        pend = self.store.answered_asks()
        if not pend:
            self.log_line("nenhuma resposta aguardando o agente (responda uma pergunta primeiro)", "dim")
            return
        if not self._resumable():
            self.log_line("sem sessão do agente para retomar: as respostas ficam na fila e o próximo /update ou ⚡ as aplica (passo 0)", "yellow")
            return
        self.resume_now(pend)

    def resume_now(self, answered, free_text: str = "") -> None:
        if not self._resumable():
            self.log_line("sem sessão para retomar: as respostas ficam na fila (passo 0 do próximo /update ou ⚡)", "yellow")
            return
        lines = "; ".join(f"{x.id} = {x.answer}" for x in answered)
        prompt = ((f"O dono respondeu: {lines}. " if lines else "") + (free_text + " " if free_text else "")
                  + "Aplique (passo 0) e continue de onde parou.").strip()
        extra = [r for r in (self._allow_rule(x)[0] for x in answered if x.answer == ALLOW_YES) if r]
        run_id = bridge.new_run_id()
        argv = bridge.resume_argv(self.inst.cfg, self.last_run.session_id, prompt, extra, run_id)
        if argv is None:
            self.log_line("este agente não retoma sessão: as respostas ficam na fila (passo 0 do próximo /update ou ⚡)", "yellow")
            return
        self.pending_reply = False
        self.run_worker(self._agent(argv, prompt, run_id, resumed_from=self.last_run.id), exclusive=False)

    def free_reply(self) -> None:
        """Resposta livre (tecla r quando o agente deixou algo, ou pela paleta): continua a conversa na mesma sessão."""
        def build(v):
            return [["note", "add", "--text", v["text"] or "…"]] if not self._resumable() else []

        def intercept(v) -> bool:
            text = v["text"]
            if self._resumable():
                self.resume_now(self.store.answered_asks(), free_text=text)
            else:
                self.log_line("sem sessão do agente para retomar: gravei como nota para o próximo /update ler", "yellow")
                self.exec([["note", "add", "--text", text]])
            return True
        sub = ("Continua a conversa do agente na mesma sessão." if self._resumable()
               else "Não há sessão do agente para retomar: o texto vira uma nota na inbox (o próximo /update lê).")
        self.form(FormSpec("Resposta livre ao agente", [Field("text", "resposta", req=True, multi=True, ph="o que o agente deve saber ou fazer")],
                           build, sub=sub, intercept=intercept, render=False))

    # ── depois de cada rodada ⚡ ───────────────────────────────────────────
    async def after_run(self, info) -> None:
        """Negações viram perguntas; o log diz, em uma linha acionável, o que o agente deixou para o dono."""
        for d in self._unique_denials(info.denials):
            rule = rule_for(d)
            external = config.is_external_write(rule)
            if external:
                text = (f"O agente tentou usar {d.get('tool_name')} ({detail_of(d)}), que escreve no mundo exterior. "
                        "Isso não é liberado por aqui: enviar, postar, criar ou mover passa pelas portas (/outbox, /publish, /focus), cada uma com o seu gate.")
                opts, ctx = [UNDERSTOOD], [f"allow:{rule}", "externo"]
            else:
                text = f"O agente não pôde usar {d.get('tool_name')}: {detail_of(d) or rule}. Liberar sempre?"
                opts, ctx = [ALLOW_YES, ALLOW_NO], [f"allow:{rule}"]
            args = ["ask", "add", text, "--kind", "permissao", "--run", info.id, "--prov", "observado", "--source", f"logs/agent-runs.jsonl#{info.id}",
                    "--by", "agent", "--context", ",".join(ctx)]
            for o in opts:
                args += ["--option", o]
            res = await asyncio.to_thread(bridge.run_brain, self.inst, args)
            self.log_line("$ " + bridge.display(args[:3]) + " …", "dim")
            if not res.ok:
                self.log_line(res.err or "não consegui registrar a permissão negada", "red")

    @staticmethod
    def _unique_denials(denials: list[dict]) -> list[dict]:
        seen, out = set(), []
        for d in denials:
            key = (d.get("tool_name"), json.dumps(d.get("tool_input"), sort_keys=True, default=str))
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out

    def report_run(self, info) -> None:
        asks = [self.store.brain.state.questions[i] for i in info.asks if i in self.store.brain.state.questions]
        asks = [q for q in asks if q.status == "aberta"]
        perms = [q for q in asks if q.kind == "permissao"]
        qs = [q for q in asks if q.kind != "permissao"]
        if not asks:
            return
        parts = []
        if qs:
            parts.append(f"{len(qs)} pergunta{'s' if len(qs) != 1 else ''}")
        if perms:
            parts.append(f"{len(perms)} permissão{'ões' if len(perms) != 1 else ''} negada{'s' if len(perms) != 1 else ''}")
        self.pending_reply = bool(info.session_id)
        self.log_line(f"⚠ o agente deixou {' e '.join(parts)} · {len(asks)} para responder (painel 4 › Perguntas)"
                      + (" · r resposta livre" if self.pending_reply else ""), "yellow")
