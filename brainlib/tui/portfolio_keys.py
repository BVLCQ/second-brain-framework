"""Teclas e formulários da face Portfólio (processos, oportunidades, áreas, documentos).

Mixin do BrainApp: cada tecla monta uma linha `brain …` (mostrada no log antes de rodar); o TUI nunca escreve no
ledger por conta própria. Promover é o gate estrutural: mostra o diff do goals.md e pede a resposta literal do dono.
"""
from __future__ import annotations

from rich.text import Text

from .. import people as people_mod
from .. import portfolio, util, watch
from ..schema import OPP_REASON_STATUS
from .modals import ConfirmModal, PickerModal, PickItem
from . import rows

STATUS_ORDER = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue", "em-espera", "descartada"]


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
                add("L", "ligar doc", lambda: self.f_doc_link(it.id))
                add("o", "abrir playbook", self.open_playbook)
                add("a", "nova oportunidade", self.f_opp_from_proc)
                add("d", "aposentar", self.f_proc_retire)
        elif p == 3:
            add("n", "nova", lambda: self.f_opp_new())
            if w(it and it.kind == "opp"):
                add("e", "editar", self.f_opp_edit)
                add("s", "status", self.pick_status)
                add("i", "ICE", self.f_ice)
                if w(it and it.data["ice_suggested"]):
                    add("c", "confirmar ICE", self.confirm_ice)
                add("L", "ligar doc", lambda: self.f_doc_link(it.id))
                add("v", "evidência", self.f_evidence)
                add("O", "one-pager", self.agent_onepager, agent=True)
                if w(it and not it.data.get("promoted")):
                    add("p", "promover", self.f_promote, gate=True)
                if w(it and it.data["status"] not in ("descartada", "entregue")):
                    add("d", "descartar", self.f_opp_discard)
        elif p == 4 and t == 1:
            if w(it and it.kind == "opp"):
                add("s", "status", self.pick_status)
                add("i", "ICE", self.f_ice)
        elif p == 5:
            if t == 0:
                add("n", "nova", self.f_area_new)
                if w(it):
                    add("e", "editar", self.f_area_edit)
            elif t == 1:
                if w(it):
                    add("enter", "abrir", self.open_current_doc)
                    add("d", "desligar", self.f_doc_unlink)
            else:
                add("n", "nova", self.f_person)
                if w(it):
                    add("e", "editar", self.f_person_update)
                    add("a", "alias", self.f_alias)
                add("R", "resolver nome", self.f_resolve)

    # ── apoio ──────────────────────────────────────────────────────────────
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
                return f"pessoa '{name}' não encontrada. Cadastre em Portfólio › Registro › Pessoas."
            if len(cands) > 1:
                return f"'{name}' é ambíguo: {', '.join(cands)}."
        return ""

    # ── processos ──────────────────────────────────────────────────────────
    def f_proc_new(self) -> None:
        if not self._need_area():
            return
        self.open_form("process.new", after=lambda: self._after_new("PROC-"))

    def f_proc_edit(self) -> None:
        p = self.cur().data
        self.open_form("process.edit", {"id": p["id"], "item": p})

    def f_proc_retire(self) -> None:
        p = self.cur().data
        self.open_form("process.retire", {"id": p["id"], "title": p["title"]})

    def open_playbook(self) -> None:
        p = self.cur().data
        pb = p["playbook"]
        if not pb:
            self.log_line(f"{p['id']} não tem playbook ligado (tecla L, tipo playbook).", "yellow")
            return
        n = next((n for n, d in enumerate(p["docs"]) if d["ref"] == pb["ref"]), None)
        if n is None:      # playbook aponta pra um ref que saiu da lista de docs: o CLI não deixa, mas drift não derruba a tecla
            self.log_line(f"{p['id']}: o playbook {pb['ref']} não está mais na lista de docs do processo.", "yellow")
            return
        self.open_doc(p["id"], n)

    def f_opp_from_proc(self) -> None:
        p = self.cur().data
        self.f_opp_new({"area": p["area"], "process": p["id"]})

    # ── oportunidades ──────────────────────────────────────────────────────
    def f_opp_new(self, pre: dict | None = None) -> None:
        if not self._need_area():
            return
        from .. import forms

        def intercept(v: dict) -> bool:
            dups = portfolio.duplicates(v["title"], v["problem"], self.store.brain.state.opportunities.values())
            if not dups:
                return False
            body = "\n".join(f"{o.id} ({o.status}) · {o.title} · similaridade {s:.2f}" for o, s in dups)
            forced = [c + ["--force"] for c in forms.build("opportunity.new", v, ctx, self.form_model())]

            def done(ok) -> None:
                if ok:
                    self.exec(forced, after=lambda: self._after_new("OPP-"))
            self.push_screen(ConfirmModal("Possível duplicata", body + "\n\nGravar mesmo assim? (Se for a mesma ideia, cancele e use v: evidência.)",
                                          forced[0]), done)
            return True

        ctx = {"item": dict(pre or {})}
        self.open_form("opportunity.new", ctx, intercept=intercept, after=lambda: self._after_new("OPP-"))

    def _after_new(self, prefix: str) -> None:
        """Depois de criar, vai para o item novo (o último id do prefixo)."""
        store = self.store
        ids = sorted(store.by_proc if prefix == "PROC-" else store.by_opp)
        if ids:
            self.jump(ids[-1])

    def f_opp_edit(self) -> None:
        o = self.cur().data
        self.open_form("opportunity.edit", {"id": o["id"], "item": o})

    def pick_status(self) -> None:
        o = self.cur().data

        def source(q: str) -> list[PickItem]:
            out = []
            for s in STATUS_ORDER:
                if q and q.lower() not in s:
                    continue
                g, gs = rows.OPP_GLYPH[s]
                note = " ← atual" if s == o["status"] else " (pede motivo)" if s in OPP_REASON_STATUS else \
                    " (só promovendo: p)" if s == "em-andamento" and not o.get("promoted") else ""
                out.append(PickItem(Text.assemble((g + " ", gs), (s, "bold"), (note, "dim")), s))
            return out

        def done(item) -> None:
            if item:
                self.set_status(o, item.data)
        self.push_screen(PickerModal(f"Status de {o['id']}", "ideia · triagem · priorizada · …", source), done)

    def set_status(self, o: dict, status: str) -> None:
        if status == o["status"]:
            return
        if status == "em-andamento" and not o.get("promoted"):
            self.log_line(f"{o['id']}: 'em-andamento' só existe depois de promover (tecla p, em qualquer nível).", "yellow")
            return
        if status in OPP_REASON_STATUS:            # laterais pedem motivo: o mesmo formulário do painel
            self.open_form("opportunity.status", {"id": o["id"], "title": o["title"], "item": o}, values={"status": status})
            return
        self.exec([["opportunity", "status", o["id"], status, "--by", "owner"]])

    def f_opp_discard(self) -> None:
        self.set_status(self.cur().data, "descartada")

    def f_ice(self) -> None:
        o = self.cur().data
        reason = f" Sugestão do agente: {o['ice_reason']}" if o["ice_suggested"] and o["ice_reason"] else ""
        self.open_form("opportunity.score", {"id": o["id"], "item": o, "ice_reason": reason}, show="ICE gravado",
                       help=lambda: rows.ice_methodology(min(100, self.size.width - 6)), help_title="Metodologia · ICE")

    def confirm_ice(self) -> None:
        o = self.cur().data
        self.exec([["opportunity", "score", o["id"], "--impact", str(o["impact"]), "--confidence", str(o["confidence"]),
                    "--ease", str(o["ease"]), "--by", "owner"]])

    def f_evidence(self) -> None:
        o = self.cur().data
        self.open_form("opportunity.evidence", {"id": o["id"]})

    def agent_onepager(self) -> None:
        o = self.cur().data
        self.ask_agent(f"One-pager de {o['id']}", [
            "Confere os campos e as evidências (o que não consta, não consta)",
            "Com a porta do Drive ligada: Resumo em tabelas (segue o Brain) + Detalhamento escrito pelo agente",
            f"Sem a porta: brain share opportunity {o['id']} (vault/reports/share/) · publicar é outro gate (/publish)"],
            f"/opportunity onepager {o['id']}")

    def f_promote(self) -> None:
        o = self.cur().data
        self.open_form("opportunity.promote", {"id": o["id"], "item": o}, after=lambda: self.jump(o["id"]))

    # ── áreas ──────────────────────────────────────────────────────────────
    def f_area_new(self) -> None:
        self.open_form("area.new")

    def f_area_edit(self) -> None:
        a = self.cur().data
        self.open_form("area.edit", {"id": a["id"], "item": a})

    # ── documentos ─────────────────────────────────────────────────────────
    def f_doc_link(self, target: str) -> None:
        self.open_form("doc.link", {"target": target, "target_fixed": True})

    def f_doc_unlink(self) -> None:
        d = self.cur().data
        self.open_form("doc.unlink", {"target": d["target"], "ref": d["ref"], "doc_title": d["title"] or d["ref"]})

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
            # id cru do Drive: não sabemos se é Doc, Sheet ou Slide — o link genérico redireciona pro app certo
            url = f"https://drive.google.com/file/d/{ref}/view"
        else:
            from .. import rawsort
            path = rawsort.resolve(self.inst, ref) if ref.startswith("RAW/") else self.inst.vault / ref
            if path and path.exists() and path.resolve().is_relative_to(self.inst.vault.resolve()):
                self.action_open_file(self.inst.rel(path.resolve()))
            else:
                self.log_line(f"{ref}: arquivo não encontrado no vault", "yellow")
            return
        self.log_line(f"abrindo {url}", "dim")
        try:
            util.open_url(url)
        except Exception as e:  # noqa: BLE001 — abrir navegador nunca derruba o TUI
            self.log_line(f"não consegui abrir o navegador: {e}", "red")
