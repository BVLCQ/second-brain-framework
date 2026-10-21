"""BrainApp — o cockpit de terminal do ./brain (Textual).

Cinco painéis numerados à esquerda, detalhe à direita, o log de comandos (painel 6) embaixo dele e a barra
de teclas contextual no rodapé. Leitura é em processo (view model); toda escrita é `./brain <args>` como
subprocesso, e a linha exata aparece no log. O desenho está em guides/tui-mockup.html.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import RichLog, Static

from .. import notes as notes_mod
from .. import people as people_mod
from .. import planning
from .. import search as search_mod
from .. import util
from . import bridge, dates, rows
from .modals import (AgentModal, ChoiceModal, ConfirmModal, Field, FilterModal, FormModal, FormSpec, PickerModal,
                     PickItem, TextModal)
from .store import PANELS, SYS_OPS, Item, Store

UCAP = 3                      # linhas visíveis de um painel sem foco


def _editor_argv() -> list[str]:
    """$VISUAL/$EDITOR como argv. Cursor e VS Code voltam na hora sem --wait: forçamos a espera."""
    argv = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
    if argv and Path(argv[0]).name in {"cursor", "code"} and not {"--wait", "-w"} & set(argv):
        argv.append("--wait")
    return argv

CMD_CATALOG = [               # paleta de comandos: nome, linha da CLI, (painel, aba, tecla)
    ("Nova ação", 'brain action open "…" --by owner', (2, 0, "n")),
    ("Fechar ação", 'brain action close A-#### --how "…"', (2, 0, "c")),
    ("Editar ação", "brain action update A-#### …", (2, 0, "e")),
    ("Prazo da ação", "brain action update A-#### --due …", (2, 0, "t")),
    ("Descartar ação", 'brain action drop A-#### --reason "…"', (2, 0, "D")),
    ("Reabrir ação", 'brain action reopen A-#### --reason "…"', (2, 0, "o")),
    ("O que me devem", "brain action list --list waiting", (2, 1, None)),
    ("Cobrar alguém", 'brain outbox draft --to … --text "…"', (2, 1, "m")),
    ("Árvore do plano", "brain plan show", (3, 0, None)),
    ("Marcar entregável", "brain plan deliverable P#.n --status …", (3, 0, "space")),
    ("Declarar progresso", "brain progress G1 45", (3, 0, "P")),
    ("Editar goal / projeto / entregável", 'brain plan edit G#|P#|P#.n … [--approval "ok"]', (3, 0, "e")),
    ("Mudança estrutural (gate)", 'brain plan log --diff … --approval "ok"', (3, 0, "E")),
    ("Novo goal (gate)", 'brain plan add-goal "…" --approval "ok"', (3, 0, "G")),
    ("Novo projeto / entregável / ação no item (n)", "brain plan add-project|add-deliverable · brain action open", (3, 0, "n")),
    ("Exportar para colega", "brain share project P1", (3, 0, "S")),
    ("Propostas pendentes", "brain proposal list", (4, 0, None)),
    ("Aceitar proposta", 'brain proposal accept R-#### --quote "…"', (4, 0, "a")),
    ("Rejeitar proposta", 'brain proposal reject R-#### --quote "…"', (4, 0, "r")),
    ("Rascunhar mensagem", 'brain outbox draft --to … --text "…"', (4, 1, "n")),
    ("Aprovar mensagem", 'brain outbox approve M-#### --quote "enviar N"', (4, 1, "A")),
    ("Enviar mensagem aprovada", "agente → Slack MCP → brain outbox sent", (4, 1, "S")),
    ("Planejar foco", "brain focus plan --days 5", (4, 2, "p")),
    ("Aprovar plano de foco", 'brain focus approve F-#### --quote "ok"', (4, 2, "A")),
    ("Aplicar foco na agenda", "brain focus apply F-#### --mode ics|google", (4, 2, "a")),
    ("Pedir publicação", "brain publish request … --to slack:#canal", (4, 3, "n")),
    ("Nova decisão", 'brain decision add "…" --decided-by …', (5, 0, "n")),
    ("Registrar entrega", 'brain delivery "…" --ref …', (5, 1, "n")),
    ("Nova pessoa", 'brain person add "…" --id …', (5, 2, "n")),
    ("Saúde da instância", "brain doctor --online", (1, 1, None)),
    ("Regenerar views", "brain render", (1, 3, "enter", "sys:render")),
    ("Abrir painel HTML", "brain render --open", (1, 3, "enter", "sys:open")),
    ("Validar ledger", "brain validate", (1, 3, "enter", "sys:validate")),
    ("Backup do vault", "brain backup", (1, 3, "enter", "sys:backup")),
    ("Atualizar framework", "brain update --check", (1, 3, "enter", "sys:update")),
    ("Varredura upstream", "brain upstream scan", (1, 3, "enter", "sys:upstream")),
    ("Memória: sincronizar", "brain memory sync", (1, 3, "enter", "sys:memory")),
    ("Memória: perguntar", 'brain memory recall|reflect "…"', (1, 3, "enter", "sys:recall")),
    ("Memória: status", "brain memory status", (1, 3, "enter", "sys:memstatus")),
    ("Saúde online", "brain doctor --online", (1, 3, "enter", "sys:doctor")),
    ("Colher edições do dono", "brain sync", (1, 3, "enter", "sys:sync")),
    ("Backup: ver últimos", "brain backup --status", (1, 3, "enter", "sys:backupst")),
    ("Agendamento: ver", "brain schedule status", (1, 3, "enter", "sys:schedst")),
    ("Agendamento: remover", "brain schedule remove", (1, 3, "enter", "sys:unsched")),
    ("Editar pessoa", "brain person update ID …", (5, 2, "u")),
    ("Quem é…?", 'brain person resolve "…"', (5, 2, "R")),
    ("Sincronizar o foco", "brain focus sync [--dry-run]", (4, 2, "s")),
    ("Primeira entrevista", "agente: /init", (1, 0, "i")),
    ("Cockpit da semana", "agente: /week", (1, 3, "enter", "sys:ai-week")),
    ("Ler emails", "agente: /gmail [filtro]", (1, 3, "enter", "sys:ai-gmail")),
    ("Ler Slack", "agente: /slack #canal [período]", (1, 3, "enter", "sys:ai-slack")),
    ("Ler doc do Drive", "agente: /drive <termo|id>", (1, 3, "enter", "sys:ai-drive")),
    ("Ler a agenda", "agente: /calendar [janela]", (1, 3, "enter", "sys:ai-calendar")),
    ("Recap", "agente: /recap <G#|P#|período>", (1, 3, "enter", "sys:ai-recap")),
    ("Reconciliar o framework", "agente: /upgrade", (1, 3, "enter", "sys:ai-upgrade")),
    ("Atualizar tudo", "agente: /update", (1, 0, "u")),
    ("Puxar uma fonte", "agente: /connect <fonte>", (1, 0, "c")),
    ("Fontes do watch.toml", "brain watch list", (1, 2, None)),
    ("Adicionar fonte", "brain watch add KEY --kind …", (1, 2, "n")),
    ("Editar fonte", "brain watch edit KEY …", (1, 2, "e")),
    ("Remover fonte", "brain watch remove KEY", (1, 2, "x")),
    ("Processar a inbox", "agente: /dump", (1, 0, "d")),
    ("Brief do dia", "agente: /brief", (1, 0, "b")),
    ("Buscar no ledger", 'brain search "…"', (None, None, "g")),
    ("Nova nota", 'brain note add --link A-#### --text "…"', (None, None, "N")),
    ("Ver o log de comandos", "painel 6", (6, 0, None)),
]


@dataclass
class Key:
    k: str
    label: str
    fn: Callable[[], None]
    agent: bool = False
    gate: bool = False


class ListPanel(Widget):
    can_focus = False

    def __init__(self, pid: int):
        super().__init__(id=f"p{pid}")
        self.pid = pid
        self.tab_spans: list[tuple[int, int, int]] = []

    def render(self) -> Text:
        return self.app.panel_body(self.pid, self.content_size.width, self.content_size.height)

    def on_click(self, event: events.Click) -> None:
        self.app.panel_click(self.pid, event.x, event.y, event.chain)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.app.panel_wheel(self.pid, 1)
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.app.panel_wheel(self.pid, -1)
        event.stop()


class Detail(VerticalScroll):
    can_focus = False


class Log(RichLog):
    can_focus = False

    def on_click(self, event: events.Click) -> None:
        self.app.goto_panel(6)


class BrainApp(App):
    CSS_PATH = "tui.tcss"
    TITLE = "brain"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, inst) -> None:
        super().__init__()
        self.inst = inst
        self.store: Store | None = None
        self.lp = 2                   # último painel de lista (1-5) em foco; o log (6) mantém o detalhe dele
        self.p = 2
        self.tab = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        self.sel_idx: dict[tuple[int, int], int] = {}
        self.sel_id: dict[tuple[int, int], str] = {}
        self.win: dict[tuple[int, int], int] = {}
        self.collapsed: set[str] = set()
        self.show_all = False
        self.filt: tuple[int, int, str] | None = None
        self.zoom = False
        self._items: dict[tuple[int, int], list[Item]] = {}
        self._lock: asyncio.Lock | None = None
        self.busy = ""
        self._quit_armed = False
        self._suggest_for: str | None = None

    @property
    def p(self) -> int:
        return self._p

    @p.setter
    def p(self, v: int) -> None:
        self._p = v
        if v != 6:
            self.lp = v

    # ── estrutura ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="left"):
                for pid in (1, 2, 3, 4, 5):
                    yield ListPanel(pid)
            with Vertical(id="right"):
                with Detail(id="detailwrap"):
                    yield Static("", id="detail")
                yield Log(id="log", markup=False, wrap=True, max_lines=500, auto_scroll=True)
        with Horizontal(id="bar"):
            yield Static("", id="hints")
            yield Static("", id="globals")

    async def on_mount(self) -> None:
        self._lock = asyncio.Lock()
        self.query_one("#detailwrap").border_title = "Detalhe"
        for pid in (1, 2, 3, 4, 5):
            self.query_one(f"#p{pid}").border_subtitle_align = "right"
        try:
            self.store = await asyncio.to_thread(Store, self.inst)
        except util.BrainError as e:
            self.log_line(f"ERRO: {e}", "red")
            self.log_line("Rode `brain validate` para ver o que está quebrado.", "dim")
            self.store = None
            return
        self.set_interval(4, self._watch)
        self.log_line("TUI pronto · ? ajuda · : comandos · g buscar", "dim")
        warn = sum(1 for c in self.store.health if c["level"] != "ok")
        if warn:
            self.log_line(f"⚠ {warn} aviso(s) de saúde · painel 1, aba Saúde", "yellow")
        self.redraw()

    # ── estado de navegação ────────────────────────────────────────────────
    def items(self, p: int) -> list[Item]:
        t = self.tab[p]
        key = (p, t)
        if key not in self._items:
            if self.store is None:
                self._items[key] = []
            else:
                f = self.filt[2] if self.filt and self.filt[:2] == key else ""
                self._items[key] = self.store.items(p, t, self.show_all, f, self.collapsed)
        return self._items[key]

    def sel_index(self, p: int) -> int:
        key = (p, self.tab[p])
        its = self.items(p)
        if not its:
            return 0
        want = self.sel_id.get(key)
        if want is not None:
            for i, it in enumerate(its):
                if it.id == want:
                    self.sel_idx[key] = i
                    return i
        i = min(max(self.sel_idx.get(key, 0), 0), len(its) - 1)
        self.sel_idx[key] = i
        self.sel_id[key] = its[i].id
        return i

    def set_sel(self, p: int, i: int) -> None:
        key, its = (p, self.tab[p]), self.items(p)
        if not its:
            return
        i = min(max(i, 0), len(its) - 1)
        self.sel_idx[key], self.sel_id[key] = i, its[i].id

    def cur(self) -> Item | None:
        p = self.lp if self.p == 6 else self.p
        its = self.items(p)
        return its[self.sel_index(p)] if its else None

    def fill_panel(self) -> int:
        return 2 if (self.lp == 1 and self.tab[1] == 0) else self.lp

    # ── desenho ────────────────────────────────────────────────────────────
    def panel_body(self, pid: int, width: int, height: int) -> Text:
        if self.store is None:
            return Text("Sem dados: ledger ilegível.", "red")
        t = self.tab[pid]
        if pid == 1 and t == 0:
            return self._summary()
        its = self.items(pid)
        if not its:
            f = self.filt[2] if self.filt and self.filt[:2] == (pid, t) else ""
            return Text(f'nada para "{f}"' if f else "vazio", "dim")
        idx = self.sel_index(pid)
        cap = max(1, height) if pid == self.fill_panel() else UCAP
        key = (pid, t)
        w = self.win.get(key, 0)
        if idx < w:
            w = idx
        if idx >= w + cap:
            w = idx - cap + 1
        w = min(max(0, w), max(0, len(its) - cap))
        self.win[key] = w
        on = self.p == pid
        sel_bg = Style(bgcolor=self.theme_variables.get("primary-muted") or self.theme_variables.get("panel"), bold=True)
        out = Text(no_wrap=True, overflow="ellipsis")
        for n, i in enumerate(range(w, min(len(its), w + cap))):
            it = its[i]
            if it.kind in ("g", "p"):
                it.extra["collapsed"] = it.id in self.collapsed
            line = rows.row(self.store, it, max(10, width - 2))
            if i == idx:
                mark = Text("▌", "bold " + ("cyan" if on else "dim"))
                if on:
                    line.stylize(sel_bg)
            else:
                mark = Text(" ")
            ln = Text(no_wrap=True, overflow="ellipsis")
            ln.append_text(mark)
            ln.append(" ")
            ln.append_text(line)
            if i == idx and on:
                ln.stylize(sel_bg)
            if n:
                out.append("\n")
            out.append_text(ln)
        return out

    def _summary(self) -> Text:
        c, s = self.store.counts, self.store
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(f" {c['mine_open']}", "bold")
        t.append(" minhas  ")
        if c["mine_overdue"]:
            t.append(f"⚠ {c['mine_overdue']} atrasada{'s' if c['mine_overdue'] > 1 else ''}  ", "red")
        t.append(f"{c['mine_due_7d']}", "bold")
        t.append(" em 7d\n")
        t.append(f" {c['waiting_open']}", "bold")
        t.append(" aguardando  ")
        t.append(f"{c['proposals_open']}", "bold yellow" if c["proposals_open"] else "bold")
        t.append(" propostas  ")
        drafts = sum(1 for x in s.m["outbox"] if x["status"] == "rascunho")
        t.append(f"{drafts}", "bold")
        t.append(f" rascunho{'' if drafts == 1 else 's'}\n")
        t.append(f" {s.inbox}", "bold magenta" if s.inbox else "bold")
        t.append(" inbox" + (" ⚡" if s.inbox else "") + "  ", "magenta" if s.inbox else "")
        t.append(f"{c['wins_30d']}", "bold")
        t.append(" conquistas  ")
        t.append(f"{c['mine_no_due']}", "bold yellow" if c["mine_no_due"] else "bold")
        t.append(" sem prazo")
        return t

    def _title(self, pid: int) -> Text:
        name, tabs = PANELS[pid]
        t = Text.assemble((f" [{pid}] ", "bold"), (name, "bold"))
        spans: list[tuple[int, int, int]] = []
        if len(tabs) > 1:
            t.append(" › ", "dim")
            for i, tb in enumerate(tabs):
                label = tb if (i == self.tab[pid] or len(tabs) < 4) else tb[:3]
                badge = self._badge(pid, i)
                start = t.cell_len
                t.append(label, "bold" if i == self.tab[pid] else "dim")
                if badge:
                    t.append(f" {badge}", "yellow")
                spans.append((start, t.cell_len, i))
                if i < len(tabs) - 1:
                    t.append(" · ", "dim")
        t.append(" ")
        self.query_one(f"#p{pid}", ListPanel).tab_spans = spans
        return t

    def _badge(self, pid: int, i: int) -> str:
        if self.store is None:
            return ""
        c, m = self.store.counts, self.store.m
        n = 0
        if pid == 4:
            if i == 0:
                n = c["proposals_open"]
            elif i == 1:
                n = sum(1 for x in m["outbox"] if x["status"] in ("rascunho", "aprovada"))
            elif i == 2:
                n = 1 if m["focus"] and m["focus"]["status"] == "proposto" else 0
            elif i == 3:
                n = sum(1 for s in m["shares"] if s["status"] in ("solicitada", "aprovada"))
        if pid == 1 and i == 1:
            n = sum(1 for h in self.store.health if h["level"] != "ok")
        if pid == 1 and i == 2:
            n = sum(1 for x in self.store.sources if x["failures"])
        return str(n) if n else ""

    def redraw(self) -> None:
        self._items = {}
        if not self.is_mounted:
            return
        fill = self.fill_panel()
        for pid in (1, 2, 3, 4, 5):
            panel = self.query_one(f"#p{pid}", ListPanel)
            panel.set_class(pid == self.p, "-on")
            compact = pid == 1 and self.tab[1] == 0
            panel.set_class(pid == fill and not compact, "-fill")
            panel.border_title = self._title(pid)
            n = len(self.items(pid)) if self.store and not compact else 0
            panel.border_subtitle = f" {self.sel_index(pid) + 1} de {n} " if n else ""
            panel.refresh(layout=True)
        self.query_one("#detail", Static).update(rows.detail(self.store, self.cur()) if self.store else Text(""))
        self.query_one("#detailwrap").scroll_home(animate=False)
        self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
        log, on = self.query_one("#log"), self.p == 6
        log.set_class(on, "-on")
        self.query_one("#detailwrap").set_class(on, "-small")
        log.border_title = Text.assemble((" [6] ", "bold"), ("Log de comandos ", "bold"))
        log.border_subtitle = " j k rolam · c limpa · 1-5 voltam " if on else ""
        self.set_class(self.zoom, "-zoom")
        self.refresh_hints()

    def _detail_subtitle(self) -> str:
        bits = []
        if self.zoom:
            bits.append("ampliado · esc volta")
        if self.filt and self.filt[2]:
            bits.append(f"filtro: {self.filt[2]}")
        if self.busy:
            bits.append(self.busy)
        return " · ".join(bits)

    def refresh_hints(self) -> None:
        def hint(t: Text, key: str, label: str, color: str, mark: str = "") -> None:
            click = Style(meta={"@click": f"app.hint({key!r})"})     # a dica inteira é clicável, tecla e rótulo
            t.append(" ", click)
            t.append(key, Style.parse("bold " + color) + click)
            t.append(" " + mark + label + " ", Style.parse("dim") + click)

        left = Text(no_wrap=True, overflow="ellipsis")
        for k in self.ctx_keys():
            hint(left, k.k, k.label, "magenta" if k.agent else ("yellow" if k.gate else "cyan"), "⚡ " if k.agent else "◆ " if k.gate else "")
        right = Text(no_wrap=True)
        for k, lab in (("?", "ajuda"), (":", "comandos"), ("N", "nota"), ("/", "filtrar"), ("g", "buscar"), ("r", "render"), ("q", "sair")):
            hint(right, k, lab, "cyan")
        self.query_one("#hints", Static).update(left)
        g = self.query_one("#globals", Static)
        g.update(right)
        g.styles.width = right.cell_len + 1

    # ── log ────────────────────────────────────────────────────────────────
    def log_line(self, text: str, style: str = "") -> None:
        t = Text()
        t.append(datetime.now().strftime("%H:%M ") if self.is_mounted else "", "dim")
        t.append(text, style)
        try:
            self.query_one("#log", RichLog).write(t)
        except Exception:  # noqa: BLE001 — log nunca derruba o app
            pass

    # ── cliques e roda do mouse ────────────────────────────────────────────
    def panel_click(self, pid: int, x: int, y: int, chain: int = 1) -> None:
        panel = self.query_one(f"#p{pid}", ListPanel)
        if y == 0:
            for x0, x1, i in panel.tab_spans:
                if x0 + 1 <= x <= x1 + 2:
                    self.p, self.tab[pid] = pid, i
                    self.redraw()
                    return
            self.p = pid
            self.redraw()
            return
        self.p = pid
        if pid == 1 and self.tab[1] == 0:
            self.redraw()
            return
        its = self.items(pid)
        w = self.win.get((pid, self.tab[pid]), 0)
        i = w + y - 1
        if 0 <= i < len(its):
            self.set_sel(pid, i)
        self.redraw()
        if chain >= 2 and 0 <= i < len(its):          # duplo clique = enter
            self.press("enter")

    def panel_wheel(self, pid: int, d: int) -> None:
        if pid == 1 and self.tab[1] == 0:
            return
        self.p = pid
        self.move(d)

    def action_hint(self, key: str) -> None:
        self.handle(key)

    def action_jump(self, node: str) -> None:
        self.jump(node)

    # ── teclado ────────────────────────────────────────────────────────────
    def on_key(self, event: events.Key) -> None:
        if len(self.screen_stack) > 1 or self.store is None and event.key != "q":
            return
        ch = event.character
        k = "space" if ch == " " else (ch if (ch and ch.isprintable()) else event.key)
        if self.handle(k):
            event.stop()
            event.prevent_default()

    def handle(self, k: str) -> bool:
        nav = {"j": 1, "down": 1, "k": -1, "up": -1}
        if k in nav:
            self.move(nav[k])
        elif k in ("home", "end"):
            self.move(-9999 if k == "home" else 9999)
        elif k in ("pagedown", "pageup"):
            self.move(8 if k == "pagedown" else -8)
        elif k in "123456" and len(k) == 1:
            self.goto_panel(int(k))
        elif k in ("l", "right"):                  # trocar de painel é só pelos números 1-5
            self.tab_move(1)
        elif k in ("h", "left"):
            self.tab_move(-1)
        elif k == "[":
            self.tab_move(-1)
        elif k == "]":
            self.tab_move(1)
        elif k == "?":
            self.help()
        elif k in (":", "ctrl+p"):
            self.palette()
        elif k == "g":
            self.search()
        elif k == "/":
            self.open_filter()
        elif k == "r":
            self.do_render()
        elif k == "N":
            self.f_note()
        elif k == "q":
            if self.busy and not self._quit_armed:
                self._quit_armed = True
                self.log_line(f"{self.busy} em andamento: sair agora interrompe. Aperte q de novo para sair mesmo assim.", "yellow")
            else:
                self.exit()
        elif k == "ctrl+t":
            self.theme = "textual-light" if self.theme != "textual-light" else "textual-dark"
            self.redraw()
        elif k == "escape":
            if self.zoom:
                self.zoom = False
                self.redraw()
            elif self.filt:
                self.filt = None
                self.redraw()
        else:
            return self.press(k)
        return True

    def press(self, k: str) -> bool:
        k = "enter" if k == "\r" else k
        if k == "enter" and (self.p == 6 or (self.p == 1 and self.tab[1] == 0)):
            return False
        for key in self.ctx_keys():
            if key.k == k:
                key.fn()
                return True
        if k == "enter":
            self.zoom = not self.zoom
            self.redraw()
            return True
        return False

    def goto_panel(self, p: int) -> None:
        self.p = ((p - 1) % 6) + 1
        if self.p == 6:
            self.zoom = False
        self.redraw()

    def tab_move(self, d: int) -> None:
        n = len(PANELS[self.p][1])
        self.tab[self.p] = min(max(self.tab[self.p] + d, 0), n - 1)
        self.redraw()

    def move(self, d: int) -> None:
        if self.p == 6:
            log = self.query_one("#log")
            if abs(d) >= 9999:
                log.scroll_home(animate=False) if d < 0 else log.scroll_end(animate=False)
            else:
                log.scroll_relative(y=d, animate=False)
            return
        if self.zoom:
            w = self.query_one("#detailwrap")
            w.scroll_relative(y=d * 3, animate=False)
            return
        if self.p == 1 and self.tab[1] == 0:
            return
        its = self.items(self.p)
        if not its:
            return
        self.set_sel(self.p, self.sel_index(self.p) + d)
        self.redraw()

    def jump(self, node: str) -> None:
        if self.store is None:
            return
        loc = self.store.locate(node)
        if not loc:
            self.log_line(f"{node}: não encontrei onde mostrar", "dim")
            return
        p, t = loc
        self.p, self.tab[p] = p, t
        self.zoom, self.filt = False, None
        if p == 3 and node[:1] == "P":
            proj = node.split(".")[0]
            self.collapsed.discard(proj)
            if proj in self.store.by_project:
                self.collapsed.discard(self.store.by_project[proj]["goal"])
        self._items = {}
        ids = [i.id for i in self.items(p)]
        if node not in ids and p in (2, 4):
            self.show_all, self._items = True, {}
            ids = [i.id for i in self.items(p)]
        if node in ids:
            self.set_sel(p, ids.index(node))
        self.redraw()

    # ── contexto de teclas ─────────────────────────────────────────────────
    def ctx_keys(self, every: bool = False, panel: int | None = None, tab: int | None = None) -> list[Key]:
        """Teclas do contexto atual. `every=True` lista todas, sem olhar o item (para o mapa de teclas)."""
        p = self.p if panel is None else panel
        t = self.tab[p] if tab is None else tab
        it = None if every else self.cur()
        K: list[Key] = []
        add = lambda k, label, fn, **kw: K.append(Key(k, label, fn, **kw))  # noqa: E731
        w = lambda cond: every or cond  # noqa: E731
        if p == 1:
            if t == 0:
                if w(self.store and self.store.is_empty()):
                    add("i", "primeira entrevista", self.agent_init, agent=True)
                add("u", "atualizar tudo", self.agent_update, agent=True)
                add("c", "puxar fonte", self.pick_source, agent=True)
                add("d", "processar inbox", lambda: self.agent_dump(), agent=True)
                add("b", "brief", lambda: self.agent_brief(), agent=True)
                add("o", "painel HTML", lambda: self.run_sys("sys:open"))
            elif t == 1:
                if w(it and it.extra.get("fix")):
                    add("f", "corrigir", self.fix_doc)
                add("o", "testar online", lambda: self.run_sys("sys:doctor"))
                add("enter", "ampliar", self.toggle_zoom)
            elif t == 2:
                add("n", "adicionar", self.f_source_add)
                if w(it and it.data["in_watch"]):
                    add("e", "editar", self.f_source_edit)
                    add("x", "remover", self.f_source_remove)
                if w(it and not it.data["in_watch"]):
                    add("w", "incluir no watch", self.f_source_include)
                if w(it):
                    add("c", "puxar", self.agent_connect_selected, agent=True)
                add("u", "atualizar tudo", self.agent_update, agent=True)
            else:
                add("enter", "executar", self.run_selected_sys)
                if w(it and it.id == "sys:update"):
                    add("U", "atualizar", lambda: self.run_sys("sys:update", apply=True))
        elif p == 2:
            add("n", "nova", self.f_new_action)
            if w(it and it.data["open"]):
                add("c", "fechar", self.f_close_action)
                add("e", "editar", self.f_edit_action)
                add("s", "status", self.cycle_status)
                add("t", "prazo", self.f_due)
                add("D", "descartar", self.f_drop)
            if t == 1 and w(it):
                add("m", "cobrar", self.f_chase)
            if w(it and not it.data["open"]):
                add("o", "reabrir", self.f_reopen)
            add("a", "só abertas" if self.show_all else "todas", self.toggle_all)
            add("enter", "ficha", self.toggle_zoom)
        elif p == 3:
            kind = it.kind if it else ""
            add("n", {"g": "novo projeto", "p": "novo entregável", "d": "nova ação"}.get(kind, "novo goal ou filho"),
                self.f_new_child, gate=kind in ("g", "") and not every)
            add("G", "novo goal", self.f_new_goal, gate=True)
            if w(it):
                add("e", "editar", self.f_edit_node, gate=not every and it.kind in ("g", "p"))
            if w(it and it.kind == "d"):
                add("space", "feito", self.toggle_done)
                add("s", "estado", self.f_deliv_state)
            if w(it and it.kind in ("g", "p")):
                add("enter", "recolher", self.toggle_collapse)
                add("P", "progresso", self.f_progress)
            add("E", "mudar árvore", self.edit_plan, gate=True)
            add("S", "exportar", self.f_share)
        elif p == 4:
            if t == 0:
                if w(it and it.data.status == "aberta"):
                    add("a", "aceitar", self.f_accept, gate=True)
                    add("r", "rejeitar", self.f_reject)
                add("T", "só abertas" if self.show_all else "todas", self.toggle_all)
            elif t == 1:
                add("n", "rascunhar", lambda: self.f_draft())
                if w(it and it.data["status"] == "rascunho"):
                    add("A", "aprovar", self.f_approve_msg, gate=True)
                if w(it and it.data["status"] == "aprovada"):
                    add("S", "enviar", self.agent_send, agent=True)
                if w(it and it.data["status"] in ("rascunho", "aprovada")):
                    add("x", "cancelar", self.f_cancel_msg)
                add("T", "só pendentes" if self.show_all else "todas", self.toggle_all)
            elif t == 2:
                add("p", "planejar", self.f_focus_plan)
                f = self.store.m["focus"] if self.store else None
                if w(f and f["status"] == "proposto"):
                    add("A", "aprovar", self.f_focus_approve, gate=True)
                if w(f and f["status"] == "aprovado"):
                    add("a", "aplicar", self.f_focus_apply, gate=True)
                add("s", "sync", self.focus_sync)
            else:
                add("n", "pedir", self.f_pub_request)
                if w(it and it.data["status"] == "solicitada"):
                    add("A", "aprovar", self.f_pub_approve, gate=True)
                if w(it and it.data["status"] == "aprovada"):
                    add("P", "publicar", self.agent_publish, agent=True)
                if w(it and it.data["status"] in ("solicitada", "aprovada")):
                    add("x", "cancelar", self.pub_cancel)
        elif p == 6:
            add("c", "limpar o log", self.clear_log)
        elif p == 5:
            if t == 0:
                add("n", "nova", self.f_decision)
                if w(it):
                    add("S", "superar", self.f_supersede)
            elif t == 1:
                add("n", "nova", self.f_delivery)
            elif t == 2:
                add("n", "nova", self.f_person)
                if w(it):
                    add("u", "editar", self.f_person_update)
                    add("a", "alias", self.f_alias)
                add("R", "resolver nome", self.f_resolve)
            else:
                if w(it):
                    add("o", "abrir RAW", self.open_raw)
        return K

    # ── execução ───────────────────────────────────────────────────────────
    def exec(self, cmds: list[list[str]], render: bool = True, after: Callable[[], None] | None = None,
             show: str | None = None) -> None:
        """Roda comandos `brain` em sequência (para no primeiro erro). `show` abre a saída inteira num modal."""
        self.run_worker(self._exec(cmds, render, after, show), exclusive=False)

    async def _exec(self, cmds: list[list[str]], render: bool, after, show: str | None = None) -> None:
        async with self._lock:
            ok = True
            outs: list[str] = []
            self.busy = "executando…"
            self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
            for args in cmds:
                self.log_line("$ " + bridge.display(args), "cyan")
                res = await asyncio.to_thread(bridge.run_brain, self.inst, args)
                lines = (res.out.splitlines() if res.out else [])
                outs.append(res.out or res.err)
                for ln in lines[:40]:
                    self.log_line(ln, "green" if res.ok else "")
                if len(lines) > 40:
                    self.log_line(f"… +{len(lines) - 40} linhas", "dim")
                if not res.ok:
                    self.log_line((res.err or f"saiu com código {res.rc}"), "red")
                    ok = False
                    break
                if not lines and res.ok:
                    self.log_line("✓ ok", "green")
            if ok and render:
                r = await asyncio.to_thread(bridge.run_brain, self.inst, ["render"])
                self.log_line("↻ brain render · " + (r.out.splitlines()[0] if r.out else "views regeneradas"), "dim")
            await self._reload()
            self.busy = ""
            self._quit_armed = False
            self.redraw()
            if show and ok and any(outs):
                self.push_screen(TextModal(show, Text("\n\n".join(o for o in outs if o))))
            if ok and after:
                after()

    async def _watch(self) -> None:
        """Relê o vault quando algo mudou fora do TUI (agente, outro terminal, editor)."""
        if self.store is None or self.busy or len(self.screen_stack) > 1 or self._lock.locked():
            return
        if await asyncio.to_thread(self.store.signature) == self.store.sig:
            return
        async with self._lock:
            await self._reload()
        self.log_line("↻ o vault mudou fora do TUI; releitura feita", "dim")
        self.redraw()

    async def _reload(self) -> None:
        try:
            await asyncio.to_thread(self.store.load)
        except util.BrainError as e:
            self.log_line(f"ERRO ao reler o ledger: {e}", "red")

    def do_render(self) -> None:
        self.exec([["render"]], render=False)

    def form(self, spec: FormSpec) -> None:
        def done(vals) -> None:
            if vals is None:
                if spec.on_cancel:
                    spec.on_cancel()
                return
            if spec.intercept and spec.intercept(vals):
                return
            self.exec(spec.build(vals), render=spec.render, after=spec.after, show=spec.show)
        self.push_screen(FormModal(spec), done)

    def toggle_zoom(self) -> None:
        self.zoom = not self.zoom
        self.redraw()

    def toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.redraw()

    def toggle_collapse(self) -> None:
        it = self.cur()
        if it:
            self.collapsed ^= {it.id}
            self.redraw()

    # ── ações: formulários ─────────────────────────────────────────────────
    @staticmethod
    def _due_check(v: str) -> str:
        try:
            dates.parse_due(v)
        except ValueError as e:
            return str(e)
        return ""

    @staticmethod
    def _effort_check(v: str) -> str:
        try:
            util.parse_duration(v)
        except util.BrainError as e:
            return str(e)
        return ""

    @staticmethod
    def _due_arg(v: str) -> list[str]:
        try:
            d = dates.parse_due(v)
        except ValueError:
            return []
        return ["--due", d.isoformat()] if d else []

    def f_new_child(self) -> None:
        """Painel 3, `n`: o que nasce depende do item. Goal → projeto, projeto → entregável, entregável → ação."""
        it = self.cur()
        if it is None:
            self.f_new_goal()
        elif it.kind == "g":
            self.f_new_project(it.data)
        elif it.kind == "p":
            self.f_new_deliverable(it.data)
        else:
            self.f_new_action({"project": it.extra["project"]["id"], "deliv": it.id})

    @staticmethod
    def _iso(v: str) -> str:
        try:
            d = dates.parse_due(v)
        except ValueError:
            return ""
        return d.isoformat() if d else ""

    def _gate_fields(self, why_ph: str) -> list[Field]:
        return [Field("reason", "motivo", ph=why_ph), Field("quote", "sua aprovação", req=True, ph="digite a resposta literal, ex.: ok")]

    def f_new_goal(self) -> None:
        nid = planning.next_goal_id(self.store.brain.plan)

        def build(v):
            c = ["plan", "add-goal", v["title"] or "…"]
            for opt, k in (("--why", "why"), ("--reason", "reason")):
                if v[k]:
                    c += [opt, v[k]]
            if self._iso(v["horizon"]):
                c += ["--horizon", self._iso(v["horizon"])]
            return [c + ["--approval", v["quote"] or "…"]]

        self.form(FormSpec(f"Novo goal {nid}", [
            Field("title", "título", req=True, ph="Marketing com IA onde faz sentido"),
            Field("horizon", "horizonte", ph=dates.HELP, check=self._due_check, res=dates.describe),
            Field("why", "por quê", ph="o que isto destrava"),
            *self._gate_fields("opcional: por que agora")], build,
            sub="Criar goal é mudança estrutural: único gate do sistema. Nasce em PLANNING/goals.md, com linha em PLANNING/log.md e no ledger.",
            gate=True, after=lambda: self.jump(nid)))

    def f_new_project(self, goal: dict) -> None:
        nid = planning.next_project_id(self.store.brain.plan)

        def build(v):
            c = ["plan", "add-project", goal["id"], v["title"] or "…"]
            if v["owner"]:
                c += ["--owner", v["owner"]]
            if v["reason"]:
                c += ["--reason", v["reason"]]
            return [c + ["--approval", v["quote"] or "…"]]

        self.form(FormSpec(f"Novo projeto {nid} em {goal['id']}", [
            Field("title", "título", req=True, ph="Padronização de métricas"),
            Field("owner", "dono", ph="id ou alias da pessoa (opcional)"),
            *self._gate_fields("opcional: por que agora")], build,
            sub=f"{goal['id']} · {goal['title']}. Criar projeto é mudança estrutural: pede a sua aprovação digitada.",
            gate=True, after=lambda: self.jump(nid)))

    def f_new_deliverable(self, proj: dict) -> None:
        nid = planning.next_deliverable_id(self.store.brain.plan, proj["id"])
        chk = lambda v: "" if v.isdigit() and int(v) >= 1 else "Use um inteiro a partir de 1."  # noqa: E731

        def build(v):
            c = ["plan", "add-deliverable", proj["id"], v["title"] or "…"]
            if self._iso(v["due"]):
                c += ["--due", self._iso(v["due"])]
            if v["weight"] not in ("", "1"):
                c += ["--weight", v["weight"]]
            return [c]

        self.form(FormSpec(f"Novo entregável {nid} em {proj['id']}", [
            Field("title", "título", req=True, ph="Manual de rotinas v1"),
            Field("due", "prazo", ph=dates.HELP, check=self._due_check, res=dates.describe),
            Field("weight", "peso", value="1", ph="1 · 2 · 3…", check=chk)], build,
            sub=f"{proj['id']} · {proj['title']}. Entregável não é goal nem projeto: entra no goals.md sem gate (o título não pode ter “·”).",
            after=lambda: self.jump(nid)))

    def f_edit_node(self) -> None:
        """Painel 3, `e`: edita o item selecionado. Goal e projeto são gate (aprovação digitada); entregável não."""
        it = self.cur()
        if it is None:
            return
        d, nid = it.data, it.id
        owner0 = d.get("owner") or ""
        status_opts = lambda cur: planning.NODE_STATUS + ([cur] if cur not in planning.NODE_STATUS else [])  # noqa: E731

        def build(v):
            c = ["plan", "edit", nid]
            if v["title"] != d["title"]:
                c += ["--title", v["title"]]
            if it.kind in ("g", "p") and v["status"] != d["status"]:
                c += ["--status", v["status"]]
            if it.kind == "g":
                if v["horizon"] != (d["horizon"] or ""):
                    c += ["--horizon", self._iso(v["horizon"])]
                if v["why"] != (d["why"] or ""):
                    c += ["--why", v["why"]]
            elif it.kind == "p":
                if v["owner"] != owner0:
                    c += ["--owner", v["owner"]]
            else:
                if v["due"] != (d["due"] or ""):
                    c += ["--due", self._iso(v["due"])]
                if v["weight"] != str(d["weight"]):
                    c += ["--weight", v["weight"]]
            if it.kind in ("g", "p"):
                if v["reason"]:
                    c += ["--reason", v["reason"]]
                c += ["--approval", v["quote"] or "…"]
            return [c]

        if it.kind == "g":
            fields = [Field("title", "título", value=d["title"], req=True),
                      Field("status", "status", choice=status_opts(d["status"]), value=d["status"]),
                      Field("horizon", "horizonte", value=d["horizon"] or "", ph="vazio remove · " + dates.HELP, check=self._due_check, res=dates.describe),
                      Field("why", "por quê", value=d["why"] or "", ph="vazio remove")]
        elif it.kind == "p":
            fields = [Field("title", "título", value=d["title"], req=True),
                      Field("status", "status", choice=status_opts(d["status"]), value=d["status"]),
                      Field("owner", "dono", value=owner0, ph="id ou alias da pessoa · vazio remove")]
        else:
            chk = lambda v: "" if v.isdigit() and int(v) >= 1 else "Use um inteiro a partir de 1."  # noqa: E731
            fields = [Field("title", "título", value=d["title"], req=True, check=lambda v: "O título não pode ter “·”." if "·" in v else ""),
                      Field("due", "prazo", value=d["due"] or "", ph="vazio remove · " + dates.HELP, check=self._due_check, res=dates.describe),
                      Field("weight", "peso", value=str(d["weight"]), ph="1 · 2 · 3…", check=chk)]
        gate = it.kind in ("g", "p")
        if gate:
            fields += self._gate_fields("opcional: por que mudar")
        sub = (f"Editar {'goal' if it.kind == 'g' else 'projeto'} é mudança estrutural: pede a sua aprovação digitada."
               if gate else "Entregável não é goal nem projeto: a edição entra no goals.md sem gate (o estado — feito, em andamento — segue em space/s).")
        self.form(FormSpec(f"Editar {nid}", fields, build, sub=sub, gate=gate))

    # entregável por número: dentro do projeto P1, "9" vale P1.9
    @staticmethod
    def _deliv_id(raw: str, project: str) -> str:
        r = (raw or "").strip().upper().lstrip(".")
        if r.isdigit():
            return f"{project}.{int(r)}" if project and project != "—" else ""
        return r

    def _deliv_check(self, raw: str, vals: dict) -> str:
        proj = vals.get("project", "")
        full = self._deliv_id(raw, proj)
        if not full:
            return "Só o número precisa do campo projeto: escolha o projeto ou escreva P#.n por inteiro."
        if full in self.store.by_deliv:
            return ""
        p = full.split(".")[0]
        nums = [d["id"].split(".")[1] for d in self.store.by_project[p]["deliverables"]] if p in self.store.by_project else []
        return f"{full} não existe" + (f" (os de {p} são {', '.join(nums)})" if nums else "")

    def _deliv_res(self, raw: str, vals: dict) -> str:
        full = self._deliv_id(raw, vals.get("project", ""))
        hit = self.store.by_deliv.get(full)
        return f"→ {full} · {hit[1]['title']}" if hit else ""

    def f_new_action(self, pre: dict | None = None) -> None:
        pre = pre or {}
        lst = ["mine", "waiting", "watching"][self.tab[2]] if self.p == 2 else "mine"
        owner = ""

        def build(v):
            a = ["action", "open", v["title"] or "…", "--by", "owner"]
            if v["list"] != "mine":
                a += ["--list", v["list"]]
            if v["owner"]:
                a += ["--owner", v["owner"]]
            a += self._due_arg(v["due"])
            if v["effort"]:
                a += ["--effort", v["effort"]]
            if v["project"] not in ("", "—"):
                a += ["--project", v["project"]]
            if v["prio"] != "normal":
                a += ["--priority", v["prio"]]
            if v["deliv"]:
                a += ["--deliverable", self._deliv_id(v["deliv"], v["project"]) or v["deliv"]]
            for opt, key in (("--people", "people"), ("--blocked-by", "blocked"), ("--link", "link")):
                if v[key]:
                    a += [opt, v[key]]
            return [a]

        def after_suggest() -> None:
            """Sem prazo digitado: oferece o agente para sugerir um (aparece em rosa até você decidir)."""
            title = self._suggest_for
            hit = [] if not title else sorted((x["id"] for x in self.store.m["actions"] if x["title"] == title and x["open"] and not x["due"]))
            if hit:
                self.ask_agent(f"Sugerir prazo para {hit[-1]}", [
                    "Lê o contexto: PLANNING (prazos de projeto/entregável), acordos com pessoas, agenda e carga atual",
                    "Grava o prazo como sugestão (brain action update … --due-suggested): fica rosa até você definir a data",
                    "Sem base para sugerir, diz 'não consta' e deixa a ação sem prazo"], f"/todo prazo {hit[-1]}")

        def build_and_remember(v):
            self._suggest_for = v["title"] if not self._iso(v["due"]) and v["list"] != "watching" else None
            return build(v)

        self.form(FormSpec(f"Nova ação em {pre['deliv']}" if pre.get("deliv") else "Nova ação", [
            Field("title", "título", req=True, ph="o que precisa acontecer"),
            Field("due", "prazo", ph=dates.HELP, check=self._due_check, res=dates.describe),
            Field("effort", "esforço", ph="90m · 2h · 1h30 · 1d", check=self._effort_check),
            Field("project", "projeto", choice=["—"] + self.store.project_ids(), value=pre.get("project", "—")),
            Field("prio", "prioridade", choice=["normal", "alta", "baixa"]),
            Field("list", "lista", choice=["mine", "waiting", "watching"], value=lst),
            Field("owner", "dono", ph="você (ou id/alias da pessoa)", value=owner),
            Field("deliv", "entregável", ph="9 (do projeto escolhido) ou P#.n · opcional", value=pre.get("deliv", ""),
                  check=self._deliv_check, res=self._deliv_res),
            Field("people", "pessoas", ph="marina-demo, heitor-demo (opcional)"),
            Field("blocked", "bloqueada por", ph="A-#### (opcional)"),
            Field("link", "link", ph="URL (opcional)")],
            build_and_remember, sub="Equivalente ao /todo. Sem prazo, o agente oferece uma sugestão (rosa).",
            after=after_suggest))

    def clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def f_note(self, pre: dict | None = None) -> None:
        """Nota avulsa: vira um .md na inbox (a porta única); o /dump arquiva no RAW. Vínculo opcional.
        Se já existe nota de hoje para o mesmo vínculo (ainda na inbox), pergunta: editar a existente ou criar outra."""
        it = self.cur()
        link0 = it.id if it and it.kind in ("action", "g", "p", "d") else ""
        pre = pre or {}
        brain, today = self.store.brain, util.today().isoformat()

        def err(v: str) -> str:
            return notes_mod.check_link(brain, notes_mod.normalize_link(v))

        def res(v: str) -> str:
            link = notes_mod.normalize_link(v)
            if err(v):
                return err(v)
            a = self.store.by_action.get(link)
            title = a["title"] if a else brain.plan.title(link)
            return f"{notes_mod.kind_of(link)} · {title} → {notes_mod.filename(self.inst, link, today)}"

        def build(v):
            c = ["note", "add"]
            if v["link"]:
                c += ["--link", notes_mod.normalize_link(v["link"])]
            return [c + ["--text", v["text"] or "…"]]

        def intercept(v: dict) -> bool:
            link = notes_mod.normalize_link(v["link"])
            ex = notes_mod.editable_today(self.inst, link)
            if ex is None:
                return False
            peek = ex.text.splitlines()
            body = Text.assemble((f"{link}: já existe uma nota de hoje, criada {ex.created[11:]}"
                                  + (f" e editada {ex.edited[11:]}" if ex.edited else "") + ", ainda na inbox.\n\n", "dim"),
                                 "\n".join("▌ " + ln for ln in peek[:4]) + ("\n▌ …" if len(peek) > 4 else ""))

            def chose(c: str) -> None:
                if c == "edit":
                    self.f_note_edit(ex, v["text"])
                elif c == "new":
                    self.exec(build(v), render=False)
                else:
                    self.f_note(pre=v)
            self.push_screen(ChoiceModal("Editar a nota de hoje ou criar outra?", body, [
                ("e", "edit", "Editar a existente (o que você digitou entra no fim do texto dela)"),
                ("n", "new", f"Nova nota ({notes_mod.filename(self.inst, link, today)})")]), chose)
            return True

        self.form(FormSpec("Nova nota", [
            Field("text", "nota", value=pre.get("text", ""), req=True, multi=True, ph="escreva à vontade: ideias, contexto, o que ouviu…"),
            Field("link", "vínculo", value=pre.get("link", link0), ph="A-#### · G# · P# · P#.n (opcional)", check=err, res=res)],
            build, render=False, intercept=intercept,
            sub="Cai na inbox como arquivo .md (nome: vínculo-data-note). O /dump arquiva no RAW; até lá e depois, "
                "a nota aparece no detalhe do vínculo, abaixo do histórico. Markdown: ctrl+o abre no seu editor."))

    def f_note_edit(self, note: notes_mod.Note, extra: str = "") -> None:
        merged = note.text + (f"\n\n{extra}" if extra else "")
        self.form(FormSpec(f"Editar {Path(note.path).name}", [
            Field("text", "nota", value=merged, req=True, multi=True)],
            lambda v: [["note", "edit", note.path, "--text", v["text"] or "…"]], render=False,
            sub=f"Reescreve o arquivo na inbox (criada {note.created}); vínculo e hora de criação ficam. "
                "Depois do /dump a nota vira RAW e não se edita mais. ctrl+o abre no seu editor."))

    def f_close_action(self) -> None:
        a = self.cur().data

        def build(v):
            return [["action", "close", a["id"], "--how", v["how"] or "…"] + (["--outcome", v["outcome"]] if v["outcome"] else []) + ["--by", "owner"]]

        self.form(FormSpec(f"Fechar {a['id']}", [
            Field("how", "como foi", req=True, ph="enviei o draft, Heitor-demo confirmou"),
            Field("outcome", "resultado", ph="opcional: resultado observável (vira entrega E-####)")],
            build, sub=a["title"]))

    def f_edit_action(self) -> None:
        a = self.cur().data
        eff0 = util.fmt_duration(a["effort_min"]) if a["effort_min"] else ""
        deliv0, blocked0 = a["deliverable"] or "", ",".join(a["blocked_by_all"] or [])
        proj0 = a["project"] or "—"
        deliv_shown = deliv0.split(".", 1)[1] if proj0 != "—" and deliv0.startswith(proj0 + ".") else deliv0   # P1.9 aparece como 9
        owner0 = "" if a["mine"] else a["owner"]

        def build(v):
            c = ["action", "update", a["id"]]
            if v["title"] != a["title"]:
                c += ["--title", v["title"]]
            if v["due"] != (a["due"] or ""):
                c += self._due_arg(v["due"]) or ["--clear-due"]
            if v["effort"] != eff0 and v["effort"]:
                c += ["--effort", v["effort"]]
            if v["prio"] != (a["priority"] or "normal"):
                c += ["--priority", v["prio"]]
            if v["project"] != proj0 and v["project"] != "—":
                c += ["--project", v["project"]]
            deliv = self._deliv_id(v["deliv"], v["project"]) or v["deliv"]
            if deliv and deliv != deliv0:
                c += ["--deliverable", deliv]
            if v["blocked"] and v["blocked"].replace(" ", "") != blocked0:
                c += ["--blocked-by", v["blocked"].replace(" ", "")]
            new_people = [p.strip() for p in v["people"].split(",") if p.strip() and p.strip() not in a["people"]]
            if new_people:
                c += ["--people", ",".join(new_people)]
            if v["list"] != a["list"]:
                c += ["--list", v["list"]]
            if v["owner"] and v["owner"] != owner0:
                c += ["--owner", v["owner"]]
            if v["note"]:
                c += ["--note", v["note"]]
            return [c + ["--by", "owner"]]

        self.form(FormSpec(f"Editar {a['id']}", [
            Field("title", "título", value=a["title"], req=True),
            Field("due", "prazo", value=a["due"] or "", check=self._due_check, res=dates.describe, ph="vazio remove o prazo"),
            Field("effort", "esforço", value=eff0, check=self._effort_check),
            Field("prio", "prioridade", choice=["normal", "alta", "baixa"], value=a["priority"] or "normal"),
            Field("project", "projeto", choice=["—"] + self.store.project_ids(), value=proj0),
            Field("deliv", "entregável", value=deliv_shown, ph="só o número, no projeto escolhido (9 → P1.9), ou P#.n",
                  check=self._deliv_check, res=self._deliv_res),
            Field("blocked", "bloqueada por", value=blocked0, ph="A-#### (a CLI não remove bloqueio)"),
            Field("people", "pessoas", ph="adiciona: marina-demo, heitor-demo"),
            Field("list", "lista", choice=["mine", "waiting", "watching"], value=a["list"]),
            Field("owner", "dono", value=owner0, ph="reatribui: id ou alias"),
            Field("note", "nota", ph="vai para o histórico da ação")], build))

    def f_due(self) -> None:
        a = self.cur().data

        def build(v):
            return [["action", "update", a["id"]] + (self._due_arg(v["due"]) or ["--clear-due"]) + ["--by", "owner"]]

        sub = ("Prazo sugerido pelo agente (rosa): salve com a mesma data para confirmar, ou digite outra."
               if a.get("due_suggested") else "Deixe em branco para remover o prazo.")
        self.form(FormSpec(f"Prazo de {a['id']}", [
            Field("due", "prazo", value=a["due"] or "", ph=dates.HELP, check=self._due_check, res=dates.describe)],
            build, sub=sub))

    def cycle_status(self) -> None:
        a = self.cur().data
        nxt = {"aberta": "fazendo", "fazendo": "aguardando", "aguardando": "aberta", "bloqueada": "fazendo"}.get(a["status"], "fazendo")
        self.exec([["action", "update", a["id"], "--status", nxt, "--by", "owner"]])

    def f_drop(self) -> None:
        a = self.cur().data
        self.form(FormSpec(f"Descartar {a['id']}", [Field("reason", "motivo", req=True, ph="projeto cancelado")],
                           lambda v: [["action", "drop", a["id"], "--reason", v["reason"] or "…", "--by", "owner"]],
                           sub="Não foi feita e não será. O histórico fica no ledger."))

    def f_reopen(self) -> None:
        a = self.cur().data
        self.form(FormSpec(f"Reabrir {a['id']}", [Field("reason", "motivo", req=True, ph="faltou a parte do México")],
                           lambda v: [["action", "reopen", a["id"], "--reason", v["reason"] or "…", "--by", "owner"]]))

    def f_chase(self) -> None:
        a = self.cur().data
        self.f_draft(to=a["owner"], text=f'Oi {a["owner_name"].split(" ")[0]}, como está "{a["title"]}"?',
                     ref=a["id"], why="prazo venceu" if a["overdue_days"] else "acompanhamento")

    def toggle_done(self) -> None:
        it = self.cur()
        d = it.data
        if d["status"] == "feito":
            self.exec([["plan", "deliverable", d["id"], "--status", "nao-iniciado", "--by", "owner"]])
            return
        self.form(FormSpec(f"Marcar {d['id']} como feito", [Field("ev", "evidência", ph="subiu em produção")],
                           lambda v: [["plan", "deliverable", d["id"], "--status", "feito"] + (["--evidence", v["ev"]] if v["ev"] else []) + ["--by", "owner"]],
                           sub=d["title"]))

    def f_deliv_state(self) -> None:
        d = self.cur().data
        self.form(FormSpec(f"Estado de {d['id']}", [Field("st", "estado", choice=["nao-iniciado", "em-andamento", "feito", "cancelado"], value=d["status"]),
                                                    Field("ev", "evidência", ph="opcional")],
                           lambda v: [["plan", "deliverable", d["id"], "--status", v["st"]] + (["--evidence", v["ev"]] if v["ev"] else []) + ["--by", "owner"]]))

    def f_progress(self) -> None:
        it = self.cur()
        nid = it.id
        chk = lambda v: "" if v.isdigit() and int(v) <= 100 else "Use um número de 0 a 100."  # noqa: E731
        self.form(FormSpec(f"Declarar progresso de {nid}", [Field("pct", "percentual", req=True, ph="0 a 100", check=chk),
                                                            Field("note", "nota", ph="cardápio andou; reforma não")],
                           lambda v: [["progress", nid, v["pct"] or "…"] + (["--note", v["note"]] if v["note"] else [])],
                           sub="Aparece ao lado do calculado; nunca o substitui.", render=True))

    def f_share(self) -> None:
        it = self.cur()
        kind = {"g": "goal", "p": "project"}.get(it.kind if it else "", "status")
        target = it.id if it and it.kind in ("g", "p") else ""

        def build(v):
            return [["share", v["kind"]] + ([v["target"]] if v["target"] and v["kind"] != "status" else []) + ["--format", v["fmt"]]]

        self.form(FormSpec("Exportar para um colega", [
            Field("kind", "tipo", choice=["project", "goal", "status", "period"], value=kind),
            Field("target", "alvo", value=target, ph="P1 · G1 · 2026-09-01:2026-09-30"),
            Field("fmt", "formato", choice=["md", "html"])], build,
            sub="Gera um documento autocontido, sem jargão interno, em vault/reports/share/.", render=False))

    def external(self, argv: list[str]) -> None:
        """Roda um programa interativo (editor, pager) devolvendo o terminal a ele enquanto dura."""
        try:
            with self.suspend():
                subprocess.run(argv, check=False)
        except SuspendNotSupported:           # driver sem suspensão (testes headless): roda sem terminal
            subprocess.run(argv, check=False, stdin=subprocess.DEVNULL)

    def edit_in_editor(self, text: str) -> str | None:
        """Edita `text` num arquivo .md temporário com o $VISUAL/$EDITOR; devolve o resultado (None se o editor falhou)."""
        editor = _editor_argv()
        fd, name = tempfile.mkstemp(suffix=".md", prefix="brain-nota-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            self.external([*editor, name])
            return Path(name).read_text(encoding="utf-8").strip("\n")
        except (OSError, ValueError) as e:
            self.log_line(f"não consegui abrir o editor: {e}", "red")
            return None
        finally:
            Path(name).unlink(missing_ok=True)

    def edit_plan(self) -> None:
        """Gate estrutural: edita goals.md, mostra o diff e só mantém com a sua aprovação digitada."""
        path = self.inst.planning_file
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        editor = _editor_argv()
        try:
            self.external([*editor, str(path)])
        except OSError as e:
            self.log_line(f"não consegui abrir o editor: {e}", "red")
            return
        after = path.read_text(encoding="utf-8") if path.exists() else ""
        if after == before:
            self.log_line("PLANNING/goals.md: nada mudou", "dim")
            return
        self.gate_for_plan(before, after)

    def gate_for_plan(self, before: str, after: str, pre: dict | None = None) -> None:
        diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), "goals.md (antes)", "goals.md (depois)", lineterm="", n=1))
        extra = Text()
        for ln in diff[:40]:
            extra.append(ln + "\n", "green" if ln.startswith("+") and not ln.startswith("+++") else "red" if ln.startswith("-") and not ln.startswith("---") else "dim")
        if len(diff) > 40:
            extra.append(f"… +{len(diff) - 40} linhas\n", "dim")
        path = self.inst.planning_file
        pre = pre or {}

        def restore() -> None:
            util.atomic_write(path, before)
            self.log_line("mudança do PLANNING descartada: goals.md voltou ao que era", "yellow")

        self.form(FormSpec(
            "Mudança na árvore do plano",
            [Field("diff", "resumo do diff", value=pre.get("diff", ""), req=True, ph="P5 nasce sob G2"),
             Field("reason", "motivo", value=pre.get("reason", ""), req=True, ph="nova frente de retenção MX"),
             Field("ev", "evidência", value=pre.get("ev", ""), ph="reunião de planejamento"),
             Field("quote", "sua aprovação", req=True, ph="digite a resposta literal, ex.: ok")],
            lambda v: [["plan", "log", "--diff", v["diff"] or "…", "--reason", v["reason"] or "…"] + (["--evidence", v["ev"]] if v["ev"] else []) + ["--approval", v["quote"] or "…"]],
            sub="Único gate estrutural: criar, renomear ou fechar goal e projeto exige a sua aprovação. "
                "Cancelar desfaz a edição do goals.md.", gate=True, extra=extra, on_cancel=restore))

    def f_accept(self) -> None:
        r = self.cur().data
        fields = [Field("quote", "sua resposta", req=True, ph="ok, pode fechar")]
        if r.kind == "fechar-acao":
            fields.append(Field("how", "como foi", value=r.summary, req=True))
        if r.kind == "reestimar":
            fields.append(Field("effort", "novo esforço", req=True, ph="90m · 2h · 1h30", check=self._effort_check))

        def build(v):
            cmds = [["proposal", "accept", r.id, "--quote", v["quote"] or "…"]]
            if r.kind == "fechar-acao" and r.target:
                cmds.append(["action", "close", r.target, "--how", v.get("how") or "…", "--by", "owner"])
            if r.kind == "reestimar" and r.target:
                cmds.append(["action", "update", r.target, "--effort", v.get("effort") or "…", "--by", "owner"])
            return cmds

        def after() -> None:
            if r.kind == "mudar-plano":
                self.log_line("Proposta aceita. Para executar a mudança do plano, use E (gate) no painel 3.", "yellow")
            elif r.kind in ("atualizar-acao", "outro"):
                self.log_line("Proposta aceita. Aplique a mudança na ação com e (editar), se for o caso.", "yellow")

        self.form(FormSpec(f"Aceitar {r.id}", fields, build, sub=r.summary, gate=True, after=after))

    def f_reject(self) -> None:
        r = self.cur().data
        self.form(FormSpec(f"Rejeitar {r.id}", [Field("quote", "sua resposta", req=True, ph="não, ainda falta o México")],
                           lambda v: [["proposal", "reject", r.id, "--quote", v["quote"] or "…"]], sub=r.summary))

    def _check_recipient(self, v: str) -> str:
        allow = self.store.allow()
        if v.startswith("#"):
            to = v
        else:
            cands = people_mod.resolve(self.store.brain.state, v) if v not in self.store.brain.state.people else [v]
            if not cands:
                return f"pessoa '{v}' não encontrada. Cadastre em Registro › Pessoas."
            if len(cands) > 1:
                return f"'{v}' é ambíguo: {', '.join(cands)}."
            to = cands[0]
        return "" if to in allow else f"'{to}' não está em [outbound].allow do config/brain.toml"

    def f_draft(self, to: str = "", text: str = "", ref: str = "", why: str = "") -> None:
        def build(v):
            c = ["outbox", "draft", "--to", v["to"] or "…", "--text", v["text"] or "…"]
            if v["ref"]:
                c += ["--ref", v["ref"]]
            if v["why"]:
                c += ["--why", v["why"]]
            return [c]

        def after() -> None:
            self.p, self.tab[4] = 4, 1
            self.set_sel(4, 0)
            self.redraw()

        self.form(FormSpec("Rascunhar mensagem no Slack", [
            Field("to", "para", value=to, req=True, ph="id da pessoa ou #canal", check=self._check_recipient),
            Field("text", "texto", value=text, req=True, ph="Oi …"),
            Field("ref", "ref", value=ref, ph="A-####"), Field("why", "por quê", value=why)], build,
            sub="O agente envia depois da sua aprovação, como você. O texto aprovado fica travado por hash.", after=after))

    def f_approve_msg(self) -> None:
        m = self.cur().data
        n = m["id"].split("-")[1].lstrip("0") or "0"
        self.form(FormSpec(f"Aprovar {m['id']} → {m['to_name']}", [Field("quote", "sua aprovação", req=True, ph=f"enviar {n}")],
                           lambda v: [["outbox", "approve", m["id"], "--quote", v["quote"] or "…"]],
                           sub="Você aprova este texto exato. Se mudar uma palavra, a aprovação cai.",
                           gate=True, extra=Text.assemble(("▌ ", "cyan"), m["text"])))

    def f_cancel_msg(self) -> None:
        m = self.cur().data
        self.form(FormSpec(f"Cancelar {m['id']}", [Field("reason", "motivo", ph="opcional")],
                           lambda v: [["outbox", "cancel", m["id"]] + (["--reason", v["reason"]] if v["reason"] else [])]))

    def f_focus_plan(self) -> None:
        chk = lambda v: "" if v.isdigit() and 1 <= int(v) <= 30 else "Use de 1 a 30 dias."  # noqa: E731
        self.form(FormSpec("Planejar foco", [Field("days", "horizonte (dias)", value=str(self.inst.cfg["focus"]["horizon_days"]), check=chk)],
                           lambda v: [["focus", "plan", "--days", v["days"] or "7"]],
                           sub="Blocos EDF nas suas ações mine com prazo. Nada vai ao calendário ainda.",
                           after=lambda: (self.tab.__setitem__(4, 2), self.redraw())))

    def f_focus_approve(self) -> None:
        f = self.store.m["focus"]
        self.form(FormSpec(f"Aprovar plano {f['id']}", [Field("quote", "sua aprovação", req=True, ph="ok")],
                           lambda v: [["focus", "approve", f["id"], "--quote", v["quote"] or "…"]],
                           sub="Um ok libera o lote inteiro. Só depois dele o aplicar vira possível.", gate=True))

    def f_focus_apply(self) -> None:
        f = self.store.m["focus"]
        mode = self.inst.cfg["focus"]["mode"]
        self.form(FormSpec(f"Aplicar {f['id']}", [Field("mode", "modo", choice=["ics", "google"], value=mode)],
                           lambda v: [["focus", "apply", f["id"], "--mode", v["mode"]]],
                           sub="google cria só eventos marcados brain_focus=1 no calendário primário. ics gera um arquivo e não toca na API.",
                           gate=True))

    def focus_sync(self) -> None:
        self.form(FormSpec("Sincronizar o foco", [Field("mode", "o que fazer", choice=["só mostrar (dry-run)", "remover agora"])],
                           lambda v: [["focus", "sync"] + (["--dry-run"] if v["mode"].startswith("só") else [])],
                           sub="Blocos futuros de ações já fechadas: no modo google saem do calendário; no ics, o arquivo avisa.",
                           render=False))

    def f_pub_request(self) -> None:
        reports, dests = self.store.reports(), self.store.destinations()
        if not dests:
            self.log_line("Nenhum destino em [publish].destinations (config/brain.toml). A porta está fechada.", "red")
            return
        rf = Field("report", "report", choice=reports) if reports else Field("report", "report", req=True, ph="reports/share/… (gere com S no painel 3)")
        self.form(FormSpec("Pedir publicação", [rf, Field("to", "destino", choice=dests)],
                           lambda v: [["publish", "request", v["report"] or "…", "--to", v["to"]]],
                           sub="Uma aprovação por publicação. O conteúdo fica travado por hash.", render=False))

    def f_pub_approve(self) -> None:
        s = self.cur().data
        self.form(FormSpec(f"Aprovar {s['id']}", [Field("quote", "sua aprovação", req=True, ph="ok, publica")],
                           lambda v: [["publish", "approve", s["id"], "--quote", v["quote"] or "…"]],
                           sub=f"Publicar {s['report']} em {s['destination']}", gate=True))

    def pub_cancel(self) -> None:
        self.exec([["publish", "cancel", self.cur().data["id"]]])

    def f_decision(self) -> None:
        def build(v):
            c = ["decision", "add", v["title"] or "…", "--decided-by", v["by"] or "…"]
            if v["project"] not in ("", "—"):
                c += ["--project", v["project"]]
            if v["why"]:
                c += ["--rationale", v["why"]]
            return [c + ["--by", "owner"]]

        self.form(FormSpec("Registrar decisão", [Field("title", "título", req=True), Field("by", "quem decidiu", req=True, ph="marina-demo, sonia-demo"),
                                                 Field("project", "projeto", choice=["—"] + self.store.project_ids()), Field("why", "porquê", ph="opcional")], build))

    def f_supersede(self) -> None:
        d = self.cur().data
        self.form(FormSpec(f"Superar {d['id']}", [Field("reason", "motivo", req=True)],
                           lambda v: [["decision", "supersede", d["id"], "--reason", v["reason"] or "…", "--by", "owner"]], sub=d["title"]))

    def f_delivery(self) -> None:
        def build(v):
            c = ["delivery", v["title"] or "…"]
            for opt, key in (("--ref", "ref"), ("--result", "result"), ("--impact", "impact")):
                if v[key]:
                    c += [opt, v[key]]
            return [c + ["--by", "owner"]]

        self.form(FormSpec("Registrar entrega", [Field("title", "título", req=True), Field("ref", "ligada a", ph="P2 · A-#### · G1"),
                                                 Field("result", "resultado"), Field("impact", "impacto")], build,
                           sub="Conquista com resultado, sem precisar fechar uma ação."))

    def f_person(self) -> None:
        made: dict[str, str] = {}

        def build(v):
            made["id"] = v["id"] or util.slugify(v["name"] or "")
            c = ["person", "add", v["name"] or "…"]
            if v["id"]:
                c += ["--id", v["id"]]
            for a in [x.strip() for x in v["alias"].split(",") if x.strip()]:
                c += ["--alias", a]
            if v["role"]:
                c += ["--role", v["role"]]
            return [c + ["--relation", v["rel"], "--by", "owner"]]

        self.form(FormSpec("Nova pessoa", [Field("name", "nome", req=True), Field("id", "id curto", ph="derivado do nome"), Field("alias", "aliases", ph="Lu, Lu M."),
                                           Field("role", "papel"), Field("rel", "relação", choice=["par", "gestor", "stakeholder", "time"])], build,
                           after=lambda: made.get("id") and self.jump(made["id"])))

    def f_person_update(self) -> None:
        p = self.cur().data

        def build(v):
            c = ["person", "update", p["id"]]
            for opt, key, old in (("--name", "name", p["name"]), ("--role", "role", p["role"] or ""),
                                  ("--relation", "rel", p["relation"] or ""), ("--email", "email", p["email"] or "")):
                if v[key] and v[key] != old:
                    c += [opt, v[key]]
            return [c + ["--by", "owner"]]

        self.form(FormSpec(f"Editar {p['id']}", [Field("name", "nome", value=p["name"], req=True), Field("role", "papel", value=p["role"] or ""),
                                                 Field("rel", "relação", value=p["relation"] or ""), Field("email", "e-mail", value=p["email"] or "")], build,
                           sub="Para aliases novos use a. A CLI não apaga campos, só os troca."))

    def f_resolve(self) -> None:
        self.form(FormSpec("Quem é…?", [Field("text", "nome ou alias", req=True, ph="a Marina-demo")],
                           lambda v: [["person", "resolve", v["text"] or "…"]],
                           sub="Diz a quem o texto se refere, sem gravar nada. Ambíguo vira erro 2: a pergunta é sua.", render=False))

    def f_memory(self) -> None:
        self.form(FormSpec("Memória: perguntar", [Field("q", "pergunta", req=True, ph="o que foi decidido sobre o forno?"),
                                                  Field("mode", "como", choice=["recall", "reflect"]),
                                                  Field("bank", "banco", choice=["mem", "raw"]),
                                                  Field("tags", "tags", ph="proj:P1,pessoa:marina-demo (opcional)")],
                           lambda v: [["memory", v["mode"], v["q"] or "…", "--bank", v["bank"]] + (["--tags", v["tags"]] if v["tags"] else [])],
                           sub="recall devolve trechos; reflect pede uma resposta sintetizada. Confirme no arquivo do vault antes de afirmar.",
                           render=False, show="Memória"))

    def f_alias(self) -> None:
        p = self.cur().data
        def build(v):
            return [["person", "alias", p["id"]] + [a.strip() for a in v["al"].split(",") if a.strip()] + ["--by", "owner"]]
        self.form(FormSpec(f"Alias para {p['id']}", [Field("al", "aliases", req=True, ph="Mari-demo, M.-demo")], build,
                           sub="Evita uma segunda ficha para a mesma pessoa."))

    def open_raw(self) -> None:
        a = self.cur().data
        from .. import rawsort
        found = rawsort.resolve(self.inst, a["raw"] or "") if a["raw"] else None
        path = found.resolve() if found else None
        if not path or not path.is_relative_to(self.inst.vault.resolve()):
            self.log_line("RAW não encontrado para este artefato (ou fora do vault)", "yellow")
            return
        self.external([*shlex.split(os.environ.get("PAGER") or "less"), str(path)])

    # ── painel 1 ───────────────────────────────────────────────────────────
    def fix_doc(self) -> None:
        it = self.cur()
        fix = it.extra.get("fix") if it else None
        if not fix:
            return
        if fix.get("agent") == "dump":
            self.agent_dump()
        elif fix.get("agent") == "connect":
            self.agent_connect(fix["key"])
        elif fix.get("sys"):
            self.p = 1
            self.tab[1] = 3
            self.set_sel(1, [o["id"] for o in SYS_OPS].index(fix["sys"]))
            self.redraw()
        elif fix.get("go"):
            self.p, self.tab[2] = fix["go"]
            self.redraw()

    def run_selected_sys(self) -> None:
        it = self.cur()
        if it and it.kind == "sys":
            self.run_sys(it.id)

    def run_sys(self, op_id: str, apply: bool = False) -> None:
        op = next(o for o in SYS_OPS if o["id"] == op_id)
        if op.get("agent"):
            self.run_ai(op)
            return
        if op.get("form") == "memory":
            self.f_memory()
            return
        args = op["apply"] if apply else op["args"]
        if op.get("info"):
            self.log_line("$ brain mcp  (fica ouvindo em stdio; registre-o na outra IA: claude mcp add segundo-cerebro -- brain mcp)", "dim")
            return
        run = lambda: self.exec([args], render=False, show=op.get("show"))  # noqa: E731
        if op.get("door") or op.get("confirm") or apply:
            def done(ok) -> None:
                if ok:
                    run()
            self.push_screen(ConfirmModal(op["name"], op["desc"], args, op.get("door", "")), done)
        else:
            run()

    # ── agente ⚡ ──────────────────────────────────────────────────────────
    def ask_agent(self, title: str, bullets: list[str], prompt: str) -> None:
        argv = bridge.agent_argv(self.inst.cfg, prompt)

        def done(choice) -> None:
            if choice == "run":
                self.run_worker(self._agent(argv, prompt), exclusive=False)
            elif choice == "copy":
                self.copy_to_clipboard(prompt)
                self.log_line("prompt copiado: cole no chat do agente", "magenta")
        self.push_screen(AgentModal(title, bullets, prompt, argv), done)

    async def _agent(self, argv: list[str], prompt: str) -> None:
        async with self._lock:
            self.busy = "agente…"
            self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
            self.log_line("⚡ " + prompt.splitlines()[0][:100], "magenta")
            rc = await bridge.run_agent(self.inst, argv, lambda ln: self.log_line("  " + ln, "magenta") if ln else None)
            self.log_line("✓ agente terminou" if rc == 0 else f"✗ agente saiu com código {rc}", "green" if rc == 0 else "red")
            r = await asyncio.to_thread(bridge.run_brain, self.inst, ["render"])
            self.log_line("↻ brain render · " + (r.out.splitlines()[0] if r.out else "views regeneradas"), "dim")
            await self._reload()
            self.busy = ""
            self._quit_armed = False
            self.redraw()

    def run_ai(self, op: dict) -> None:
        """Comando de IA da aba Sistema: os cinco com fluxo próprio entram direto; os demais pedem o argumento (se houver) e abrem o modal ⚡."""
        own = {"/init": self.agent_init, "/dump": self.agent_dump, "/update": self.agent_update, "/connect": self.pick_source, "/brief": self.agent_brief}
        if op["agent"] in own:
            own[op["agent"]]()
            return
        cmd, bullets = op["agent"], op["do"]
        if not op.get("arg"):
            self.ask_agent(op["name"], bullets, cmd)
            return
        label, ph, req = op["arg"]
        field = Field("arg", label, ph=ph, req=req)
        self.form(FormSpec(op["name"], [field], lambda v: [], sub=op["desc"], render=False,
                           intercept=lambda v: self.ask_agent(op["name"], bullets, f"{cmd} {v['arg']}".strip()) or True))

    def agent_init(self) -> None:
        self.ask_agent("Primeira entrevista", ["Pergunta quem você é, seus goals, projetos e pessoas", "Monta PROFILE e PLANNING como proposta (diff)",
                                               "Só grava a árvore depois do seu ok (gate)"], "/init")

    def agent_dump(self) -> None:
        self.ask_agent("Processar a inbox", [f"Arquiva {self.store.inbox} item(ns) de vault/RAW/inbox/ em RAW/<ano>/<mês>/ (mover, nunca editar)",
                                              "Extrai decisões, ações e fatos com proveniência", "Grava tudo pelo ./brain e regenera as views"], "/dump")

    def agent_brief(self) -> None:
        self.ask_agent("Brief do dia", ["Lê FRESH/home.md e todo.md", "Escreve a narrativa em FRESH/notes/ (o painel exibe como está)"], "/brief")

    MCP_NOTE = "Precisa de permissão para as ferramentas MCP de leitura ([runner].allow ou [runner].command no brain.toml)"

    def agent_connect(self, key: str) -> None:
        self.ask_agent(f"Puxar a fonte {key}", ["Lê a fonte pelo MCP, só leitura", "Grava com brain snapshot (hash igual = silêncio)",
                                                "Processa a novidade (/dump só nesse item)", self.MCP_NOTE], f"/connect {key}")

    def agent_connect_selected(self) -> None:
        it = self.cur()
        if it and it.kind == "src":
            self.agent_connect(it.data["key"])

    def agent_update(self) -> None:
        keys = [x["key"] for x in self.store.sources if x["in_watch"]]
        if not keys:
            self.log_line("Nenhuma fonte no config/watch.toml: o /update não teria o que puxar. Painel 1, aba Fontes, tecla n.", "yellow")
            return
        shown = ", ".join(keys[:5]) + (f" e mais {len(keys) - 5}" if len(keys) > 5 else "")
        self.ask_agent("Atualizar tudo (/update)", [f"Lê {len(keys)} fonte(s) do watch.toml pelo MCP de leitura: {shown}",
                                                    "Grava cada leitura com brain snapshot (hash igual = silêncio)",
                                                    "Processa a inbox (/dump), roda o render e sincroniza a memória, se ligada", self.MCP_NOTE], "/update")

    def pick_source(self) -> None:
        srcs = [x for x in self.store.sources]
        if not srcs:
            self.log_line("Nenhuma fonte conhecida. Cadastre em Painel 1, aba Fontes, tecla n.", "yellow")
            return

        def source(q: str) -> list[PickItem]:
            f = util.fold(q)
            return [PickItem(Text.assemble((x["key"].ljust(26), "bold"), (x.get("kind") or "avulsa").ljust(8), ("" if x["in_watch"] else "fora do watch", "dim")), x["key"])
                    for x in srcs if f in util.fold(x["key"] + " " + (x.get("kind") or ""))]

        def done(item) -> None:
            if item:
                self.agent_connect(item.data)
        self.push_screen(PickerModal("Puxar qual fonte?", "digite para filtrar…", source), done)

    # ── fontes: watch.toml pela CLI (`brain watch`) ────────────────────────
    @staticmethod
    def _extras_check(v: str) -> str:
        from .. import watch
        for part in [p for p in v.split(";") if p.strip()]:
            k, sep, _ = part.partition("=")
            if not sep or not watch.FIELD_RE.match(k.strip()):
                return f"use campo=valor separados por ponto e vírgula (recebi {part.strip()!r})"
        return ""

    @staticmethod
    def _extras(v: str) -> dict:
        out = {}
        for part in [p for p in v.split(";") if p.strip()]:
            k, _, val = part.partition("=")
            out[k.strip()] = val.strip()
        return out

    def _source_fields(self, src: dict | None, key_locked: bool = False) -> list[Field]:
        from .. import watch
        src = src or {}
        known = {"key", "kind", "window", "channel", "jql", "note", "in_watch", "last_ok", "last_error", "failures", "pulls", "last_changed"}
        other = "; ".join(f"{k}={v}" for k, v in src.items() if k not in known)
        taken = {x["key"] for x in self.store.sources if x["in_watch"] and x["key"] != src.get("key")}

        def key_check(v: str) -> str:
            if not watch.KEY_RE.match(v):
                return "key: minúsculas, números, '.', '_' e '-' (ex.: slack-time-dados)"
            return "já existe uma fonte com essa key" if v in taken else ""

        return [Field("key", "key", value=src.get("key", ""), req=True, ph="slack-time-dados", check=key_check),
                Field("kind", "tipo", value=src.get("kind", ""), req=True, ph="gmail · slack · gcal · drive · jira"),
                Field("window", "janela", value=src.get("window", ""), ph="auto · 1d · 7d"),
                Field("channel", "canal", value=src.get("channel", ""), ph="#time-dados (slack)"),
                Field("jql", "jql", value=src.get("jql", ""), ph="consulta (jira)"),
                Field("note", "nota", value=src.get("note", ""), ph="para que serve esta fonte"),
                Field("other", "outros", value=other, ph="campo=valor; campo=valor", check=self._extras_check)]

    def _source_after(self, getkey) -> None:
        self.p, self.tab[1] = 1, 2
        self.redraw()
        k = getkey()
        if k:
            self.jump_source(k)

    def jump_source(self, key: str) -> None:
        self._items = {}
        ids = [i.id for i in self.items(1)]
        if f"src:{key}" in ids:
            self.set_sel(1, ids.index(f"src:{key}"))
        self.redraw()

    def f_source_add(self, pre: dict | None = None) -> None:
        made: dict[str, str] = {}

        def build(v):
            made["key"] = v["key"]
            c = ["watch", "add", v["key"] or "…", "--kind", v["kind"] or "…"]
            for opt, k in (("--window", "window"), ("--note", "note")):
                if v[k]:
                    c += [opt, v[k]]
            for k in ("channel", "jql"):
                if v[k]:
                    c += ["--set", f"{k}={v[k]}"]
            for k, val in self._extras(v["other"]).items():
                c += ["--set", f"{k}={val}"]
            return [c]

        self.form(FormSpec("Adicionar fonte ao watch.toml", self._source_fields(pre), build,
                           sub="Fonte que não está no watch.toml não é puxada pelo /update nem pelo noturno.",
                           render=False, after=lambda: self._source_after(lambda: made.get("key"))))

    def f_source_include(self) -> None:
        it = self.cur()
        if it and it.kind == "src":
            self.f_source_add({"key": it.data["key"]})

    def f_source_edit(self) -> None:
        old = self.cur().data
        made: dict[str, str] = {}

        def build(v):
            made["key"] = v["key"]
            c = ["watch", "edit", old["key"]]
            if v["key"] != old["key"]:
                c += ["--rename", v["key"]]
            for opt, k in (("--kind", "kind"), ("--window", "window"), ("--note", "note")):
                if v[k] != (old.get(k) or "") and v[k]:
                    c += [opt, v[k]]
            new = {k: v[k] for k in ("channel", "jql") if v[k]} | self._extras(v["other"])
            for k, val in new.items():
                if str(old.get(k, "")) != val:
                    c += ["--set", f"{k}={val}"]
            known = {"key", "kind", "in_watch", "last_ok", "last_error", "failures", "pulls", "last_changed"}
            for k in old:
                if k not in known and k not in new and (k != "window" or not v["window"]) and (k != "note" or not v["note"]):
                    c += ["--unset", k]
            return [c]

        self.form(FormSpec(f"Editar a fonte {old['key']}", self._source_fields(old), build,
                           sub="Mudar a key renomeia a fonte; o histórico de pulls fica na key antiga.",
                           render=False, after=lambda: self._source_after(lambda: made.get("key"))))

    def f_source_remove(self) -> None:
        key = self.cur().data["key"]

        def done(ok) -> None:
            if ok:
                self.exec([["watch", "remove", key]], render=False, after=lambda: self._source_after(lambda: None))
        self.push_screen(ConfirmModal(f"Remover a fonte {key}", "O /update e o noturno deixam de puxá-la. Snapshots já gravados e o ledger ficam como estão.",
                                      ["watch", "remove", key]), done)

    def agent_send(self) -> None:
        m = self.cur().data
        prompt = (f"Envie a mensagem {m['id']}, que o dono já aprovou. Leia `./brain outbox show {m['id']}` e envie EXATAMENTE esse texto "
                  f"pelo MCP do Slack, como o dono, para {m['to']}. Depois registre com `./brain outbox sent {m['id']} --link <permalink>`. "
                  "Se o texto divergir do aprovado ou o destinatário não estiver em [outbound].allow, pare e avise.")
        self.ask_agent(f"Enviar {m['id']} pelo Slack", ["Confere que o texto bate com o hash aprovado", f"Envia pelo Slack MCP como você para {m['to_name']}",
                                                        f"Registra o permalink: brain outbox sent {m['id']} --link …"], prompt)

    def agent_publish(self) -> None:
        s = self.cur().data
        prompt = (f"Publique o pedido {s['id']}, que o dono já aprovou: leia `./brain publish list`, publique o conteúdo de {s['report']} em "
                  f"{s['destination']} (Slack canvas ou Drive, conforme o destino) e registre com `./brain publish done {s['id']} --link <link>`. "
                  "Se o arquivo mudou depois da aprovação, pare e avise.")
        self.ask_agent(f"Publicar {s['id']}", ["Confere o hash do report", f"Posta em {s['destination']}", f"Registra o link: brain publish done {s['id']} --link …"], prompt)

    # ── paleta, busca, filtro, ajuda ───────────────────────────────────────
    def palette(self) -> None:
        def source(q: str) -> list[PickItem]:
            terms = util.fold(q).split()
            out = []
            for name, cmd, go in CMD_CATALOG:
                if all(t in util.fold(name + " " + cmd) for t in terms):
                    t = Text.assemble((name.ljust(30), "bold"), (cmd, "cyan"))
                    if go[2]:
                        t.append("   " + ("space" if go[2] == "space" else go[2]), "yellow")
                    out.append(PickItem(t, go))
            return out

        def done(item) -> None:
            if item:
                self.run_catalog(item.data)
        self.push_screen(PickerModal("Comandos", "digite para buscar: fechar, foco, backup…", source), done)

    def run_catalog(self, go: tuple) -> None:
        p, t, k = go[0], go[1], go[2]
        if p is None:
            if k == "g":
                self.search()
            elif k == "N":
                self.f_note()
            return
        self.p, self.tab[p] = p, t
        self.filt = None
        if len(go) > 3:
            self.set_sel(p, [o["id"] for o in SYS_OPS].index(go[3]))
        self.redraw()
        if k:
            self.press(k)

    def search(self) -> None:
        def source(q: str) -> list[PickItem]:
            if len(q) < 2:
                return []
            hits = search_mod.search(self.store.brain, q, limit=14)
            return [PickItem(Text.assemble((h["kind"].ljust(9), "dim"), (h["id"].split("/")[-1][:16].ljust(17), "cyan"), h["title"]), h) for h in hits]

        def done(item) -> None:
            if item:
                self.jump(item.data["id"])
        self.push_screen(PickerModal("Buscar no ledger e nos artefatos", "brain search …", source, empty="Nada encontrado. “Não consta” também é resposta."), done)

    def open_filter(self) -> None:
        if self.p == 6 or (self.p == 1 and self.tab[1] == 0):
            return
        key = (self.p, self.tab[self.p])

        def change(text: str) -> None:
            self.filt = (*key, text) if text else None
            self.redraw()
        self.push_screen(FilterModal(self.filt[2] if self.filt and self.filt[:2] == key else "", change))

    def help(self) -> None:
        name, tabs = PANELS[self.p]
        body = Text()
        body.append("Neste contexto\n", "dim")
        for k in self.ctx_keys():
            body.append(f"  {('space' if k.k == ' ' else k.k):<7}", "bold cyan")
            body.append(("⚡ " if k.agent else "◆ " if k.gate else "") + k.label + "\n")
        body.append("\nNavegação\n", "dim")
        for k, d in (("j k ↑ ↓", "mover na lista"), ("1-6", "ir ao painel (6 = log)"), ("[ ] ← →", "aba anterior / próxima (h l também)"),
                     ("enter", "ampliar o detalhe"), ("esc", "voltar")):
            body.append(f"  {k:<9}", "bold cyan")
            body.append(d + "\n")
        body.append("\nEm qualquer tela\n", "dim")
        for k, d in (("?", "esta ajuda"), (":", "paleta de comandos"), ("/", "filtrar a lista"), ("g", "buscar em tudo"), ("N", "nova nota na inbox"), ("r", "regenerar views"),
                     ("ctrl+t", "tema claro / escuro"), ("q", "sair")):
            body.append(f"  {k:<9}", "bold cyan")
            body.append(d + "\n")
        body.append("\n⚡ roda o agente  ·  ◆ pede aprovação digitada\n", "dim")
        self.push_screen(TextModal(f"Atalhos · {name} › {tabs[self.tab[self.p]]}", body))


def run(inst) -> None:
    BrainApp(inst).run()
