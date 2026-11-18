"""Telas modais do TUI: formulário com preview da CLI, seletor (paleta/busca), confirmação, agente, ajuda."""
from __future__ import annotations

import inspect
import shlex
from dataclasses import dataclass, field
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Select, Static, TextArea
from textual.widgets._select import SelectOverlay
from textual.widgets.option_list import Option

from .. import forms
from . import bridge


def _call(fn: Callable, value: str, vals: dict) -> str:
    """check/res com um argumento (o valor) ou dois obrigatórios (o valor e todos os campos, para campos que dependem de outros)."""
    required = [p for p in inspect.signature(fn).parameters.values() if p.default is p.empty]
    return fn(value, vals) if len(required) >= 2 else fn(value)


@dataclass
class Field:
    id: str
    label: str
    value: str = ""
    ph: str = ""
    choice: list[str | tuple[str, str]] | None = None    # valores, ou (valor, rótulo) quando o rótulo mostra mais que o valor
    options: Callable[[dict], list[tuple[str, str]]] | None = None   # (campos) → (valor, rótulo): lista que depende de outro campo
    depends: str | None = None                       # id do campo que, ao mudar, recalcula `options`
    req: bool = False
    check: Callable[..., str] | None = None          # (valor) ou (valor, campos) → mensagem de erro, ou ""
    res: Callable[..., str] | None = None            # (valor) ou (valor, campos) → texto de apoio (ex.: data resolvida)
    multi: bool = False                              # caixa de texto grande (várias linhas); enter quebra a linha
    show: Callable[[dict], bool] | None = None       # (campos) → aparece? Escondido não conta: valor "", sem req nem check
    fill: tuple[str, Callable[[dict], str | None]] | None = None   # (id do campo, (campos) → valor): preenche sozinho quando aquele campo muda (None não mexe)
    suggest: list[tuple[str, str]] | list[dict[str, str]] | list[str] | None = None   # texto livre com sugestões (id + rótulo; mesma fonte do painel)
    secret: bool = False                             # digita escondido (chave de API)


def _pairs(f: Field, vals: dict) -> list[tuple[str, str]]:
    """Opções de um campo de escolha como (rótulo, valor) — a ordem que o Select espera."""
    raw = f.options(vals) if f.options else (f.choice or [])
    return [((c[1], c[0]) if isinstance(c, tuple) else (c, c)) for c in raw]


EMPTY_CHOICE = ("— escolha —", "")


def _pairs_or_empty(f: Field, vals: dict) -> list[tuple[str, str]]:
    """Como `_pairs`, mas nunca vazia: sem opções, o campo fica em "— escolha —" (valor vazio) e o submit é barrado pelo obrigatório."""
    return _pairs(f, vals) or [EMPTY_CHOICE]


@dataclass
class FormSpec:
    title: str
    fields: list[Field]
    build: Callable[[dict], list[list[str]]]         # valores → comandos `brain` (listas de argumentos)
    sub: str = ""
    gate: bool = False                               # confirmar aprova (borda âmbar)
    extra: Text | None = None                        # conteúdo fixo acima dos campos (ex.: diff, texto exato)
    on_cancel: Callable[[], None] | None = None
    on_fail: Callable[[], None] | None = None        # algum comando falhou (o que o formulário preparou fica desfeito)
    after: Callable[[], None] | None = None
    render: bool = True
    show: str | None = None                          # abre a saída inteira num modal (ex.: memória)
    intercept: Callable[[dict], bool] | None = None  # roda ao confirmar; True = assumiu o fluxo (ex.: perguntar antes de gravar)
    help: Callable[[], Text] | None = None           # tecla ?: orientações de preenchimento (ex.: metodologia do ICE)
    help_title: str = "Orientações"                  # título da tela que o ? abre


@dataclass
class PickItem:
    label: Text
    data: object = None


def preview(cmds: list[list[str]]) -> Text:
    t = Text()
    for i, c in enumerate(cmds):
        if i:
            t.append("\n")
        t.append("$ ", "cyan")
        t.append(bridge.display(c), "cyan")
    return t


class FormModal(ModalScreen):
    # enter confirma em qualquer campo (inclusive nas listas); espaço/seta abre a lista de um campo de escolha
    # ? abre as orientações do formulário (spec.help) — com prioridade para vencer o Select fechado, e
    # check_action desliga a tecla nos formulários sem help (o ? continua digitável nos Input)
    BINDINGS = [Binding("escape", "cancel", "Cancelar"), Binding("ctrl+s", "submit", "Confirmar"),
                Binding("ctrl+o", "external_edit", "Abrir no editor", show=False),
                Binding("enter", "enter_submit", priority=True, show=False),
                Binding("question_mark", "show_help", "Orientações", priority=True, show=False)]

    def __init__(self, spec: FormSpec):
        super().__init__()
        self.spec = spec
        self._fields = {f.id: f for f in spec.fields}
        self._last_vals = {f.id: f.value for f in spec.fields}
        self._sug_items: dict[str, list[dict[str, str]]] = {}
        self._sug_active: str | None = None
        self._sug_navigated: bool = False

    def compose(self) -> ComposeResult:
        s = self.spec
        with VerticalScroll(id="dialog", classes="gate" if s.gate else ""):
            yield Static(Text.assemble(("◆ gate · ", "yellow") if s.gate else "", (s.title, "bold")), id="mt")
            if s.sub:
                yield Static(Text(s.sub, "dim"), id="ms")
            if s.extra is not None:
                yield Static(s.extra, id="mx")
            for f in s.fields:
                with Vertical(id=f"b_{f.id}", classes="fbox"):
                    with Horizontal(classes="frow big" if f.multi else "frow"):
                        yield Label(Text.assemble(f.label, (" *", "red") if f.req else ""), classes="flab")
                        if f.multi:
                            yield TextArea(f.value, placeholder=f.ph, id=f"f_{f.id}", classes="fin")
                        elif f.choice or f.options:
                            pairs = _pairs_or_empty(f, {x.id: x.value for x in s.fields})
                            val = f.value if f.value in [v for _, v in pairs] else pairs[0][1]
                            # opção vazia ("— escolha —") no topo: o estado sem escolha mostra o prompt dela
                            prompt = pairs[0][0] if pairs and pairs[0][1] == "" else "Select"
                            yield Select(pairs, value=val, allow_blank=False, prompt=prompt,
                                         id=f"f_{f.id}", classes="fin")
                        else:
                            yield Input(value=f.value, placeholder=f.ph, id=f"f_{f.id}", classes="fin",
                                        password=f.secret)
                    if f.suggest is not None:
                        ol = OptionList(id=f"s_{f.id}", classes="fsug")
                        ol.can_focus = False
                        ol.display = False
                        yield ol
                    yield Static("", id=f"r_{f.id}", classes="fres")
            yield Static("", id="cmdp")
            yield Static("", id="err")
            multi = any(f.multi for f in s.fields)
            keys = ("ctrl+s confirmar · ctrl+o abrir no seu editor (markdown) · enter quebra a linha · tab próximo campo"
                    if multi else "enter confirmar · tab próximo campo · espaço abre a lista")
            keys += " · ? orientações" if s.help else ""
            keys += " · esc cancelar"
            yield Static(Text(keys, "dim"), id="mf")

    def on_mount(self) -> None:
        self._update()
        first = self.query("Input, Select, TextArea")
        if first:
            first.first().focus()

    @staticmethod
    def _sug_token(val: str) -> str:
        return val.rsplit(",", 1)[-1].strip() if "," in val else val.strip()

    def _close_sug(self, fid: str | None = None) -> None:
        targets = [fid] if fid else [f.id for f in self.spec.fields if f.suggest is not None]
        for k in targets:
            for ol in self.query(f"#s_{k}"):
                ol.display = False
        if fid is None or self._sug_active == fid:
            self._sug_active = None
            self._sug_navigated = False

    def _refresh_sug(self, fid: str, raw_val: str, *, force_open: bool = False) -> None:
        f = self._fields.get(fid)
        if not f or f.suggest is None:
            return
        tok = self._sug_token(raw_val)
        if not tok and not force_open:
            self._close_sug(fid)
            return
        if self._sug_active and self._sug_active != fid:
            self._close_sug(self._sug_active)
        items = forms.filter_options(f.suggest, tok)
        self._sug_items[fid] = items
        ol = self.query_one(f"#s_{fid}", OptionList)
        ol.clear_options()
        if not items:
            self._close_sug(fid)
            return
        ol.add_options([
            Option(
                Text.assemble(
                    (it["id"], "bold cyan"),
                    (f" · {it['label']}", "") if it["label"] and it["label"] != it["id"] else "",
                ),
                id=str(i),
            )
            for i, it in enumerate(items)
        ])
        ol.highlighted = 0
        ol.display = True
        self._sug_active = fid
        if not force_open:
            self._sug_navigated = False

    def _highlighted_sug(self, fid: str) -> dict[str, str] | None:
        if self._sug_active != fid:
            return None
        ol = self.query_one(f"#s_{fid}", OptionList)
        items = self._sug_items.get(fid) or []
        if not ol.display or ol.highlighted is None or not (0 <= ol.highlighted < len(items)):
            return None
        return items[ol.highlighted]

    def _apply_sug(self, fid: str, chosen_id: str) -> None:
        inp = self.query_one(f"#f_{fid}", Input)
        cur = inp.value
        if "," in cur:
            prefix = cur.rsplit(",", 1)[0].rstrip()
            new_val = f"{prefix}, {chosen_id}"
        else:
            new_val = chosen_id
        self._last_vals[fid] = new_val
        self._close_sug(fid)
        inp.value = new_val
        inp.cursor_position = len(new_val)
        self._update()

    def _raw(self) -> dict:
        out = {}
        null = getattr(Select, "NULL", object())       # textual ≥8: valor sem escolha é sentinela, não ""
        for f in self.spec.fields:
            w = self.query_one(f"#f_{f.id}")
            v = w.text if isinstance(w, TextArea) else w.value
            out[f.id] = "" if v is Select.BLANK or v is null else str(v).strip()
        return out

    def _hidden(self, raw: dict) -> set[str]:
        return {f.id for f in self.spec.fields if f.show and not f.show(raw)}

    def vals(self) -> dict:
        raw = self._raw()
        hidden = self._hidden(raw)
        return {k: ("" if k in hidden else v) for k, v in raw.items()}

    def _update(self) -> None:
        v, hidden = self.vals(), self._hidden(self._raw())
        for f in self.spec.fields:
            self.query_one(f"#b_{f.id}").display = f.id not in hidden
        for f in self.spec.fields:
            self.query_one(f"#r_{f.id}", Static).update(Text(_call(f.res, v[f.id], v), "dim") if f.res and v[f.id] else "")
        try:
            self.query_one("#cmdp", Static).update(preview(self.spec.build(v)))
        except Exception as e:  # noqa: BLE001 — o preview nunca derruba o formulário
            self.query_one("#cmdp", Static).update(Text(f"({e})", "dim"))
        self.query_one("#err", Static).update("")

    def on_input_changed(self, e: Input.Changed) -> None:
        fid = (e.input.id or "")[2:]
        if fid in self._fields and e.value != self._last_vals.get(fid):
            self._last_vals[fid] = e.value
            self._refresh_sug(fid, e.value)
        self._update()

    def on_select_changed(self, e: Select.Changed) -> None:
        changed = (e.select.id or "")[2:]
        for f in self.spec.fields:
            if f.options and f.depends == changed:
                self._refresh_options(f)
            if f.fill and f.fill[0] == changed:
                val = f.fill[1](self.vals())
                if val is not None:
                    self._last_vals[f.id] = val
                    self._close_sug(f.id)
                    self.query_one(f"#f_{f.id}").value = val           # Input.Changed repinta o preview
        self._update()

    def _refresh_options(self, f: Field) -> None:
        """Recalcula a lista de um campo que depende de outro (ex.: projetos do goal escolhido), mantendo o valor se ainda existir."""
        sel = self.query_one(f"#f_{f.id}", Select)
        pairs = _pairs_or_empty(f, self.vals())
        keep = sel.value if sel.value in [v for _, v in pairs] else pairs[0][1]
        sel.set_options(pairs)
        sel.value = keep

    def on_text_area_changed(self, _e) -> None:
        self._update()

    def on_option_list_option_selected(self, e: OptionList.OptionSelected) -> None:
        fid = (e.option_list.id or "")[2:]
        items = self._sug_items.get(fid) or []
        if e.option.id is not None and 0 <= int(e.option.id) < len(items):
            self._apply_sug(fid, items[int(e.option.id)]["id"])
            self.query_one(f"#f_{fid}", Input).focus()

    def on_descendant_focus(self, e) -> None:
        fid = (e.widget.id or "")[2:] if (e.widget.id or "").startswith("f_") else None
        if self._sug_active and self._sug_active != fid:
            self._close_sug(self._sug_active)

    def on_key(self, e) -> None:
        if e.key in ("down", "up") and isinstance(self.focused, Input):
            fid = (self.focused.id or "")[2:]
            f = self._fields.get(fid)
            if f and f.suggest is not None:
                ol = self.query_one(f"#s_{fid}", OptionList)
                if not ol.display:
                    if e.key == "down":
                        self._refresh_sug(fid, self.focused.value, force_open=True)
                        self._sug_navigated = True
                        e.stop()
                        e.prevent_default()
                else:
                    ol.action_cursor_down() if e.key == "down" else ol.action_cursor_up()
                    self._sug_navigated = True
                    e.stop()
                    e.prevent_default()

    def on_input_submitted(self, _e) -> None:
        self.action_enter_submit()

    def check_action(self, action: str, parameters) -> bool | None:
        if action == "enter_submit":                       # lista aberta: enter escolhe a opção; caixa grande: enter quebra a linha
            return not isinstance(self.focused, (SelectOverlay, TextArea))
        if action == "show_help":                          # só os formulários com orientações (ex.: ICE) pegam o ?
            return self.spec.help is not None
        return True

    def action_enter_submit(self) -> None:
        if self._sug_active:
            chosen = self._highlighted_sug(self._sug_active)
            if chosen is not None:
                inp = self.query_one(f"#f_{self._sug_active}", Input)
                tok = self._sug_token(inp.value)
                if tok != chosen["id"] or self._sug_navigated:
                    self._apply_sug(self._sug_active, chosen["id"])
                    return
            self._close_sug()
        self.action_submit()

    def action_show_help(self) -> None:
        """? abre as orientações do formulário por cima (ex.: metodologia do ICE); esc volta com os valores intactos."""
        if self.spec.help is not None:
            self.app.push_screen(TextModal(self.spec.help_title, self.spec.help()))

    def action_submit(self) -> None:
        v, hidden = self.vals(), self._hidden(self._raw())
        for f in [x for x in self.spec.fields if x.id not in hidden]:
            if f.req and not v[f.id]:
                self.query_one("#err", Static).update(Text(f'Preencha "{f.label}".', "red"))
                self.query_one(f"#f_{f.id}").focus()
                return
            if f.check and v[f.id]:
                msg = _call(f.check, v[f.id], v)
                if msg:
                    self.query_one("#err", Static).update(Text(msg, "red"))
                    self.query_one(f"#f_{f.id}").focus()
                    return
        self.dismiss(v)

    def action_external_edit(self) -> None:
        """Abre o texto da caixa grande no $VISUAL/$EDITOR (vim, nano, code --wait…) e traz o resultado de volta."""
        areas = self.query(TextArea)
        if not areas:
            return
        ta = self.focused if isinstance(self.focused, TextArea) else areas.first()
        new = self.app.edit_in_editor(ta.text)
        if new is not None:
            ta.text = new
            ta.move_cursor(ta.document.end)
        ta.focus()

    def action_cancel(self) -> None:
        if self._sug_active and self._highlighted_sug(self._sug_active) is not None:
            self._close_sug()
            return
        self.dismiss(None)


class ChoiceModal(ModalScreen):
    """Pergunta com poucas saídas: seta + enter, ou a letra de cada opção. Esc devolve ''."""
    BINDINGS = [Binding("escape", "pick('')", "Voltar")]

    def __init__(self, title: str, body: Text, options: list[tuple[str, str, str]]):
        super().__init__()
        self.title_, self.body, self.options = title, body, options       # (tecla, valor, rótulo)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="gate"):
            yield Static(Text(self.title_, "bold"), id="mt")
            yield Static(self.body, id="mb")
            yield OptionList(*[Option(Text.assemble((f"{k}  ", "bold cyan"), lab), id=val) for k, val, lab in self.options], id="pl")
            yield Static(Text("↑↓ enter escolher · " + " · ".join(f"{k} {lab.split(' ')[0].lower()}" for k, _, lab in self.options) + " · esc volta", "dim"), id="mf")

    def on_mount(self) -> None:
        self.query_one("#pl", OptionList).focus()

    def on_key(self, e) -> None:
        for k, val, _ in self.options:
            if e.key == k:
                e.stop()
                self.dismiss(val)
                return

    def on_option_list_option_selected(self, e: OptionList.OptionSelected) -> None:
        self.dismiss(e.option.id)

    def action_pick(self, value: str) -> None:
        self.dismiss(value)


class PickerModal(ModalScreen):
    """Paleta de comandos e busca: digita, filtra, enter abre."""
    BINDINGS = [Binding("escape", "cancel", "Fechar"), Binding("down", "move(1)", show=False), Binding("up", "move(-1)", show=False)]

    def __init__(self, title: str, placeholder: str, source: Callable[[str], list[PickItem]], empty: str = ""):
        super().__init__()
        self.title_, self.ph, self.source, self.empty = title, placeholder, source, empty
        self.items: list[PickItem] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(self.title_, "bold"), id="mt")
            yield Input(placeholder=self.ph, id="pq")
            yield OptionList(id="pl")
            yield Static(Text("↑↓ escolher · enter abrir · esc fechar", "dim"), id="mf")

    def on_mount(self) -> None:
        self.query_one("#pq").focus()
        self.run_worker(self._refresh(""), exclusive=True)

    async def _refresh(self, q: str) -> None:
        import asyncio
        items = await asyncio.to_thread(self.source, q)
        self.items = items
        ol = self.query_one("#pl", OptionList)
        ol.clear_options()
        if items:
            ol.add_options([Option(i.label, id=str(n)) for n, i in enumerate(items)])
            ol.highlighted = 0
        else:
            ol.add_option(Option(Text(self.empty or "Nada encontrado. “Não consta” também é resposta.", "dim"), disabled=True))

    def on_input_changed(self, e: Input.Changed) -> None:
        self.run_worker(self._refresh(e.value.strip()), exclusive=True)

    def action_move(self, d: int) -> None:
        ol = self.query_one("#pl", OptionList)
        ol.action_cursor_down() if d > 0 else ol.action_cursor_up()

    def _pick(self) -> None:
        ol = self.query_one("#pl", OptionList)
        if ol.highlighted is not None and self.items and ol.highlighted < len(self.items):
            self.dismiss(self.items[ol.highlighted])

    def on_input_submitted(self, _e) -> None:
        self._pick()

    def on_option_list_option_selected(self, e: OptionList.OptionSelected) -> None:
        if e.option.id is not None:
            self.dismiss(self.items[int(e.option.id)])

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen):
    BINDINGS = [Binding("escape", "no", "Cancelar"), Binding("enter", "yes", "Confirmar")]

    def __init__(self, title: str, body: str, cmd: list[str] | None = None, door: str = ""):
        super().__init__()
        self.title_, self.body, self.cmd, self.door = title, body, cmd, door

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="gate" if self.door else ""):
            yield Static(Text(self.title_, "bold"), id="mt")
            yield Static(Text(self.body, "dim"), id="ms")
            if self.door:
                yield Static(Text(f" porta · {self.door} ", "bold yellow"), id="mx")
            if self.cmd:
                yield Static(preview([self.cmd]), id="cmdp")
            yield Static(Text("enter confirmar · esc cancelar", "dim"), id="mf")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class AgentModal(ModalScreen):
    BINDINGS = [Binding("escape", "no", "Cancelar"), Binding("enter", "run", "Rodar"), Binding("y", "copy", "Copiar prompt")]

    def __init__(self, title: str, bullets: list[str], prompt: str, argv: list[str] | None):
        super().__init__()
        self.title_, self.bullets, self.prompt, self.argv = title, bullets, prompt, argv

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="agent"):
            yield Static(Text.assemble(("⚡ ", "magenta"), (self.title_, "bold")), id="ms0")
            yield Static(Text("Isto roda o agente fora do TUI. O que ele escreve passa pelo ./brain.", "dim"), id="ms")
            if self.argv:
                shown = [a if len(a) < 90 else a[:87] + "…" for a in self.argv]
                yield Static(Text("$ " + shlex.join(shown), "magenta"), id="cmdp")
            else:
                yield Static(Text("Nenhum agente headless encontrado ([runner] em config/brain.toml). "
                                  "Copie o prompt com y e cole no chat do agente.", "yellow"), id="cmdp")
            yield Static(Text("O agente vai:", "dim"), id="mx")
            yield Static(Text("\n".join("  • " + b for b in self.bullets)), id="mb")
            yield Static(Text("enter rodar · y copiar o prompt · esc cancelar", "dim"), id="mf")

    def action_run(self) -> None:
        self.dismiss("run" if self.argv else None)

    def action_copy(self) -> None:
        self.dismiss("copy")

    def action_no(self) -> None:
        self.dismiss(None)


class TextModal(ModalScreen):
    """Ajuda e telas só de leitura."""
    BINDINGS = [Binding("escape", "close", "Fechar"), Binding("q", "close", show=False), Binding("question_mark", "close", show=False)]

    def __init__(self, title: str, body: Text):
        super().__init__()
        self.title_, self.body = title, body

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static(Text(self.title_, "bold"), id="mt")
            yield Static(self.body, id="mb")
            yield Static(Text("esc fecha", "dim"), id="mf")

    def action_close(self) -> None:
        self.dismiss(None)


class FilterModal(ModalScreen):
    """Um nível de filtro. `base` são os níveis já aplicados: este refina o que sobrou deles."""
    BINDINGS = [Binding("escape", "clear", "Limpar")]

    def __init__(self, value: str, on_change: Callable[[str], None], base: list[str] | None = None):
        super().__init__()
        self.value, self.on_change, self.base = value, on_change, list(base or [])

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(f"Filtrar lista — filtro {len(self.base) + 1}" if self.base else "Filtrar lista", "bold"), id="mt")
            if self.base:
                yield Static(Text("sobre: " + " › ".join(self.base), "magenta"), id="mb")
            yield Input(value=self.value, placeholder="refinar o que sobrou…" if self.base else "texto, id ou projeto", id="fq")
            yield Static(Text("enter mantém · esc desfaz só este filtro", "dim"), id="mf")

    def on_mount(self) -> None:
        self.query_one("#fq").focus()

    def on_input_changed(self, e: Input.Changed) -> None:
        self.on_change(e.value.strip())

    def on_input_submitted(self, _e) -> None:
        self.dismiss(True)

    def action_clear(self) -> None:
        self.on_change("")
        self.dismiss(False)
