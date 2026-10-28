"""Teclas e formulários da face Portfólio (processos, oportunidades, áreas, documentos).

Mixin do BrainApp: cada tecla monta uma linha `brain …` (mostrada no log antes de rodar); o TUI nunca escreve no
ledger por conta própria. Promover é o gate estrutural: mostra o diff do goals.md e pede a resposta literal do dono.
"""
from __future__ import annotations

import re
import webbrowser

from rich.text import Text

from .. import people as people_mod
from .. import portfolio, util, watch
from ..cli_portfolio import promote_proposal
from ..schema import DOC_KINDS, OPP_KINDS, OPP_REASON_STATUS, RECURRENCE
from .modals import ConfirmModal, Field, FormSpec, PickerModal, PickItem
from . import rows

STATUS_ORDER = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue", "em-espera", "descartada"]
NONE = "—"                                          # opção "sem valor" dos campos de escolha


class PortfolioKeys:
    # ── contexto de teclas ─────────────────────────────────────────────────
    def ctx_keys_face(self, K: list, p: int, t: int, it, every: bool) -> None:
        from .app import Key
        add = lambda k, label, fn, **kw: K.append(Key(k, label, fn, **kw))  # noqa: E731
        w = lambda cond: every or cond  # noqa: E731
        if p in (1, 4):
            add("o", "mapa HTML", lambda: self.run_sys("sys:openpf"))
        if p == 2:
            add("n", "novo", self.f_proc_new)
            if w(it and it.kind == "proc"):
                add("e", "editar", self.f_proc_edit)
                add("l", "ligar doc", lambda: self.f_doc_link(it.id))
                add("o", "abrir playbook", self.open_playbook)
                add("a", "nova oportunidade", self.f_opp_from_proc)
                add("x", "aposentar", self.f_proc_retire)
        elif p == 3:
            add("n", "nova", lambda: self.f_opp_new())
            if w(it and it.kind == "opp"):
                add("e", "editar", self.f_opp_edit)
                add("s", "status", self.pick_status)
                add("i", "ICE", self.f_ice)
                if w(it and it.data["ice_suggested"]):
                    add("c", "confirmar ICE", self.confirm_ice)
                add("l", "ligar doc", lambda: self.f_doc_link(it.id))
                add("v", "evidência", self.f_evidence)
                add("O", "one-pager", self.agent_onepager, agent=True)
                if w(it and not it.data["project"]):
                    add("p", "promover", self.f_promote, gate=True)
                if w(it and it.data["status"] not in ("descartada", "entregue")):
                    add("x", "descartar", self.f_opp_discard)
        elif p == 4 and t == 1:
            if w(it and it.kind == "opp"):
                add("s", "status", self.pick_status)
                add("i", "ICE", self.f_ice)
        elif p == 5:
            if t == 0:
                add("n", "nova", self.f_area_new)
                if w(it):
                    add("e", "editar", self.f_area_edit)
            elif w(it):
                add("enter", "abrir", self.open_current_doc)
                add("u", "desligar", self.f_doc_unlink)

    # ── apoio ──────────────────────────────────────────────────────────────
    def _area_ids(self) -> list[str]:
        return list(self.store.by_area)

    def _need_area(self) -> bool:
        """Processo e oportunidade pedem uma área cadastrada; sem nenhuma, leva ao cadastro."""
        if self.store.by_area:
            return True
        self.log_line("Cadastre uma área primeiro (painel 5 › Áreas, tecla n).", "yellow")
        self.face, self.p, self.tab[5] = 1, 5, 0
        self.redraw()
        self.f_area_new()
        return False

    def _people_check(self, v: str) -> str:
        for name in util.split_csv(v):
            if name in self.store.brain.state.people:
                continue
            cands = people_mod.resolve(self.store.brain.state, name)
            if not cands:
                return f"pessoa '{name}' não encontrada. Cadastre em Execução › Registro › Pessoas."
            if len(cands) > 1:
                return f"'{name}' é ambíguo: {', '.join(cands)}."
        return ""

    @staticmethod
    def _num_check(v: str) -> str:
        try:
            ok = float(v.replace(",", ".")) > 0
        except ValueError:
            ok = False
        return "" if ok else "Use um número maior que zero."

    @staticmethod
    def _num(v: str) -> str:
        return str(float(v.replace(",", ".")))

    @staticmethod
    def _dur_check(v: str) -> str:
        try:
            return "" if (util.parse_duration(v) or 0) > 0 else "Use uma duração maior que zero (45m, 1h30m)."
        except util.BrainError as e:
            return str(e)

    @staticmethod
    def _scale_check(v: str) -> str:
        return "" if v.isdigit() and 1 <= int(v) <= 5 else "Use um inteiro de 1 a 5."

    def _proc_check(self, v: str) -> str:
        return "" if v in self.store.by_proc else f"{v} não existe (use PROC-####)."

    def _goal_check(self, v: str) -> str:
        return "" if v in self.store.by_goal else f"{v} não existe no PLANNING (use GOAL-#)."

    def _choice(self, v: str) -> str:
        return "" if v == NONE else v

    # ── processos ──────────────────────────────────────────────────────────
    def _proc_fields(self, d: dict | None = None) -> list[Field]:
        d = d or {}
        rec = [NONE, *sorted(RECURRENCE)]
        area = d.get("area") if d.get("area") in self.store.by_area else self._area_ids()[0]
        return [
            Field("title", "título", value=d.get("title", ""), req=True, ph="Fechamento mensal"),
            Field("area", "área", choice=self._area_ids(), value=area),
            Field("owner", "responsável", value=d.get("owner") or "", ph="id ou alias da pessoa (1)", check=self._people_check),
            Field("executors", "executores", value=", ".join(d.get("executors") or []), ph="ids ou aliases, vírgula", check=self._people_check),
            Field("recurrence", "recorrência", choice=rec, value=d.get("recurrence") or NONE),
            Field("per_month", "execuções/mês", value=f"{d['per_month']:g}" if d.get("per_month") else "",
                  ph="só sob-demanda / por-evento", check=self._num_check),
            Field("duration", "duração", value=util.fmt_duration(d["duration_min"]).replace("min", "m") if d.get("duration_min") else "",
                  ph="por execução: 45m · 1h30m", check=self._dur_check),
            Field("tools", "ferramentas", value=", ".join(d.get("tools") or []), ph="Sheets, Jira"),
            Field("io", "entradas → saídas", value=d.get("io") or "", ph="planilha de vendas → relatório fechado"),
            Field("pain", "dor", ph="uma dor a adicionar (opcional)"),
            Field("maturity", "maturidade", value=str(d["maturity"]) if d.get("maturity") else "", ph="1–5", check=self._scale_check),
            Field("note", "nota", ph="opcional")]

    def _proc_args(self, v: dict, old: dict | None) -> list[str]:
        """Opções da CLI para os campos que mudaram (no cadastro novo, todos os preenchidos)."""
        old = old or {}
        c: list[str] = []
        pairs = (("--area", v["area"], old.get("area") or ""), ("--owner", v["owner"], old.get("owner") or ""),
                 ("--executor", v["executors"], ", ".join(old.get("executors") or [])),
                 ("--recurrence", self._choice(v["recurrence"]), old.get("recurrence") or ""),
                 ("--tools", v["tools"], ", ".join(old.get("tools") or [])), ("--io", v["io"], old.get("io") or ""),
                 ("--maturity", v["maturity"], str(old.get("maturity") or "")))
        for opt, new, was in pairs:
            if new and new != was:
                c += [opt, new]
        if v["per_month"] and (not old.get("per_month") or float(v["per_month"].replace(",", ".")) != old["per_month"]):
            c += ["--per-month", self._num(v["per_month"])]
        was_dur = util.fmt_duration(old["duration_min"]).replace("min", "m") if old.get("duration_min") else ""
        if v["duration"] and v["duration"] != was_dur:
            c += ["--duration", v["duration"]]
        for opt, key in (("--pain", "pain"), ("--note", "note")):
            if v[key]:
                c += [opt, v[key]]
        return c

    def f_proc_new(self) -> None:
        if not self._need_area():
            return
        self.form(FormSpec("Novo processo", self._proc_fields(),
                           lambda v: [["process", "add", v["title"] or "…", "--by", "owner", *self._proc_args(v, None)]],
                           sub="Horas/mês = execuções/mês × duração × nº de executores; quem calcula é o CLI.",
                           after=lambda: self._after_new("PROC-")))

    def f_proc_edit(self) -> None:
        p = self.cur().data

        def build(v):
            c = ["process", "update", p["id"], "--by", "owner"]
            if v["title"] != p["title"]:
                c += ["--title", v["title"]]
            return [c + self._proc_args(v, p)]

        self.form(FormSpec(f"Editar {p['id']}", self._proc_fields(p), build,
                           sub="Só o que mudou vai para a CLI. Executores e ferramentas substituem a lista; dor e nota são acrescentadas."))

    def f_proc_retire(self) -> None:
        p = self.cur().data
        self.form(FormSpec(f"Aposentar {p['id']}", [Field("reason", "motivo", req=True, ph="deixou de existir")],
                           lambda v: [["process", "retire", p["id"], "--reason", v["reason"] or "…", "--by", "owner"]],
                           sub=p["title"]))

    def open_playbook(self) -> None:
        p = self.cur().data
        pb = p["playbook"]
        if not pb:
            self.log_line(f"{p['id']} não tem playbook ligado (tecla l, tipo playbook).", "yellow")
            return
        self.open_doc(p["id"], next(n for n, d in enumerate(p["docs"]) if d["ref"] == pb["ref"]))

    def f_opp_from_proc(self) -> None:
        p = self.cur().data
        self.f_opp_new({"area": p["area"], "process": p["id"]})

    # ── oportunidades ──────────────────────────────────────────────────────
    def _opp_fields(self, d: dict | None = None) -> list[Field]:
        d = d or {}
        area = d.get("area") if d.get("area") in self.store.by_area else self._area_ids()[0]
        return [
            Field("title", "título", value=d.get("title", ""), req=True, ph="Automatizar a conciliação"),
            Field("area", "área", choice=self._area_ids(), value=area),
            Field("process", "processo", value=d.get("process") or "", ph="PROC-#### (opcional)", check=self._proc_check),
            Field("kind", "tipo", choice=sorted(OPP_KINDS), value=d.get("kind") or "melhoria-de-processo"),
            Field("problem", "problema", value=d.get("problem") or ""),
            Field("suggestion", "sugestão", value=d.get("suggestion") or ""),
            Field("gain", "ganho esperado", value=d.get("gain") or "", ph="texto livre"),
            Field("hours", "horas/mês poupadas", value=f"{d['hours_saved']:g}" if d.get("hours_saved") else "", ph="declarado por você (opcional)",
                  check=self._num_check),
            Field("goal", "goal", value=d.get("goal") or "", ph="GOAL-# (opcional)", check=self._goal_check),
            Field("people", "pessoas", ph="ids ou aliases, vírgula (opcional)", check=self._people_check)]

    def _opp_args(self, v: dict, old: dict | None) -> list[str]:
        old = old or {}
        c: list[str] = []
        for opt, key in (("--area", "area"), ("--process", "process"), ("--kind", "kind"), ("--problem", "problem"),
                         ("--suggestion", "suggestion"), ("--gain", "gain"), ("--goal", "goal")):
            if v[key] and v[key] != (old.get(key) or ""):
                c += [opt, v[key]]
        if v["hours"] and (not old.get("hours_saved") or float(v["hours"].replace(",", ".")) != old["hours_saved"]):
            c += ["--hours-saved", self._num(v["hours"])]
        if v["people"]:
            c += ["--person", v["people"]]
        return c

    def f_opp_new(self, pre: dict | None = None) -> None:
        if not self._need_area():
            return
        build = lambda v, force=False: [["opportunity", "add", v["title"] or "…", "--by", "owner",  # noqa: E731
                                         *self._opp_args(v, None), *(["--force"] if force else [])]]

        def intercept(v: dict) -> bool:
            dups = portfolio.duplicates(v["title"], v["problem"], self.store.brain.state.opportunities.values())
            if not dups:
                return False
            body = "\n".join(f"{o.id} ({o.status}) · {o.title} · similaridade {s:.2f}" for o, s in dups)

            def done(ok) -> None:
                if ok:
                    self.exec(build(v, True), after=lambda: self._after_new("OPP-"))
            self.push_screen(ConfirmModal("Possível duplicata", body + "\n\nGravar mesmo assim? (Se for a mesma ideia, cancele e use v: evidência.)",
                                          build(v, True)[0]), done)
            return True

        self.form(FormSpec("Nova oportunidade", self._opp_fields(pre), build,
                           sub="Nasce em 'ideia'. O detector de duplicatas olha título e problema antes de gravar.",
                           intercept=intercept, after=lambda: self._after_new("OPP-")))

    def _after_new(self, prefix: str) -> None:
        """Depois de criar, vai para o item novo (o último id do prefixo)."""
        store = self.store
        ids = sorted(store.by_proc if prefix == "PROC-" else store.by_opp)
        if ids:
            self.jump(ids[-1])

    def f_opp_edit(self) -> None:
        o = self.cur().data

        def build(v):
            c = ["opportunity", "update", o["id"], "--by", "owner"]
            if v["title"] != o["title"]:
                c += ["--title", v["title"]]
            return [c + self._opp_args(v, o)]

        self.form(FormSpec(f"Editar {o['id']}", self._opp_fields(o), build,
                           sub="Só o que mudou vai para a CLI. Status, ICE e promoção têm teclas próprias (s, i, p)."))

    def pick_status(self) -> None:
        o = self.cur().data

        def source(q: str) -> list[PickItem]:
            out = []
            for s in STATUS_ORDER:
                if q and q.lower() not in s:
                    continue
                g, gs = rows.OPP_GLYPH[s]
                note = " ← atual" if s == o["status"] else " (pede motivo)" if s in OPP_REASON_STATUS else \
                    " (só promovendo: p)" if s == "em-andamento" and not o["project"] else ""
                out.append(PickItem(Text.assemble((g + " ", gs), (s, "bold"), (note, "dim")), s))
            return out

        def done(item) -> None:
            if item:
                self.set_status(o, item.data)
        self.push_screen(PickerModal(f"Status de {o['id']}", "ideia · triagem · priorizada · …", source), done)

    def set_status(self, o: dict, status: str) -> None:
        if status == o["status"]:
            return
        if status == "em-andamento" and not o["project"]:
            self.log_line(f"{o['id']}: 'em-andamento' só existe depois de promover a projeto (tecla p).", "yellow")
            return
        if status in OPP_REASON_STATUS:
            self.form(FormSpec(f"{o['id']} → {status}", [Field("reason", "motivo", req=True, ph="por que fica assim")],
                               lambda v: [["opportunity", "status", o["id"], status, "--reason", v["reason"] or "…", "--by", "owner"]],
                               sub=o["title"]))
            return
        self.exec([["opportunity", "status", o["id"], status, "--by", "owner"]])

    def f_opp_discard(self) -> None:
        self.set_status(self.cur().data, "descartada")

    def f_ice(self) -> None:
        o = self.cur().data
        fields = [Field("impact", "impacto (1–5)", value=str(o["impact"] or ""), req=True, check=self._scale_check),
                  Field("confidence", "confiança (1–5)", value=str(o["confidence"] or ""), req=True, check=self._scale_check),
                  Field("ease", "facilidade (1–5)", value=str(o["ease"] or ""), req=True, check=self._scale_check)]
        self.form(FormSpec(f"ICE de {o['id']}", fields,
                           lambda v: [["opportunity", "score", o["id"], "--impact", v["impact"] or "…", "--confidence", v["confidence"] or "…",
                                       "--ease", v["ease"] or "…", "--by", "owner"]],
                           sub="Score = impacto × confiança × facilidade (1–125). O CLI calcula e mostra o resultado." + (
                               f" Sugestão do agente: {o['ice_reason']}" if o["ice_suggested"] and o["ice_reason"] else ""),
                           show="ICE gravado"))

    def confirm_ice(self) -> None:
        o = self.cur().data
        self.exec([["opportunity", "score", o["id"], "--impact", str(o["impact"]), "--confidence", str(o["confidence"]),
                    "--ease", str(o["ease"]), "--by", "owner"]])

    def f_evidence(self) -> None:
        o = self.cur().data
        self.form(FormSpec(f"Evidência de {o['id']}", [Field("source", "fonte", req=True, ph="PROCESSED/2026/10/reuniao.md")],
                           lambda v: [["opportunity", "evidence", o["id"], "--source", v["source"] or "…", "--by", "owner"]],
                           sub="Artefato ou RAW que reforça esta oportunidade."))

    def agent_onepager(self) -> None:
        o = self.cur().data
        self.ask_agent(f"One-pager de {o['id']}", [
            "Confere os campos e as evidências (o que não consta, não consta)",
            "Com a porta do Drive ligada: Resumo em tabelas (segue o Brain) + Detalhamento escrito pelo agente",
            f"Sem a porta: brain share opportunity {o['id']} (vault/reports/share/) · publicar é outro gate (/publish)"],
            f"/opportunity onepager {o['id']}")

    def f_promote(self) -> None:
        o = self.cur().data
        goals = [g["id"] for g in self.store.m["goals"] if g["status"] in ("ativo", "ativa")]
        if not goals:
            self.log_line("Nenhum goal ativo para receber o projeto.", "yellow")
            return
        opp = self.store.brain.state.opportunities[o["id"]]
        nid, diff = promote_proposal(self.store.brain, opp)
        extra = Text()
        for ln in diff:
            extra.append("+ " + ln + "\n", "green")

        def build(v):
            c = ["opportunity", "promote", o["id"], "--goal", v["goal"]]
            if v["title"] and v["title"] != o["title"]:
                c += ["--title", v["title"]]
            if v["reason"]:
                c += ["--reason", v["reason"]]
            return [c + ["--approval", v["quote"] or "…"]]

        self.form(FormSpec(
            f"Promover {o['id']} a projeto {nid}",
            [Field("goal", "goal", choice=goals, value=goals[0]), Field("title", "título do projeto", value=o["title"], req=True),
             Field("reason", "motivo", ph="opcional"),
             Field("quote", "sua aprovação", req=True, ph="digite a resposta literal, ex.: ok")], build,
            sub="Criar projeto é mudança estrutural: único gate do sistema. Nasce em PLANNING/goals.md, com linha em "
                "PLANNING/log.md e no ledger; a oportunidade vira em-andamento.",
            gate=True, extra=extra, after=lambda: self.jump(o["id"])))

    # ── áreas ──────────────────────────────────────────────────────────────
    def f_area_new(self) -> None:
        def build(v):
            c = ["area", "add", v["slug"] or "…", "--by", "owner"]
            for opt, key in (("--name", "name"), ("--alias", "alias"), ("--note", "note")):
                if v[key]:
                    c += [opt, v[key]]
            return [c]

        slug_ok = lambda v: "" if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", v) else "Use minúsculas, números e hífens (ex.: growth)."  # noqa: E731
        self.form(FormSpec("Nova área", [Field("slug", "id", req=True, ph="operacoes", check=slug_ok),
                                         Field("name", "nome", ph="Operações"), Field("alias", "aliases", ph="Ops, Operacoes (vírgula)"),
                                         Field("note", "nota")], build, sub="Áreas são do ledger: cadastre quantas quiser."))

    def f_area_edit(self) -> None:
        a = self.cur().data

        def build(v):
            c = ["area", "update", a["id"], "--by", "owner"]
            if v["name"] and v["name"] != a["name"]:
                c += ["--name", v["name"]]
            for opt, key in (("--alias", "alias"), ("--note", "note")):
                if v[key]:
                    c += [opt, v[key]]
            return [c]

        self.form(FormSpec(f"Editar a área {a['id']}", [Field("name", "nome", value=a["name"], req=True),
                                                        Field("alias", "novo alias", ph="vírgula"), Field("note", "nota", value=a["note"])],
                           build, sub="Aliases novos são acrescentados."))

    # ── documentos ─────────────────────────────────────────────────────────
    def f_doc_link(self, target: str) -> None:
        def watch_check(v: str, vals: dict) -> str:
            if v != "sim":
                return ""
            if vals.get("kind") != "playbook":
                return "Só playbook é vigiado."
            return "" if watch.drive_doc_id(vals.get("ref", "")) else "Vigiar pede um doc do Drive (URL ou id)."

        def build(v):
            c = ["doc", "link", target, "--kind", v["kind"], "--ref", v["ref"] or "…", "--by", "owner"]
            if v["title"]:
                c += ["--title", v["title"]]
            if v["watch"] == "sim":
                c.append("--watch")
            return [c]

        self.form(FormSpec(f"Ligar documento a {target}",
                           [Field("kind", "tipo", choice=sorted(DOC_KINDS), value="playbook"),
                            Field("ref", "ref", req=True, ph="URL, id do Drive ou caminho do vault"),
                            Field("title", "título", ph="opcional"),
                            Field("watch", "vigiar", choice=["não", "sim"], check=watch_check)],
                           build, sub="Playbook vigiado do Drive: o /update só relê quando o modifiedTime muda."))

    def f_doc_unlink(self) -> None:
        d = self.cur().data

        def done(ok) -> None:
            if ok:
                self.exec([["doc", "unlink", d["target"], "--ref", d["ref"], "--by", "owner"]])
        self.push_screen(ConfirmModal(f"Desligar o documento de {d['target']}", d["title"] or d["ref"],
                                      ["doc", "unlink", d["target"], "--ref", d["ref"], "--by", "owner"]), done)

    def open_current_doc(self) -> None:
        it = self.cur()
        if it and it.kind == "docl":
            self.open_doc(it.data["target"], it.data["n"])

    def action_open_doc(self, target: str, n: int) -> None:
        self.open_doc(target, n)

    def open_doc(self, target: str, n: int) -> None:
        item = self.store.by_proc.get(target) or self.store.by_opp.get(target)
        if not item or n >= len(item["docs"]):
            return
        ref = item["docs"][n]["ref"]
        if ref.startswith(("http://", "https://")):
            url = ref
        elif watch.drive_doc_id(ref) == ref and "/" not in ref:
            url = f"https://docs.google.com/document/d/{ref}/edit"
        else:
            from .. import rawsort
            path = rawsort.resolve(self.inst, ref) if ref.startswith("RAW/") else self.inst.vault / ref
            if path and path.exists() and path.resolve().is_relative_to(self.inst.vault.resolve()):
                import os
                import shlex
                self.external([*shlex.split(os.environ.get("PAGER") or "less"), str(path.resolve())])
            else:
                self.log_line(f"{ref}: arquivo não encontrado no vault", "yellow")
            return
        self.log_line(f"abrindo {url}", "dim")
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001 — abrir navegador nunca derruba o TUI
            self.log_line(f"não consegui abrir o navegador: {e}", "red")
