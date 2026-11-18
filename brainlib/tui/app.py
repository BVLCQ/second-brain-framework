"""BrainApp — o cockpit de terminal do ./brain (Textual).

Cinco painéis numerados à esquerda, detalhe à direita, o log de comandos (painel 6) embaixo dele e a barra
de teclas contextual no rodapé. Leitura é em processo (view model); toda escrita é `./brain <args>` como
subprocesso, e a linha exata aparece no log.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import RichLog, Static

from .. import dupes
from .. import opener
from .. import ids as idmod
from .. import notes as notes_mod
from .. import people as people_mod
from .. import planning
from .. import search as search_mod
from .. import util
from . import bridge, rows
from .modals import (AgentModal, ChoiceModal, ConfirmModal, Field, FilterModal, FormModal, FormSpec, PickerModal,
                     PickItem, TextModal)
from .ask_keys import AskKeys
from .config_keys import ConfigKeys
from .feedback_keys import FeedbackKeys
from .portfolio_keys import PortfolioKeys
from .store import ACTION_SORTS, ACTION_VIEWS, FACE_START, FACES, PLAN_TAB_STATUS, SYS_OPS, SYS_TAB, Item, Store

UCAP = 3                      # linhas visíveis de um painel sem foco


def _editor_argv() -> list[str]:
    """$VISUAL/$EDITOR como argv. Cursor e VS Code voltam na hora sem --wait: forçamos a espera."""
    argv = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
    if argv and Path(argv[0]).name in {"cursor", "code"} and not {"--wait", "-w"} & set(argv):
        argv.append("--wait")
    return argv

CMD_CATALOG = [               # paleta de comandos: nome, linha da CLI, (face, painel, aba, tecla[, id])
    ("Nova ação", 'brain action open "…" --by owner', (0, 2, 0, "n")),
    ("Fechar ação", 'brain action close TASK-#### --how "…"', (0, 2, 0, "c")),
    ("Editar ação", "brain action update TASK-#### …", (0, 2, 0, "e")),
    ("Prazo da ação", "brain action update TASK-#### --due …", (0, 2, 0, "t")),
    ("Descartar ação", 'brain action drop TASK-#### --reason "…"', (0, 2, 0, "d")),
    ("Reabrir ação", 'brain action reopen TASK-#### --reason "…"', (0, 2, 0, "o")),
    ("O que me devem", "brain action list --list waiting", (0, 2, 1, None)),
    ("Cobrar alguém", 'brain outbox draft --to … --text "…"', (0, 2, 1, "m")),
    ("Árvore do plano", "brain plan show", (0, 3, 0, None)),
    ("Marcar entregável", "brain plan deliverable PROJ-#.# --status …", (0, 3, 0, "space")),
    ("Declarar progresso", "brain progress GOAL-1 45", (0, 3, 0, "P")),
    ("Editar goal / projeto / entregável", 'brain plan edit GOAL-#|PROJ-#|PROJ-#.# … [--approval "ok"]', (0, 3, 0, "e")),
    ("Mudança estrutural (gate)", 'brain plan log --diff … --approval "ok"', (0, 3, 0, "E")),
    ("Novo goal (gate)", 'brain plan add-goal "…" --approval "ok"', (0, 3, 0, "G")),
    ("Novo projeto / entregável / ação no item (n)", "brain plan add-project|add-deliverable · brain action open", (0, 3, 0, "n")),
    ("Exportar para colega", "brain share project PROJ-1", (0, 3, 0, "S")),
    ("Perguntas do agente", "brain ask list --open", (0, 4, 0, None)),
    ("Responder pergunta do agente", 'brain ask answer ASK-#### "…" --by owner', (0, 4, 0, "a")),
    ("Descartar pergunta do agente", 'brain ask drop ASK-#### --reason "…"', (0, 4, 0, "d")),
    ("Retomar o agente com as respostas", "agente: claude -p --resume <sessão> (respostas dos ASK)", (0, 4, 0, "R")),
    ("Resposta livre ao agente", "agente: claude -p --resume <sessão> \"…\"", (None, None, None, "r")),
    ("Propostas pendentes", "brain proposal list", (0, 4, 1, None)),
    ("Aceitar proposta", 'brain proposal accept PROP-#### --quote "…"', (0, 4, 1, "a")),
    ("Rejeitar proposta", 'brain proposal reject PROP-#### --quote "…"', (0, 4, 1, "d")),
    ("Rascunhar mensagem", 'brain outbox draft --to … --text "…"', (0, 4, 2, "n")),
    ("Aprovar mensagem", 'brain outbox approve MSG-#### --quote "enviar N"', (0, 4, 2, "A")),
    ("Enviar mensagem aprovada", "agente → Slack MCP → brain outbox sent", (0, 4, 2, "S")),
    ("Planejar foco", "brain focus plan --days 5", (0, 4, 3, "p")),
    ("Aprovar plano de foco", 'brain focus approve FOCUS-#### --quote "ok"', (0, 4, 3, "A")),
    ("Aplicar foco na agenda", "brain focus apply FOCUS-#### --mode ics|google", (0, 4, 3, "a")),
    ("Pedir publicação", "brain publish request … --to slack:#canal", (0, 4, 4, "n")),
    ("Sugerir / reportar bug", 'brain feedback add "…" --kind sugestao|bug --body "…"', (0, 6, 1, "n")),
    ("Publicar feedback pendente", "brain feedback push FB-####", (0, 6, 1, "p")),
    ("Retirar rascunho de feedback", 'brain feedback withdraw FB-#### --reason "…"', (0, 6, 1, "d")),
    ("Retratar issue de feedback", 'brain feedback retract FB-#### --withdraw|--correct --reason "…"', (0, 6, 1, "r")),
    ("Sincronizar estado dos issues", "brain feedback sync", (0, 6, 1, "s")),
    ("Nova decisão", 'brain decision add "…" --decided-by …', (0, 5, 0, "n")),
    ("Registrar entrega", 'brain delivery "…" --ref …', (0, 5, 1, "n")),
    ("Saúde da instância", "brain doctor --online", (2, 2, 0, None)),
    ("Regenerar views", "brain render", (0, 1, 2, "enter", "sys:render")),
    ("Abrir painel HTML", "brain render --open", (0, 1, 2, "enter", "sys:open")),
    ("Validar ledger", "brain validate", (0, 1, 2, "enter", "sys:validate")),
    ("Backup do vault", "brain backup", (0, 1, 2, "enter", "sys:backup")),
    ("Atualizar framework", "brain update --check", (0, 1, 2, "enter", "sys:update")),
    ("Varredura upstream", "brain upstream scan", (0, 1, 2, "enter", "sys:upstream")),
    ("Memória: sincronizar", "brain memory sync", (0, 1, 2, "enter", "sys:memory")),
    ("Memória: perguntar", 'brain memory recall|reflect "…"', (0, 1, 2, "enter", "sys:recall")),
    ("Memória: status", "brain memory status", (0, 1, 2, "enter", "sys:memstatus")),
    ("Saúde online", "brain doctor --online", (2, 2, 0, "enter", "sys:doctor")),
    ("Colher edições do dono", "brain sync", (0, 1, 2, "enter", "sys:sync")),
    ("Backup: ver últimos", "brain backup --status", (0, 1, 2, "enter", "sys:backupst")),
    ("Agendamento: ver", "brain schedule status", (0, 1, 2, "enter", "sys:schedst")),
    ("Agendamento: remover", "brain schedule remove", (0, 1, 2, "enter", "sys:unsched")),
    ("Provedores da memória", "brain memory providers show", (2, 1, 0, "s")),
    ("Trocar provedor (formulário)", "brain memory providers set <slot> --provider …", (2, 1, 0, "s")),
    ("Wizard da memória", "brain setup --only memoria", (2, 1, 0, "w", "sys:wizmem")),
    ("Sincronizar o foco", "brain focus sync [--dry-run]", (0, 4, 3, "s")),
    ("Primeira entrevista", "agente: /init", (0, 1, 0, "i")),
    ("Cockpit da semana", "agente: /week", (0, 1, 3, "enter", "sys:ai-week")),
    ("Ler emails", "agente: /gmail [filtro]", (0, 1, 3, "enter", "sys:ai-gmail")),
    ("Ler Slack", "agente: /slack #canal [período]", (0, 1, 3, "enter", "sys:ai-slack")),
    ("Ler doc do Drive", "agente: /drive <termo|id>", (0, 1, 3, "enter", "sys:ai-drive")),
    ("Ler a agenda", "agente: /calendar [janela]", (0, 1, 3, "enter", "sys:ai-calendar")),
    ("Recap", "agente: /recap <GOAL-#|PROJ-#|período>", (0, 1, 3, "enter", "sys:ai-recap")),
    ("Reconciliar o framework", "agente: /upgrade", (0, 1, 3, "enter", "sys:ai-upgrade")),
    ("Atualizar tudo", "agente: /update", (0, 1, 0, "u")),
    ("Puxar uma fonte", "agente: /connect <fonte>", (0, 1, 0, "c")),
    ("Fontes do watch.toml", "brain watch list", (0, 1, 2, None)),
    ("Adicionar fonte", "brain watch add KEY --kind …", (0, 1, 2, "n")),
    ("Editar fonte", "brain watch edit KEY …", (0, 1, 2, "e")),
    ("Remover fonte", "brain watch remove KEY", (0, 1, 2, "d")),
    ("Processar a inbox", "agente: /dump", (0, 1, 0, "d")),
    ("Brief do dia", "agente: /brief", (0, 1, 0, "b")),
    ("Buscar no ledger", 'brain search "…"', (None, None, None, "g")),
    ("Nova nota", 'brain note add --link TASK-#### --text "…"', (None, None, None, "N")),
    ("Ver o log de comandos", "painel 6", (0, 6, 0, None)),
    # face Portfólio
    ("Visão do portfólio", "brain opportunity list --sort score", (1, 1, 0, None)),
    ("Abrir mapa de oportunidades (HTML)", "brain render --open portfolio", (1, 1, 0, "o")),
    ("Processos", "brain process list", (1, 2, 0, None)),
    ("Processos com lacuna", "brain process list --gaps", (1, 2, 2, None)),
    ("Novo processo", 'brain process add "…" --area … --owner …', (1, 2, 0, "n")),
    ("Editar processo", "brain process update PROC-#### …", (1, 2, 0, "e")),
    ("Ligar documento", "brain doc link PROC-####|OPP-#### --kind … --ref …", (1, 2, 0, "L")),
    ("Abrir playbook", "abre o doc do playbook do processo", (1, 2, 0, "o")),
    ("Aposentar processo", 'brain process retire PROC-#### --reason "…"', (1, 2, 0, "d")),
    ("Oportunidades", "brain opportunity list", (1, 3, 0, None)),
    ("Nova oportunidade", 'brain opportunity add "…" --area …', (1, 3, 0, "n")),
    ("Editar oportunidade", "brain opportunity update OPP-#### …", (1, 3, 0, "e")),
    ("Status da oportunidade", "brain opportunity status OPP-#### <status>", (1, 3, 0, "s")),
    ("ICE da oportunidade", "brain opportunity score OPP-#### --impact … --confidence … --ease …", (1, 3, 0, "i")),
    ("Metodologia ICE", "brain opportunity rubric", (None, None, None, "icehelp")),
    ("Confirmar ICE sugerido", "brain opportunity score OPP-#### (valores sugeridos)", (1, 3, 0, "c")),
    ("Evidência da oportunidade", "brain opportunity evidence OPP-#### --source …", (1, 3, 0, "v")),
    ("One-pager da oportunidade", "agente: /opportunity onepager OPP-####", (1, 3, 0, "O")),
    ("Promover oportunidade (gate)", 'brain opportunity promote OPP-#### --level goal|project|deliverable … --approval "ok"', (1, 3, 0, "p")),
    ("Descartar oportunidade", 'brain opportunity status OPP-#### descartada --reason "…"', (1, 3, 0, "d")),
    ("Matriz impacto × facilidade", "brain opportunity list --sort score", (1, 4, 0, None)),
    ("Áreas", "brain area list", (1, 5, 0, None)),
    ("Nova área", 'brain area add <slug> --name "…"', (1, 5, 0, "n")),
    ("Editar área", "brain area update <slug> …", (1, 5, 0, "e")),
    ("Documentos ligados", "brain doc link … · brain doc unlink …", (1, 5, 1, None)),
    ("Desligar documento", "brain doc unlink PROC-####|OPP-#### --ref …", (1, 5, 1, "d")),
    ("Nova pessoa", 'brain person add "…" --id …', (1, 5, 2, "n")),
    ("Editar pessoa", "brain person update ID …", (1, 5, 2, "e")),
    ("Quem é…?", 'brain person resolve "…"', (1, 5, 2, "R")),
]


# Teclas que mudaram na padronização (2.10): ainda funcionam, escondidas, por uma versão. (face, painel, aba|None) → {antiga: nova}
KEY_ALIASES = {
    (0, 2, None): {"D": "d", "a": "T"},          # Ações: descartar e alternar "todas"
    (1, 5, 2): {"u": "e"},                       # Registro › Pessoas: editar
}


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
    tab_spans: list[tuple[int, int, int]] = []      # abas do painel 6 desenhadas no título (Log · Feedback)

    def on_click(self, event: events.Click) -> None:
        if event.y == 0:                            # linha do título: clique em aba troca (como nos painéis de lista)
            for x0, x1, i in self.tab_spans:
                if x0 + 1 <= event.x <= x1 + 2:
                    self.app.p, self.app.tab[6] = 6, i
                    self.app.redraw()
                    return
        self.app.goto_panel(6)


class BrainApp(ConfigKeys, AskKeys, FeedbackKeys, PortfolioKeys, App):
    CSS_PATH = "tui.tcss"
    TITLE = "brain"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, inst) -> None:
        super().__init__()
        self.inst = inst
        self.store: Store | None = None
        self.face = 0                 # índice em FACES; a navegação de cada face fica em self.nav[face]
        self.nav = [self._new_nav(start) for start in FACE_START]
        self.collapsed: set[str] = set()
        self._lock: asyncio.Lock | None = None
        self.busy = ""
        self._quit_armed = False
        self._suggest_for: str | None = None
        self.pending_reply = False      # a última rodada deixou perguntas/permissões: `r` vira resposta livre
        self.last_run = None            # RunInfo da última rodada do agente com sessão (a resposta livre `r` a retoma)

    @staticmethod
    def _new_nav(start: int) -> dict:
        """Estado de navegação de uma face: cada face volta exatamente onde estava."""
        return {"p": start, "lp": start,   # lp: último painel de lista (1-5) em foco; o log (6) mantém o detalhe dele
                "tab": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}, "sel_idx": {}, "sel_id": {}, "win": {},
                "filt": None, "zoom": False, "show_all": False, "view": 0, "sort": 0, "source_sort": 0, "items": {}}

    # As propriedades abaixo apontam para a face atual: o resto do app lê e escreve `self.p`, `self.tab[p]`,
    # `self.filt`… sem saber de faces. Trocar de face é só trocar `self.face`.
    @property
    def _nv(self) -> dict:
        return self.nav[self.face]

    @property
    def panels(self) -> dict:
        return FACES[self.face][1]

    @property
    def p(self) -> int:
        return self._nv["p"]

    @p.setter
    def p(self, v: int) -> None:
        self._nv["p"] = v
        if v != 6:
            self._nv["lp"] = v

    @property
    def lp(self) -> int:
        return self._nv["lp"]

    @property
    def tab(self) -> dict:
        return self._nv["tab"]

    @property
    def sel_idx(self) -> dict:
        return self._nv["sel_idx"]

    @property
    def sel_id(self) -> dict:
        return self._nv["sel_id"]

    @property
    def win(self) -> dict:
        return self._nv["win"]

    @property
    def filt(self) -> tuple | None:
        """(painel, aba, filtro 1, filtro 2, …): filtros em cascata de UMA lista — cada um refina o anterior."""
        return self._nv["filt"]

    @filt.setter
    def filt(self, v) -> None:
        self._nv["filt"] = v

    def filt_levels(self, key: tuple[int, int] | None = None) -> list[str]:
        """Os filtros em cascata aplicados à lista `key` (padrão: a atual), do primeiro ao último; [] se não há."""
        key = key or (self.p, self.tab[self.p])
        return [f for f in self.filt[2:] if f] if self.filt and tuple(self.filt[:2]) == tuple(key) else []

    def set_filt_levels(self, key: tuple[int, int], levels: list[str]) -> None:
        self.filt = (*key, *levels) if levels else None

    @staticmethod
    def filt_label(levels: list[str]) -> str:
        return " › ".join(levels)

    @property
    def zoom(self) -> bool:
        return self._nv["zoom"]

    @zoom.setter
    def zoom(self, v: bool) -> None:
        self._nv["zoom"] = v

    @property
    def view(self) -> int:
        return self._nv["view"]

    @view.setter
    def view(self, v: int) -> None:
        self._nv["view"] = v

    @property
    def sort(self) -> int:
        return self._nv["sort"]

    @sort.setter
    def sort(self, v: int) -> None:
        self._nv["sort"] = v

    @property
    def source_sort(self) -> int:
        return self._nv["source_sort"]

    @source_sort.setter
    def source_sort(self, v: int) -> None:
        self._nv["source_sort"] = v

    @property
    def show_all(self) -> bool:
        return self._nv["show_all"]

    @show_all.setter
    def show_all(self, v: bool) -> None:
        self._nv["show_all"] = v

    @property
    def _items(self) -> dict:
        return self._nv["items"]

    @_items.setter
    def _items(self, v: dict) -> None:
        self._nv["items"] = v

    def _summary_on(self) -> bool:
        """Painel 1 › Resumo da face Execução: o placar fixo (sem lista, sem seleção)."""
        return self.face == 0 and self.p == 1 and self.tab[1] == 0

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
                yield ListPanel(6)              # aba Feedback: lista no lugar do log (painel 6, aba 1)
        with Horizontal(id="facebar"):
            yield Static("", id="faces")
            yield Static("", id="facehint")
        with Horizontal(id="bar"):
            yield Static("", id="hints")
            yield Static("", id="globals")

    async def on_mount(self) -> None:
        self._lock = asyncio.Lock()
        self.query_one("#detailwrap").border_title = "Detalhe"
        for pid in (1, 2, 3, 4, 5, 6):
            self.query_one(f"#p{pid}").styles.border_subtitle_align = "right"
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
                if self.face == 0 and p == 1 and self.panels.get(1, ("", []))[1][t:t + 1] == [SYS_TAB]:
                    self._items[key] = [Item(o["id"], "sys", o) for o in SYS_OPS]
                else:
                    self._items[key] = []
            else:
                sort_arg = (self.source_sort if (self.face == 0 and p == 1 and t == 1)
                            else (self.sort if p == 2 and self.face == 0 else 0))
                self._items[key] = self.store.items(self.face, p, t, self.show_all, self.filt_levels(key), self.collapsed,
                                              self.view if p == 2 and self.face == 0 else 0, sort_arg)
        return self._items[key]

    @staticmethod
    def _skip_header(its: list[Item], i: int, step: int = 1) -> int:
        i = min(max(i, 0), len(its) - 1)
        if its[i].kind != "sgrp":
            return i
        d = 1 if step >= 0 else -1
        for j in range(i + d, len(its) if d > 0 else -1, d):
            if its[j].kind != "sgrp":
                return j
        for j in range(i - d, -1 if d > 0 else len(its), -d):
            if its[j].kind != "sgrp":
                return j
        return i

    def sel_index(self, p: int) -> int:
        key = (p, self.tab[p])
        its = self.items(p)
        if not its:
            return 0
        want = self.sel_id.get(key)
        if want is not None:
            for i, it in enumerate(its):
                if it.id == want and it.kind != "sgrp":
                    self.sel_idx[key] = i
                    return i
        i = self._skip_header(its, self.sel_idx.get(key, 0), 1)
        self.sel_idx[key] = i
        self.sel_id[key] = its[i].id
        return i

    def set_sel(self, p: int, i: int, step: int = 1) -> None:
        key, its = (p, self.tab[p]), self.items(p)
        if not its:
            return
        i = self._skip_header(its, i, step)
        self.sel_idx[key], self.sel_id[key] = i, its[i].id

    def cur(self) -> Item | None:
        p = self.p
        if p == 6 and self.tab[6] != 1:         # no log em si o detalhe é o da última lista (lp)
            p = self.lp
        its = self.items(p)
        return its[self.sel_index(p)] if its else None

    def fill_panel(self) -> int:
        return 2 if (self.face == 0 and self.lp == 1 and self.tab[1] == 0) else self.lp

    # ── desenho ────────────────────────────────────────────────────────────
    def panel_body(self, pid: int, width: int, height: int) -> Text:
        if self.store is None:
            return Text("Sem dados: ledger ilegível.", "red")
        t = self.tab[pid]
        if self.face == 0 and pid == 1 and t == 0:
            return self._summary()
        its = self.items(pid)
        if not its:
            f = self.filt_label(self.filt_levels((pid, t)))
            if f:
                return Text(f'nada para "{f}"  ·  esc tira o último filtro', "dim")
            if (pid, t) == (6, 1):
                return Text("vazio — n registra sugestão/bug (vira issue no GitHub)", "dim")
            return Text("vazio", "dim")
        idx = self.sel_index(pid)
        cap = max(1, height) if (pid == self.fill_panel() or pid == 6 and self.p == 6) else UCAP
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
        t.append(f" rascunho{'' if drafts == 1 else 's'}")
        asks = len(s.open_asks())
        if asks:
            t.append("  ")
            t.append(f"{asks}", "bold magenta")
            t.append(f" pergunta{'' if asks == 1 else 's'} ⚡", "magenta")
        t.append("\n")
        t.append(f" {s.inbox}", "bold magenta" if s.inbox else "bold")
        t.append(" inbox" + (" ⚡" if s.inbox else "") + "  ", "magenta" if s.inbox else "")
        t.append(f"{c['wins_30d']}", "bold")
        t.append(" conquistas  ")
        t.append(f"{c['mine_no_due']}", "bold yellow" if c["mine_no_due"] else "bold")
        t.append(" sem prazo")
        return t

    def _title(self, pid: int) -> Text:
        if pid not in self.panels:                       # painel que a face atual não define
            return Text(f" [{pid}] ", "dim")
        name, tabs = self.panels[pid]
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
        if pid == 2 and self.face == 0 and self.view:
            t.append(f" · vista {ACTION_VIEWS[self.view]}", "bold magenta")
        if pid == 2 and self.face == 0 and self.sort:
            t.append(f" · ordem {ACTION_SORTS[self.sort].lower()}", "bold magenta")
        if pid == 1 and self.face == 0 and self.tab[1] == 1 and self.source_sort:
            t.append(" · ordem ↑ antigo", "bold magenta")
        lv = self.filt_levels((pid, self.tab[pid]))
        if lv:
            t.append(f" · ⌕ filtro: {self.filt_label(lv)}", "bold magenta")
        t.append(" ")
        self.query_one(f"#p{pid}", ListPanel).tab_spans = spans
        return t

    def _badge(self, pid: int, i: int) -> str:
        if self.store is None or self.face not in (0, 2):
            return ""
        if self.face == 2:
            n = sum(1 for h in self.store.health if h["level"] != "ok") if (pid, i) == (2, 0) else 0
            return str(n) if n else ""
        c, m = self.store.counts, self.store.m
        n = 0
        if pid == 4:
            if i == 0:
                n = len(self.store.open_asks())
            elif i == 1:
                n = c["proposals_open"]
            elif i == 2:
                n = sum(1 for x in m["outbox"] if x["status"] in ("rascunho", "aprovada"))
            elif i == 3:
                n = 1 if m["focus"] and m["focus"]["status"] == "proposto" else 0
            elif i == 4:
                n = sum(1 for s in m["shares"] if s["status"] in ("solicitada", "aprovada"))
        if pid == 3 and i:
            st = PLAN_TAB_STATUS[i] if i < len(PLAN_TAB_STATUS) else ""
            n = sum(1 for x in m["goals"] + m["projects"] if x["status"] == st)
        if pid == 6 and i == 1:
            n = sum(1 for f in self.store.brain.state.feedbacks.values() if f.status in ("pendente", "falhou"))
        if pid == 1 and i == 1:
            n = sum(1 for x in self.store.sources if x.get("enabled", True) and x["failures"])
        return str(n) if n else ""

    def redraw(self) -> None:
        self._items = {}
        if not self.is_mounted or not self.screen_stack:
            return
        fill = self.fill_panel()
        for pid in (1, 2, 3, 4, 5):
            panel = self.query_one(f"#p{pid}", ListPanel)
            live = pid in self.panels                     # face pode não definir todos os painéis (Configurações: 1-2)
            panel.set_class(live and pid == self.p, "-on")
            compact = self.face == 0 and pid == 1 and self.tab[1] == 0
            panel.set_class(live and pid == fill and not compact, "-fill")
            panel.border_title = self._title(pid)
            n = len(self.items(pid)) if self.store and live and not compact else 0
            panel.border_subtitle = self._panel_subtitle(pid, n)
            panel.refresh(layout=True)
        cur = self.cur()
        self.query_one("#detail", Static).update(rows.detail(self.store, cur if hasattr(cur, "kind") else None) if self.store else Text(""))
        self.query_one("#detailwrap").scroll_home(animate=False)
        self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
        log, on = self.query_one("#log"), self.p == 6
        fb = on and self.tab[6] == 1                   # aba Feedback: a lista ocupa o lugar do log
        fbp = self.query_one("#p6", ListPanel)
        log.set_class(on and not fb, "-on")
        log.display = not fb
        fbp.display = fb
        self.query_one("#detailwrap").set_class(on, "-small")
        log.border_title = self._title(6)              # abas à vista também no log: Log · Feedback (clicável)
        log.tab_spans = fbp.tab_spans
        log.border_subtitle = " j k rolam · c limpa · 1-5 voltam " if on and not fb else ""
        if fb:
            fbp.set_class(True, "-on")
            fbp.border_title = self._title(6)
            n = len(self.items(6)) if self.store else 0
            fbp.border_subtitle = self._panel_subtitle(6, n)
            fbp.refresh(layout=True)
        self.set_class(self.zoom, "-zoom")
        self.refresh_faces()
        self.refresh_hints()

    def _panel_subtitle(self, pid: int, n: int) -> Text | str:
        """`3 de 12`; com filtro em cascata, `3 de 12 · de 80 sem filtro` — o total sem filtro deixa claro que há corte."""
        if not n:
            return ""
        t = Text(f" {self.sel_index(pid) + 1} de {n} ")
        key = (pid, self.tab[pid])
        if self.store and self.filt_levels(key):
            sort_arg = (self.source_sort if (self.face == 0 and pid == 1 and key[1] == 1)
                        else (self.sort if pid == 2 and self.face == 0 else 0))
            total = len(self.store.items(self.face, pid, key[1], self.show_all, "", self.collapsed,
                                         self.view if pid == 2 and self.face == 0 else 0, sort_arg))
            t.append(f"· filtrado de {total} ", "bold magenta")
        return t

    def _detail_subtitle(self) -> str:
        bits = []
        if self.zoom:
            bits.append("ampliado · esc volta")
        lv = self.filt_levels()
        if lv:
            bits.append(f"filtro: {self.filt_label(lv)}")
        if self.busy:
            bits.append(self.busy)
        return " · ".join(bits)

    def refresh_faces(self) -> None:
        """Faixa de faces na linha de cima: `Execução · [Portfólio]`, a atual em negrito e entre colchetes; clicar troca."""
        t = Text(no_wrap=True)
        t.append(" ")
        for i, (name, _) in enumerate(FACES):
            click = Style(meta={"@click": f"app.face_to({i})"})
            if i:
                t.append(" · ", "dim")
            if i == self.face:
                t.append(f"[{name}]", Style.parse("bold") + click)
            else:
                t.append(name, Style.parse("dim") + click)
        self.query_one("#faces", Static).update(t)
        hint = Text(no_wrap=True)
        hint.append("tab ", "bold cyan")
        hint.append("⇄ face ", "dim")
        self.query_one("#facehint", Static).update(hint)

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
        local = {k.k for k in self.ctx_keys()}
        lv = self.filt_levels()
        for k, lab in ((("esc", f"tira filtro ({len(lv)})"),) if lv else ()) + (("?", "ajuda"), (":", "comandos"), ("N", "nota"), ("/", "refinar filtro" if lv else "filtrar"), ("g", "buscar"),
                       ("r", "resposta ao agente" if self.pending_reply else "render"), ("q", "sair")):
            if k not in local:                     # a tecla de contexto vence: não anuncia o global que ela esconde
                hint(right, k, lab, "cyan")
        ver = self._version_badge()
        right.append(Text("  " + ver[0], ver[1]))
        self.query_one("#hints", Static).update(left)
        g = self.query_one("#globals", Static)
        g.update(right)
        g.styles.width = right.cell_len + 1

    def _version_badge(self) -> tuple[str, str]:
        """(texto, estilo) — versão local + aviso de atualização (cache, sem rede)."""
        from .. import __version__ as ver, upstream
        try:
            c = upstream.read_check_cache(self.inst)
            if (c.get("behind") or 0) > 0:
                return f"v{ver} · atualização ({c['behind']})", "bold yellow"
        except Exception:                              # noqa: BLE001 — badge nunca derruba a TUI
            pass
        return f"v{ver}", "dim"

    # ── log ────────────────────────────────────────────────────────────────
    def log_line(self, text: str, style: str = "") -> None:
        t = Text()
        t.append(util.now().strftime("%H:%M ") if self.is_mounted else "", "dim")
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
        if self.face == 0 and pid == 1 and self.tab[1] == 0:
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
        if self.face == 0 and pid == 1 and self.tab[1] == 0:
            return
        self.p = pid
        self.move(d)

    def action_hint(self, key: str) -> None:
        self.handle("escape" if key == "esc" else key)

    def action_jump(self, node: str) -> None:
        self.jump(node)

    def action_open_file(self, rel: str) -> None:
        """Clique num arquivo linkado: abre no aplicativo da máquina ([tui.open]); só lê, nunca escreve."""
        try:
            app = opener.open_file(self.inst, rel)
        except util.BrainError as e:
            self.log_line(str(e), "yellow")
            return
        self.log_line(f"abrindo {Path(rel).name} → {app}", "dim")

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
            self.free_reply() if self.pending_reply else self.do_render()
        elif k == "N":
            self.f_note()
        elif k == "`":                             # console: abre/fecha o log (o painel HTML tem a mesma tecla)
            self.toggle_log()
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
            elif self.filt:                         # esc tira um filtro por vez: o último aplicado primeiro
                self.filt = (*self.filt[:-1],) if len(self.filt) > 3 else None
                self.redraw()
        else:
            return self.press(k)
        return True

    def press(self, k: str) -> bool:
        k = "enter" if k == "\r" else k
        if k == "enter" and (self.p == 6 or self._summary_on()):
            return False
        for key in self.ctx_keys():
            if key.k == k:
                key.fn()
                return True
        new = self.key_alias(k)
        if new:                                    # tecla antiga, ainda aceita (e escondida) por uma versão
            for key in self.ctx_keys():
                if key.k == new:
                    key.fn()
                    return True
        if k == "enter":
            self.zoom = not self.zoom
            self.redraw()
            return True
        return False

    def key_alias(self, k: str) -> str:
        """Teclas que mudaram na padronização (2.10) e que ainda funcionam, sem aparecer nas dicas nem na ajuda:
        antigo → novo, por contexto (face, painel, aba; None = qualquer aba). Saem na versão seguinte."""
        for (face, p, t), table in KEY_ALIASES.items():
            if face == self.face and p == self.p and t in (None, self.tab[self.p]) and k in table:
                return table[k]
        return ""

    def face_move(self, d: int) -> None:
        """Tab / Shift+Tab: próxima / anterior face, em carrossel. Cada face guarda onde estava (painel, aba, seleção, zoom, filtro)."""
        self.face_to((self.face + d) % len(FACES))

    def face_to(self, i: int) -> None:
        if self.store is None or not 0 <= i < len(FACES) or i == self.face:
            return
        self.face = i
        self.redraw()

    def action_face_to(self, i: int) -> None:
        if len(self.screen_stack) == 1:
            self.face_to(i)

    # Tab/Shift+Tab são do Textual para mudar o foco (os formulários em modals.py dependem disso). Na tela principal
    # não há nada focável, então a tecla gira as faces; em qualquer modal, o comportamento padrão continua valendo.
    def action_focus_next(self) -> None:
        if len(self.screen_stack) == 1:
            self.face_move(1)
        else:
            super().action_focus_next()

    def action_focus_previous(self) -> None:
        if len(self.screen_stack) == 1:
            self.face_move(-1)
        else:
            super().action_focus_previous()

    def toggle_log(self) -> None:
        if self.p == 6:
            self.goto_panel(getattr(self, "_before_log", 0) or 2)
        else:
            self._before_log = self.p
            self.goto_panel(6)

    def goto_panel(self, p: int) -> None:
        self.p = ((p - 1) % 6) + 1
        if self.p == 6:
            self.zoom = False
        self.redraw()

    def tab_move(self, d: int) -> None:
        if self.p not in self.panels:
            return
        n = len(self.panels[self.p][1])
        self.tab[self.p] = min(max(self.tab[self.p] + d, 0), n - 1)
        self.redraw()

    def move(self, d: int) -> None:
        if self.p == 6 and self.tab[6] == 0:
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
        if self._summary_on():
            return
        its = self.items(self.p)
        if not its:
            return
        self.set_sel(self.p, self.sel_index(self.p) + d, step=1 if d >= 0 else -1)
        self.redraw()

    def jump(self, node: str) -> None:
        if self.store is None:
            return
        node = idmod.normalize(node)
        loc = self.store.locate(node)
        if not loc:
            self.log_line(f"{node}: não encontrei onde mostrar", "dim")
            return
        face, p, t = loc
        self.face = face
        self.p, self.tab[p] = p, t
        self.zoom, self.filt = False, None
        if p == 3 and node.startswith("PROJ-"):
            proj = node.split(".")[0]
            self.collapsed.discard(proj)
            if proj in self.store.by_project:
                self.collapsed.discard(self.store.by_project[proj]["goal"])
        self._items = {}
        ids = [i.id for i in self.items(p)]
        if node not in ids and p in (2, 4):
            self.show_all, self._items = True, {}
            if p == 2 and self.face == 0:
                self.view = 0                      # a ação saltada pode estar fora da vista atual
            ids = [i.id for i in self.items(p)]
        if node in ids:
            self.set_sel(p, ids.index(node))
        self.redraw()

    # ── contexto de teclas ─────────────────────────────────────────────────
    def ctx_keys(self, every: bool = False, panel: int | None = None, tab: int | None = None) -> list[Key]:
        """Teclas do contexto atual. `every=True` lista todas, sem olhar o item (para o mapa de teclas)."""
        p = self.p if panel is None else panel
        if p not in self.panels:
            return []
        t = self.tab[p] if tab is None else tab
        it = None if every else self.cur()
        if it is not None and not hasattr(it, "kind"):
            it = None
        K: list[Key] = []
        add = lambda k, label, fn, **kw: K.append(Key(k, label, fn, **kw))  # noqa: E731
        w = lambda cond: every or cond  # noqa: E731
        if self.face != 0:
            if p == 6:
                if t == 1:
                    add("n", "nova", self.f_feedback_new)
                    if w(it and it.data.status in ("pendente", "falhou")):
                        add("p", "publicar", self.f_feedback_push)
                        add("d", "retirar", self.f_feedback_withdraw)
                    if w(it and it.data.status == "criado"):
                        add("r", "retratar", self.f_feedback_retract)
                    add("s", "sincronizar issues", self.f_feedback_sync)
                    add("T", "só pendentes" if self.show_all else "todas", self.toggle_all)
                else:
                    add("c", "limpar o log", self.clear_log)
            else:
                self.ctx_keys_face(K, p, t, it, every)
            return K
        if p == 1:
            if t == 0:
                if w(self.store and self.store.is_empty()):
                    add("i", "primeira entrevista", self.agent_init, agent=True)
                add("n", "nota", self.f_note)
                add("u", "atualizar tudo", self.agent_update, agent=True)
                add("c", "puxar fonte", self.pick_source, agent=True)
                add("d", "processar inbox", lambda: self.agent_dump(), agent=True)
                add("b", "brief", lambda: self.agent_brief(), agent=True)
                add("o", "painel HTML", lambda: self.run_sys("sys:open"))
            elif t == 1:
                add("n", "adicionar", self.f_source_add)
                if w(it and it.kind == "src" and it.data["in_watch"]):
                    add("e", "editar", self.f_source_edit)
                    add("x", "ligar" if it and not it.data.get("enabled", True) else "desligar", self.toggle_source_enabled)
                    add("d", "remover", self.f_source_remove)
                if w(it and it.kind == "src" and not it.data["in_watch"]):
                    add("w", "incluir no watch", self.f_source_include)
                if w(it and it.kind == "src"):
                    add("c", "puxar", self.agent_connect_selected, agent=True)
                add("o", f"ordem: {'↑ antigo' if self.source_sort else '↓ recente'}", self.toggle_source_sort)
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
                add("d", "descartar", self.f_drop)
                add("M", "mesclar", self.f_merge)
            if t == 1 and w(it):
                add("m", "cobrar", self.f_chase)
            if w(it and not it.data["open"]):
                add("o", "reabrir", self.f_reopen)
            if w(it and it.data["open"]):
                add("z", "voltar" if it and it.data["parked"] else "não agora", self.toggle_park)
            add("v", f"vista: {ACTION_VIEWS[self.view].lower()}", self.cycle_view)
            add("O", f"ordem: {ACTION_SORTS[self.sort].lower()}", self.cycle_sort)
            # aba Minhas: fechadas ≤14d sempre visíveis (coluna Feita do painel) — voltar é "só recentes"
            add("T", ("só recentes" if t == 0 else "só abertas") if self.show_all else "todas", self.toggle_all)
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
                    add("a", "responder", self.f_answer)
                    add("d", "descartar", self.f_ask_drop)
                add("R", "retomar o agente", self.resume_with_answers, agent=True)
                add("T", "só abertas" if self.show_all else "todas", self.toggle_all)
            elif t == 1:
                if w(it and it.data.status == "aberta"):
                    add("a", "aceitar", self.f_accept, gate=True)
                    add("d", "rejeitar", self.f_reject)
                add("T", "só abertas" if self.show_all else "todas", self.toggle_all)
            elif t == 2:
                add("n", "rascunhar", lambda: self.f_draft())
                if w(it and it.data["status"] == "rascunho"):
                    add("A", "aprovar", self.f_approve_msg, gate=True)
                if w(it and it.data["status"] == "aprovada"):
                    add("S", "enviar", self.agent_send, agent=True)
                if w(it and it.data["status"] in ("rascunho", "aprovada")):
                    add("d", "cancelar", self.f_cancel_msg)
                add("T", "só pendentes" if self.show_all else "todas", self.toggle_all)
            elif t == 3:
                add("p", "planejar", self.f_focus_plan)
                f = self.store.m["focus"] if self.store else None
                if w(f and f["status"] == "proposto"):
                    add("A", "aprovar", self.f_focus_approve, gate=True)
                if w(f and f["status"] == "aprovado"):
                    add("a", "aplicar", self.f_focus_apply, gate=True)
                add("s", "sync", self.focus_sync)
            elif t == 4:
                add("n", "pedir", self.f_pub_request)
                if w(it and it.data["status"] == "solicitada"):
                    add("A", "aprovar", self.f_pub_approve, gate=True)
                if w(it and it.data["status"] == "aprovada"):
                    add("p", "publicar", self.agent_publish, agent=True)
                if w(it and it.data["status"] in ("solicitada", "aprovada")):
                    add("d", "cancelar", self.pub_cancel)
        elif p == 6:
            if t == 1:
                add("n", "nova", self.f_feedback_new)
                if w(it and it.data.status in ("pendente", "falhou")):
                    add("p", "publicar", self.f_feedback_push)
                    add("d", "retirar", self.f_feedback_withdraw)
                if w(it and it.data.status == "criado"):
                    add("r", "retratar", self.f_feedback_retract)
                add("s", "sincronizar issues", self.f_feedback_sync)
                add("T", "só pendentes" if self.show_all else "todas", self.toggle_all)
            else:
                add("c", "limpar o log", self.clear_log)
        elif p == 5:
            if t == 0:
                add("n", "nova", self.f_decision)
                if w(it):
                    add("S", "superar", self.f_supersede)
            elif t == 1:
                add("n", "nova", self.f_delivery)
            else:
                if w(it):
                    add("o", "abrir RAW", self.open_raw)
        return K

    # ── execução ───────────────────────────────────────────────────────────
    def exec(self, cmds: list[list[str]], render: bool = True, after: Callable[[], None] | None = None,
             show: str | None = None, on_fail: Callable[[], None] | None = None) -> None:
        """Roda comandos `brain` em sequência (para no primeiro erro). `show` abre a saída inteira num modal;
        `on_fail` roda se algum comando falhar (ex.: desfazer a edição do goals.md que o gate não registrou)."""
        self.run_worker(self._exec(cmds, render, after, show, self.face, on_fail), exclusive=False)

    async def _exec(self, cmds: list[list[str]], render: bool, after, show: str | None = None, face: int = 0,
                    on_fail: Callable[[], None] | None = None) -> None:
        async with self._lock:
            ok = True
            outs: list[str] = []
            self.busy = "executando…"
            self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
            try:
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
                if not ok and on_fail:
                    on_fail()
                if ok and render:
                    await self._render_after()
                await self._reload()
            finally:
                # o worker pode morrer no meio (binário do brain sumiu, callback quebrou): sem isto o busy
                # fica preso para sempre — o _watch para de reler o vault e o q pede confirmação dobrada
                self.busy = ""
                self._quit_armed = False
                self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
                self.redraw()
            if show and ok and any(outs):
                self.push_screen(TextModal(show, Text("\n\n".join(o for o in outs if o))))
            if ok and after:
                shown, self.face = self.face, face       # o `after` mexe na navegação da face onde o comando nasceu
                try:
                    after()
                finally:
                    if self.face == face:
                        self.face = shown
                self.redraw()

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

    async def _render_after(self) -> None:
        r = await asyncio.to_thread(bridge.run_brain, self.inst, ["render"])
        if r.ok:
            self.log_line("↻ brain render · " + (r.out.splitlines()[0] if r.out else "views regeneradas"), "dim")
            return
        lines = (r.err or r.out or "").strip().splitlines()
        self.log_line(f"⚠ brain render falhou (código {r.rc}) — FRESH e o painel HTML ficaram velhos: "
                      f"{lines[-1][:160] if lines else 'sem saída'}", "yellow")

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
            self.exec(spec.build(vals), render=spec.render, after=spec.after, show=spec.show, on_fail=spec.on_fail)
        self.push_screen(FormModal(spec), done)

    # ── formulários: a especificação mora em brainlib/forms.py (a MESMA do painel) ──────────────────────────
    def form_model(self) -> dict:
        """O view model com o que os formulários leem — as mesmas chaves que o painel recebe como M."""
        from .. import forms, schema, watch
        st = self.store
        # "today" de agora: a TUI aberta na virada do dia não resolve "amanhã" um dia cedo
        return {**st.m, "today": util.today().isoformat(), "sources": st.sources, "source_kinds": [list(k) for k in watch.KINDS],
                "doc_kinds": sorted(schema.DOC_KINDS), "form_static": forms.static(st.brain)}

    def _py_rules(self, ctx: dict) -> tuple[dict, dict]:
        """Validações e dicas que só o Python tem (forms.PY_ONLY): precisam do ledger inteiro ou da config."""
        def dup_res(x, v, c, m) -> str:
            if len(x.strip()) < 8:
                return ""
            hits = dupes.similar(self.store.brain.state, {**dupes.profile_from_data({"title": x}), "people": []})
            return f"parecida com {hits[0]['id']} · {hits[0]['title']} ({hits[0]['score']:.2f})" if hits else ""

        def promote_diff(x, v, c, m) -> str:
            from ..cli_portfolio import promote_proposal
            opp = self.store.brain.state.opportunities.get(c.get("id", ""))
            level = v.get("level") or "project"
            target = v.get("goal") if level == "project" else v.get("project") if level == "deliverable" else None
            if opp is None or (level != "goal" and not target):
                return ""
            try:
                _, lines = promote_proposal(self.store.brain, opp, v.get("title") or None, level, target)
                return "cria:\n" + "\n".join("+ " + ln for ln in lines)
            except Exception:  # noqa: BLE001 — a dica nunca derruba o formulário
                return ""

        def provider_model(x, v, c, m) -> str:
            from .. import providers as prov
            info = prov.PROVIDERS[v.get("slot") or "embeddings"].get(v.get("provider", ""), {})
            if info.get("models"):
                return "recomendados por operação (cenário B): " + " · ".join(f"{op}={md}" for op, md in info["models"].items())
            return info.get("model", "— modelo default do provedor —")

        checks = {"people": lambda x, v, c, m: self._people_check(x), "recipient": lambda x, v, c, m: self._check_recipient(x)}
        return checks, {"dup_action": dup_res, "promote_diff": promote_diff, "provider_model": provider_model}

    def open_form(self, form_id: str, ctx: dict | None = None, *, values: dict | None = None, after=None, on_cancel=None,
                  on_fail=None, intercept=None, extra=None, render: bool = True, show: str | None = None, help=None,
                  help_title: str = "Orientações", wrap=None) -> None:
        """Abre o formulário `form_id` de brainlib/forms.py: campos, rótulos, validação e a linha `brain …` saem de lá.
        `values` sobrepõe o valor inicial (rascunho que volta); `wrap(cmds, vals)` acrescenta passos só da TUI."""
        from .. import forms
        fm, ctx = forms.FORMS[form_id], ctx or {}
        m = self.form_model()
        init = {**forms.initial(fm, ctx, m), **{k: v for k, v in (values or {}).items() if v is not None}}
        checks, hints = self._py_rules(ctx)

        def build(v: dict) -> list[list[str]]:
            cmds = forms.build(form_id, v, ctx, m, surface="tui")
            return wrap(cmds, v) if wrap else cmds

        if not fm.fields:                                # só confirmação (ex.: remover fonte, desligar documento)
            cmds = build({})

            def done(ok) -> None:
                if ok:
                    self.exec(cmds, render=render, after=after, show=show)
            self.push_screen(ConfirmModal(forms.title(form_id, ctx), forms.sub(form_id, ctx), cmds[0]), done)
            return
        fields = [Field(f.id, forms.label(f, m, ctx), value=init[f.id], ph=forms._fmt(f.ph, ctx), req=forms.required(f, ctx),
                        multi=f.multi,
                        secret=f.secret, depends=f.depends,
                        options=(lambda v, f=f: forms.options(f, m, v, ctx)) if f.choices is not None else None,
                        suggest=[o[0] for o in forms.options(f, m, init, ctx)] if f.suggest else None,
                        check=(lambda x, v, f=f: forms.check(f.check, x, v, ctx, m, checks)) if f.check else None,
                        res=(lambda x, v, f=f: forms.hint(f.hint, x, v, ctx, m, hints)) if f.hint else None,
                        show=(lambda v, f=f: forms._cond(f.show, v, ctx, m)) if f.show is not None else None,
                        fill=(f.fill[0], forms.FILL[f.fill[1]]) if f.fill else None)
                  for f in fm.fields if f.auto != "surface"]
        self.form(FormSpec(forms.title(form_id, ctx), fields, build, sub=forms.sub(form_id, ctx), gate=fm.gate, extra=extra,
                           on_cancel=on_cancel, on_fail=on_fail, after=after, render=render, show=show, intercept=intercept,
                           help=help, help_title=help_title))

    def toggle_zoom(self) -> None:
        self.zoom = not self.zoom
        self.redraw()

    def toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.redraw()

    def cycle_view(self) -> None:
        """v: Todas → Esta semana (e o que está atrasado) → Depois → Não agora."""
        self.view = (self.view + 1) % len(ACTION_VIEWS)
        self.redraw()

    def cycle_sort(self) -> None:
        """O: ordena as ações por prazo (padrão; empate pelo ID) ou só pelo ID, sempre crescente."""
        self.sort = (self.sort + 1) % len(ACTION_SORTS)
        self.redraw()

    def toggle_park(self) -> None:
        a = self.cur().data
        self.exec([["action", "update", a["id"], "--unpark" if a["parked"] else "--park", "--by", "owner"]])

    def toggle_collapse(self) -> None:
        it = self.cur()
        if it:
            self.collapsed ^= {it.id}
            self.redraw()

    # ── ações: formulários ─────────────────────────────────────────────────
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

    def f_new_goal(self) -> None:
        nid = planning.next_goal_id(self.store.brain.plan)
        self.open_form("goal.new", {"nid": nid}, after=lambda: self.jump(nid))

    def f_new_project(self, goal: dict) -> None:
        nid = planning.next_project_id(self.store.brain.plan)
        self.open_form("project.new", {"nid": nid, "goal": goal["id"], "goal_title": goal["title"]}, after=lambda: self.jump(nid))

    def f_new_deliverable(self, proj: dict) -> None:
        nid = planning.next_deliverable_id(self.store.brain.plan, proj["id"])
        self.open_form("deliverable.new", {"nid": nid, "project": proj["id"], "project_title": proj["title"]},
                       after=lambda: self.jump(nid))

    def f_edit_node(self) -> None:
        """Painel 3, `e`: edita o item selecionado. Goal e projeto são gate (confirmar aprova); entregável não."""
        it = self.cur()
        if it is None:
            return
        ctx = {"id": it.id, "item": it.data}
        if it.kind == "g":
            self.open_form("goal.edit", ctx)
        elif it.kind == "p":
            self.open_form("project.edit", ctx)
        else:
            self.open_form("deliverable.edit", ctx)

    def f_new_action(self, pre: dict | None = None) -> None:
        pre = pre or {}
        lst = ["mine", "waiting", "watching"][self.tab[2]] if self.p == 2 else "mine"

        def after_suggest() -> None:
            """Sem prazo digitado: oferece o agente para sugerir um (aparece em roxo até você decidir)."""
            title = self._suggest_for
            hit = [] if not title else sorted((x["id"] for x in self.store.m["actions"] if x["title"] == title and x["open"] and not x["due"]))
            if hit:
                self.ask_agent(f"Sugerir prazo para {hit[-1]}", [
                    "Lê o contexto: PLANNING (prazos de projeto/entregável), acordos com pessoas, agenda e carga atual",
                    "Grava o prazo como sugestão (brain action update … --due-suggested): fica roxo até você definir a data",
                    "Sem base para sugerir, diz 'não consta' e deixa a ação sem prazo"], f"/todo prazo {hit[-1]}")

        def remember(cmds, v):
            # o aviso de parecida já apareceu no campo título: gravar é a decisão do dono de que é outra ação (--force)
            self._suggest_for = v["title"] if not v["due"] and v["list"] != "watching" else None
            return cmds

        deliv, proj = pre.get("deliv", ""), pre.get("project", "—")
        self.open_form("action.new", {"list": lst, "owner": "eu" if lst == "mine" else "", "deliv": deliv, "project": proj,
                                      "item": {"project": proj}, "in_deliv": f" em {deliv}" if deliv else ""},
                       wrap=remember, after=after_suggest)

    def clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def f_note(self, pre: dict | None = None) -> None:
        """Nota avulsa: vira um .md na inbox (a porta única); o /dump arquiva no RAW. Vínculo opcional.
        Se já existe nota de hoje para o mesmo vínculo (ainda na inbox), pergunta: editar a existente ou criar outra."""
        from .. import forms
        it = self.cur()
        link0 = it.id if it and it.kind in ("action", "g", "p", "d") else ""
        pre = pre or {}
        today = util.today().isoformat()

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
                    self.exec(forms.build("note.add", v, ctx, self.form_model()), render=False)
                else:
                    self.f_note(pre=v)
            self.push_screen(ChoiceModal("Editar a nota de hoje ou criar outra?", body, [
                ("e", "edit", "Editar a existente (o que você digitou entra no fim do texto dela)"),
                ("n", "new", f"Nova nota ({notes_mod.filename(self.inst, link, today)})")]), chose)
            return True

        ctx = {"text": pre.get("text", ""), "link": pre.get("link", link0)}
        self.open_form("note.add", ctx, render=False, intercept=intercept)

    def f_note_edit(self, note: notes_mod.Note, extra: str = "") -> None:
        self.open_form("note.edit", {"name": Path(note.path).name, "path": note.path, "created": note.created,
                                     "text": note.text + (f"\n\n{extra}" if extra else "")}, render=False)

    def f_close_action(self) -> None:
        a = self.cur().data
        self.open_form("action.close", {"id": a["id"], "title": a["title"], "item": a})

    def f_edit_action(self) -> None:
        a = self.cur().data
        self.open_form("action.edit", {"id": a["id"], "title": a["title"], "item": a})

    def f_due(self) -> None:
        a = self.cur().data
        sub = ("Prazo sugerido pelo agente (roxo): salve com a mesma data para confirmar, ou digite outra."
               if a.get("due_suggested") else "Deixe em branco para remover o prazo.")
        self.open_form("action.due", {"id": a["id"], "title": a["title"], "item": a, "due_sub": sub})

    def cycle_status(self) -> None:
        a = self.cur().data
        blk = a.get("blocked_by") or []
        if blk:
            self.log_line(f"{a['id']} segue bloqueada por {', '.join(blk)} — resolva o bloqueio para movê-la", "yellow")
            return
        nxt = {"aberta": "fazendo", "fazendo": "aguardando", "aguardando": "aberta"}.get(a["status"], "fazendo")
        self.exec([["action", "update", a["id"], "--status", nxt, "--by", "owner"]])

    def f_drop(self) -> None:
        a = self.cur().data
        self.open_form("action.drop", {"id": a["id"], "title": a["title"], "item": a})

    def f_merge(self) -> None:
        """Mescla a ação selecionada (duplicada, que sai) em outra que fica — o mesmo `action merge` do painel."""
        a = self.cur().data
        self.open_form("action.merge", {"id": a["id"], "title": a["title"], "item": a})

    def f_reopen(self) -> None:
        a = self.cur().data
        self.open_form("action.reopen", {"id": a["id"], "title": a["title"], "item": a})

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
        self.open_form("deliverable.done", {"id": d["id"], "title": d["title"], "item": d})

    def f_deliv_state(self) -> None:
        d = self.cur().data
        self.open_form("deliverable.state", {"id": d["id"], "title": d["title"], "item": d})

    def f_progress(self) -> None:
        self.open_form("progress.declare", {"id": self.cur().id})

    def f_share(self) -> None:
        it = self.cur()
        kind = {"g": "goal", "p": "project"}.get(it.kind if it else "", "status")
        self.open_form("share.export", {"kind": kind, "target": it.id if it and it.kind in ("g", "p") else ""}, render=False)

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
        """Gate estrutural: edita goals.md, mostra o diff e só mantém ao confirmar."""
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
            # escrita direta deliberada: é o rollback da edição que o próprio dono fez no editor (não dado de
            # entidade novo) — relê o arquivo e recusa se ele andou de novo, para não pisar terceiros
            now = path.read_text(encoding="utf-8") if path.exists() else ""
            if now != after:                      # outro processo mexeu depois do editor: não sobrescreve às cegas
                self.log_line("goals.md mudou de novo fora do TUI: não desfiz a edição; confira e registre com E (gate)", "red")
                return
            util.atomic_write(path, before)
            self.log_line("mudança do PLANNING descartada: goals.md voltou ao que era", "yellow")

        self.open_form("plan.log", {"diff": pre.get("diff", ""), "reason": pre.get("reason", ""), "ev": pre.get("ev", "")},
                       extra=extra, on_cancel=restore, on_fail=restore)

    def f_accept(self) -> None:
        r = self.cur().data

        def after() -> None:
            if r.kind == "mudar-plano":
                self.log_line("Proposta aceita. Para executar a mudança do plano, use E (gate) no painel 3.", "yellow")
            elif r.kind == "framework":
                self.log_line("Proposta aceita. A issue vai pro GitHub do framework (porta 7) — veja o resultado no log › Feedback.", "yellow")
            elif r.kind in ("atualizar-acao", "outro"):
                self.log_line("Proposta aceita. Aplique a mudança na ação com e (editar), se for o caso.", "yellow")

        self.open_form("proposal.accept", {"id": r.id, "summary": r.summary, "kind": r.kind, "target": r.target or "",
                                           "into": r.into or ""}, after=after)

    def f_reject(self) -> None:
        r = self.cur().data
        self.open_form("proposal.reject", {"id": r.id, "summary": r.summary})

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
        def after() -> None:
            self.p, self.tab[4] = 4, 2
            self.set_sel(4, 0)
            self.redraw()

        self.open_form("outbox.draft", {"to": to, "text": text, "ref": ref, "why": why}, after=after)

    def f_approve_msg(self) -> None:
        m = self.cur().data
        n = m["id"].split("-")[1].lstrip("0") or "0"
        self.open_form("outbox.approve", {"id": m["id"], "to_name": m["to_name"], "n": n, "text": m["text"]},
                       extra=Text.assemble(("▌ ", "cyan"), m["text"]))

    def f_cancel_msg(self) -> None:
        m = self.cur().data
        self.open_form("outbox.cancel", {"id": m["id"], "text": m["text"]})

    def f_focus_plan(self) -> None:
        self.open_form("focus.plan", {"days": str(self.inst.cfg["focus"]["horizon_days"])},
                       after=lambda: (self.tab.__setitem__(4, 3), self.redraw()))

    def f_focus_approve(self) -> None:
        self.open_form("focus.approve", {"id": self.store.m["focus"]["id"]})

    def f_focus_apply(self) -> None:
        self.open_form("focus.apply", {"id": self.store.m["focus"]["id"], "mode": self.inst.cfg["focus"]["mode"]})

    def focus_sync(self) -> None:
        self.open_form("focus.sync", render=False)

    def f_pub_request(self) -> None:
        if not self.store.destinations():
            self.log_line("Nenhum destino em [publish].destinations (config/brain.toml). A porta está fechada.", "red")
            return
        reports = self.store.reports()
        self.open_form("publish.request", {"report": reports[0] if reports else ""}, render=False)

    def f_pub_approve(self) -> None:
        s = self.cur().data
        self.open_form("publish.approve", {"id": s["id"], "report": s["report"], "destination": s["destination"]})

    def pub_cancel(self) -> None:
        self.exec([["publish", "cancel", self.cur().data["id"]]])

    def f_decision(self) -> None:
        self.open_form("decision.new")

    def f_supersede(self) -> None:
        d = self.cur().data
        self.open_form("decision.supersede", {"id": d["id"], "title": d["title"]})

    def f_delivery(self) -> None:
        self.open_form("delivery.new")

    def f_person(self) -> None:
        made: dict[str, str] = {}

        def remember(cmds, v):
            made["id"] = v["id"] or util.slugify(v["name"] or "")
            return cmds

        self.open_form("person.new", wrap=remember, after=lambda: made.get("id") and self.jump(made["id"]))

    def f_person_update(self) -> None:
        p = self.cur().data
        self.open_form("person.edit", {"id": p["id"], "item": p})

    def f_resolve(self) -> None:
        self.open_form("person.resolve", render=False)

    def f_memory(self) -> None:
        self.open_form("memory.ask", render=False, show="Memória")

    def f_alias(self) -> None:
        p = self.cur().data
        self.open_form("person.alias", {"id": p["id"]})

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
    def _locate_tab(self, pid: int, label: str) -> tuple[int, int] | None:
        """(face, aba) onde o painel `pid` mostra a aba `label` — a face atual primeiro."""
        order = [(self.face, self.panels)] + [(i, p) for i, (_, p) in enumerate(FACES) if i != self.face]
        for face, panels in order:
            tabs = panels.get(pid, ("", []))[1]
            if label in tabs:
                return (face, tabs.index(label))
        return None

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
            loc = self._locate_tab(1, SYS_TAB)
            if loc is None:
                self.log_line("operação de sistema não encontrada nesta face", "yellow")
                return
            face, tab = loc
            if face != self.face:
                self.face_to(face)
                self.face = face
            self.p = 1
            self.tab[1] = tab
            self.set_sel(1, [o["id"] for o in SYS_OPS].index(fix["sys"]))
            self.redraw()
        elif fix.get("go"):
            gp, gt = fix["go"]
            if gp in self.panels:
                gt = min(gt, len(self.panels[gp][1]) - 1)
            self.p, self.tab[gp] = gp, gt
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
        if op.get("external"):
            import sys as _sys
            from .bridge import FRAMEWORK
            self.log_line(f"$ brain {' '.join(op['args'])}  (terminal interativo)", "cyan")
            self.external([_sys.executable, str(FRAMEWORK / "brain"), *op["args"]])
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
        run_id = bridge.new_run_id()
        argv = bridge.agent_argv(self.inst.cfg, prompt, run_id)

        def done(choice) -> None:
            if choice == "run":
                self.run_worker(self._agent(argv, prompt, run_id), exclusive=False)
            elif choice == "copy":
                self.copy_to_clipboard(prompt)
                self.log_line("prompt copiado: cole no chat do agente", "magenta")
        self.push_screen(AgentModal(title, bullets, prompt, argv), done)

    async def _agent(self, argv: list[str], prompt: str, run_id: str = "", resumed_from: str = "") -> None:
        async with self._lock:
            self.busy = "agente…"
            self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
            try:
                self.log_line("⚡ " + prompt.splitlines()[0][:100], "magenta")
                info = bridge.RunInfo(id=run_id, resumed_from=resumed_from)
                rc = await bridge.run_agent(self.inst, argv, lambda ln: self.log_line("  " + ln, "magenta") if ln else None, info)
                if info.denials:
                    await self.after_run(info)                # cada negação vira uma pergunta (kind=permissao)
                await asyncio.to_thread(bridge.record_run, self.inst, info, argv, prompt)
                if info.session_id:
                    self.last_run = info
                self.log_line("✓ agente terminou" if rc == 0 else f"✗ agente saiu com código {rc}", "green" if rc == 0 else "red")
                await self._render_after()
                await self._reload()
                self.report_run(info)
                if resumed_from and rc != 0:
                    self.log_line("o resume falhou (sessão expirada ou outro agente): as respostas ficam na fila, o próximo /update ou ⚡ as aplica (passo 0)", "yellow")
            finally:
                # idem _exec: exceção no meio (spawn do agente, record_run) não pode prender o busy
                self.busy = ""
                self._quit_armed = False
                self.query_one("#detailwrap").border_subtitle = self._detail_subtitle()
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
        self.open_form("agent.arg", {"name": op["name"], "desc": op["desc"], "arg_label": label, "arg_ph": ph, "arg_req": req},
                       render=False, intercept=lambda v: self.ask_agent(op["name"], bullets, f"{cmd} {v['arg']}".strip()) or True)

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
        in_watch = [x for x in self.store.sources if x["in_watch"]]
        if not in_watch:
            self.log_line("Nenhuma fonte no config/watch.toml: o /update não teria o que puxar. Painel 1, aba Fontes, tecla n.", "yellow")
            return
        keys = [x["key"] for x in in_watch if x.get("enabled", True)]
        if not keys:
            self.log_line("Todas as fontes do config/watch.toml estão desligadas (tecla x liga).", "yellow")
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
    def _source_after(self, getkey) -> None:
        self.p, self.tab[1] = 1, 1                     # Fontes (aba 1 desde a face Configurações)
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

        def remember(cmds, v):
            made["key"] = v["key"]
            return cmds

        self.open_form("watch.add", {"item": pre or {}}, wrap=remember, render=False,
                       after=lambda: self._source_after(lambda: made.get("key")))

    def f_source_include(self) -> None:
        it = self.cur()
        if it and it.kind == "src":
            self.f_source_add({"key": it.data["key"]})

    def toggle_source_sort(self) -> None:
        self.source_sort = 1 - self.source_sort
        self.redraw()

    def toggle_source_enabled(self) -> None:
        it = self.cur()
        if not it or it.kind != "src" or not it.data.get("in_watch"):
            return
        key = it.data["key"]
        nxt = "false" if it.data.get("enabled", True) else "true"
        self.exec([["watch", "edit", key, "--set", f"enabled={nxt}"]], render=False,
                  after=lambda: self._source_after(lambda: key))

    def f_source_edit(self) -> None:
        it = self.cur()
        if not it or it.kind != "src":
            return
        old = it.data
        made: dict[str, str] = {}

        def remember(cmds, v):
            made["key"] = v["key"]
            return cmds

        self.open_form("watch.edit", {"key0": old["key"], "item": old}, wrap=remember, render=False,
                       after=lambda: self._source_after(lambda: made.get("key")))

    def f_source_remove(self) -> None:
        it = self.cur()
        if not it or it.kind != "src":
            return
        self.open_form("watch.remove", {"key": it.data["key"]}, render=False,
                       after=lambda: self._source_after(lambda: None))

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
                    if go[3]:
                        t.append("   " + ("space" if go[3] == "space" else go[3]), "yellow")
                    out.append(PickItem(t, go))
            return out

        def done(item) -> None:
            if item:
                self.run_catalog(item.data)
        self.push_screen(PickerModal("Comandos", "digite para buscar: fechar, foco, backup…", source), done)

    def run_catalog(self, go: tuple) -> None:
        face, p, t, k = go[0], go[1], go[2], go[3]
        if p is None:
            if k == "g":
                self.search()
            elif k == "N":
                self.f_note()
            elif k == "r":
                self.free_reply()
            elif k == "icehelp":
                from . import rows
                self.push_screen(TextModal("Metodologia · ICE", rows.ice_methodology(min(100, self.size.width - 6))))
            return
        self.face = face
        self.p, self.tab[p] = p, t
        self.filt = None
        if len(go) > 4:
            self.set_sel(p, [o["id"] for o in SYS_OPS].index(go[4]))
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
        if self.p == 6 or self._summary_on():
            return
        key = (self.p, self.tab[self.p])
        base = self.filt_levels(key)               # "/" de novo não reabre o filtro: abre um NOVO, sobre o que sobrou

        def change(text: str) -> None:
            self.set_filt_levels(key, base + ([text] if text else []))
            self.redraw()
        self.push_screen(FilterModal("", change, base=base))

    def help(self) -> None:
        name, tabs = self.panels.get(self.p, (f"painel {self.p} (fora desta face)", ["—"]))
        tab_label = tabs[min(self.tab[self.p], len(tabs) - 1)]
        body = Text()
        body.append("Neste contexto\n", "dim")
        for k in self.ctx_keys():
            body.append(f"  {('space' if k.k == ' ' else k.k):<7}", "bold cyan")
            body.append(("⚡ " if k.agent else "◆ " if k.gate else "") + k.label + "\n")
        body.append("\nNavegação\n", "dim")
        for k, d in (("j k ↑ ↓", "mover na lista"), ("tab / shift+tab", "próxima / anterior face (Execução · Portfólio · Configurações)"), ("1-6", "ir ao painel (6 = log)"), ("[ ] ← →", "aba anterior / próxima (h l também)"),
                     ("enter", "ampliar o detalhe"), ("esc", "voltar")):
            body.append(f"  {k:<9}", "bold cyan")
            body.append(d + "\n")
        body.append("\nEm qualquer tela\n", "dim")
        for k, d in (("?", "esta ajuda — dentro do formulário do ICE, a metodologia de pontuação"), (":", "paleta de comandos"), ("/", "filtrar a lista — de novo, refina o que sobrou; esc tira um filtro por vez"), ("g", "buscar em tudo"), ("N", "nova nota na inbox"), ("`", "abre / fecha o log"), ("r", "regenerar views"),
                     ("ctrl+t", "tema claro / escuro"), ("q", "sair")):
            body.append(f"  {k:<9}", "bold cyan")
            body.append(d + "\n")
        body.append("\n⚡ roda o agente  ·  ◆ gate — confirmar aprova\n", "dim")
        face = f"{FACES[self.face][0]} · " if self.face else ""
        self.push_screen(TextModal(f"Atalhos · {face}{name} › {tab_label}", body))


def run(inst) -> None:
    BrainApp(inst).run()
