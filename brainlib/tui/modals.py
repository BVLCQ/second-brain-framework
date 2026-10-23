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
    choice: list[str] | None = None
    req: bool = False
    check: Callable[..., str] | None = None          # (valor) ou (valor, campos) → mensagem de erro, ou ""
    res: Callable[..., str] | None = None            # (valor) ou (valor, campos) → texto de apoio (ex.: data resolvida)
    multi: bool = False                              # caixa de texto grande (várias linhas); enter quebra a linha


@dataclass
class FormSpec:
    title: str
    fields: list[Field]
    build: Callable[[dict], list[list[str]]]         # valores → comandos `brain` (listas de argumentos)
    sub: str = ""
    gate: bool = False                               # pede aprovação digitada (borda âmbar)
    extra: Text | None = None                        # conteúdo fixo acima dos campos (ex.: diff, texto exato)
    on_cancel: Callable[[], None] | None = None
    on_fail: Callable[[], None] | None = None        # algum comando falhou (o que o formulário preparou fica desfeito)
    after: Callable[[], None] | None = None
    render: bool = True
    show: str | None = None                          # abre a saída inteira num modal (ex.: memória)
    intercept: Callable[[dict], bool] | None = None  # roda ao confirmar; True = assumiu o fluxo (ex.: perguntar antes de gravar)


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
    BINDINGS = [Binding("escape", "cancel", "Cancelar"), Binding("ctrl+s", "submit", "Confirmar"),
                Binding("ctrl+o", "external_edit", "Abrir no editor", show=False),
                Binding("enter", "enter_submit", priority=True, show=False)]

    def __init__(self, spec: FormSpec):
        super().__init__()
        self.spec = spec

    def compose(self) -> ComposeResult:
        s = self.spec
        with VerticalScroll(id="dialog", classes="gate" if s.gate else ""):
            yield Static(Text.assemble(("◆ aprovação · ", "yellow") if s.gate else "", (s.title, "bold")), id="mt")
            if s.sub:
                yield Static(Text(s.sub, "dim"), id="ms")
            if s.extra is not None:
                yield Static(s.extra, id="mx")
            for f in s.fields:
                with Horizontal(classes="frow big" if f.multi else "frow"):
                    yield Label(Text.assemble(f.label, (" *", "red") if f.req else ""), classes="flab")
                    if f.multi:
                        yield TextArea(f.value, placeholder=f.ph, id=f"f_{f.id}", classes="fin")
                    elif f.choice:
                        val = f.value if f.value in f.choice else f.choice[0]
                        yield Select([(c, c) for c in f.choice], value=val, allow_blank=False, id=f"f_{f.id}", classes="fin")
                    else:
                        yield Input(value=f.value, placeholder=f.ph, id=f"f_{f.id}", classes="fin")
                yield Static("", id=f"r_{f.id}", classes="fres")
            yield Static("", id="cmdp")
            yield Static("", id="err")
            multi = any(f.multi for f in s.fields)
            yield Static(Text("ctrl+s confirmar · ctrl+o abrir no seu editor (markdown) · enter quebra a linha · tab próximo campo · esc cancelar" if multi else
                              "enter confirmar · tab próximo campo · espaço abre a lista · esc cancelar", "dim"), id="mf")

    def on_mount(self) -> None:
        self._update()
        first = self.query("Input, Select, TextArea")
        if first:
            first.first().focus()

    def vals(self) -> dict:
        out = {}
        for f in self.spec.fields:
            w = self.query_one(f"#f_{f.id}")
            v = w.text if isinstance(w, TextArea) else w.value
            out[f.id] = "" if v is Select.BLANK else str(v).strip()
        return out

    def _update(self) -> None:
        v = self.vals()
        for f in self.spec.fields:
            self.query_one(f"#r_{f.id}", Static).update(Text(_call(f.res, v[f.id], v), "dim") if f.res and v[f.id] else "")
        try:
            self.query_one("#cmdp", Static).update(preview(self.spec.build(v)))
        except Exception as e:  # noqa: BLE001 — o preview nunca derruba o formulário
            self.query_one("#cmdp", Static).update(Text(f"({e})", "dim"))
        self.query_one("#err", Static).update("")

    def on_input_changed(self, _e) -> None:
        self._update()

    def on_select_changed(self, _e) -> None:
        self._update()

    def on_text_area_changed(self, _e) -> None:
        self._update()

    def on_input_submitted(self, _e) -> None:
        self.action_submit()

    def check_action(self, action: str, parameters) -> bool | None:
        if action == "enter_submit":                       # lista aberta: enter escolhe a opção; caixa grande: enter quebra a linha
            return not isinstance(self.focused, (SelectOverlay, TextArea))
        return True

    def action_enter_submit(self) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        v = self.vals()
        for f in self.spec.fields:
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
    BINDINGS = [Binding("escape", "clear", "Limpar")]

    def __init__(self, value: str, on_change: Callable[[str], None]):
        super().__init__()
        self.value, self.on_change = value, on_change

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text("Filtrar lista", "bold"), id="mt")
            yield Input(value=self.value, placeholder="texto, id ou projeto", id="fq")
            yield Static(Text("enter mantém · esc limpa", "dim"), id="mf")

    def on_mount(self) -> None:
        self.query_one("#fq").focus()

    def on_input_changed(self, e: Input.Changed) -> None:
        self.on_change(e.value.strip())

    def on_input_submitted(self, _e) -> None:
        self.dismiss(True)

    def action_clear(self) -> None:
        self.on_change("")
        self.dismiss(False)
