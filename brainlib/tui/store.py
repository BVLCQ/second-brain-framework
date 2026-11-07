"""Leitura somente-leitura do cérebro para o TUI: view model, saúde e listas por painel.

Nada aqui escreve. O TUI recarrega depois de cada comando que ele mesmo dispara.
"""
from __future__ import annotations

import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .. import config, doctor, ids, model, notes as notes_mod, opener, rawsort, util, watch
from ..core import Brain

# Abas do painel Plano (Execução): 0 = árvore inteira; 1-4 = só goals/projetos naquele status.
# Goal na aba aparece com todos os seus projetos; projeto no status aparece dentro do goal (contexto),
# mesmo quando o goal tem outro status.
PLAN_VIEWS = ["Todos", "Ativo", "Congelado", "Depois", "Finalizado"]
PLAN_TAB_STATUS = [None, "ativo", "congelado", "depois", "finalizado"]

PANELS_EXEC = {
    1: ("Status", ["Resumo", "Fontes", "Sistema"]),
    2: ("Ações", ["mine", "waiting", "watching"]),
    3: ("Plano", PLAN_VIEWS),
    4: ("Aprovar", ["Perguntas", "Propostas", "Outbox", "Foco", "Publicar"]),
    5: ("Registro", ["Decisões", "Entregas", "Pessoas", "Artefatos"]),
    6: ("Log de comandos", ["Log", "Feedback"]),
}

# Vistas do painel Ações (tecla v): Todas · Esta semana (+ atrasadas) · Depois · Não agora (adiadas de propósito).
ACTION_VIEWS = ["Todas", "Esta semana", "Depois", "Não agora"]
ACTION_SORTS = ["Prazo", "ID"]


def action_view(a: dict, today) -> int:
    """Em qual vista uma ação aberta cai: 1 esta semana · 2 depois · 3 não agora. Fechadas só aparecem em "Todas" (0).

    Esta semana = até o domingo corrente, incluindo o que já está atrasado; sem prazo só entra se já está em andamento.
    Depois = semana que vem em diante e o que não tem data."""
    if not a["open"]:
        return 0
    if a.get("parked"):
        return 3
    if a["due"]:
        return 1 if date.fromisoformat(a["due"]) <= today + timedelta(days=6 - today.weekday()) else 2
    return 1 if a["status"] == "fazendo" else 2


PANELS_PORT = {
    1: ("Visão", ["Resumo", "Por área", "Por goal"]),
    2: ("Processos", ["Todos", "Por área", "Lacunas"]),
    3: ("Oportunidades", ["Triagem", "Priorizadas", "Em curso", "Arquivo"]),
    4: ("Matriz", ["Matriz", "Ranking"]),
    5: ("Registro", ["Áreas", "Documentos"]),
    6: ("Log de comandos", ["Log", "Feedback"]),
}

# Configurações (face 2): o que o dono re-edita quando quer — provedores da memória, harnesses, saúde.
# A configuração é seção viva, não "setup uma vez": as mesmas escolhas do wizard, sem refazer a instalação.
PANELS_CFG = {
    1: ("Memória", ["Provedores", "Harnesses"]),
    2: ("Instância", ["Saúde"]),
    6: ("Log de comandos", ["Log", "Feedback"]),
}

# Face = conjunto de painéis 1–5 com abas próprias; o painel 6 (Log) é comum. Tab/Shift+Tab giram entre as faces
# (carrossel). Uma face nova entra só declarando-se aqui (e em FACE_START: o painel em que ela abre).
FACES = [("Execução", PANELS_EXEC), ("Portfólio", PANELS_PORT), ("Configurações", PANELS_CFG)]
FACE_START = [2, 3, 1]
OPP_TABS = [("ideia", "triagem"), ("priorizada",), ("em-andamento", "piloto", "validando"),
            ("entregue", "em-espera", "descartada")]      # status de cada aba de Oportunidades (a última recebe o resto)
PANELS = PANELS_EXEC                 # compatibilidade: os painéis da face Execução

SYS_OPS = [
    {"id": "sys:render", "name": "Regenerar views", "args": ["render"],
     "desc": "Colhe checkboxes e status editados à mão e reescreve todo o FRESH (Markdown e painel HTML). "
             "Roda sozinho depois de cada escrita feita aqui."},
    {"id": "sys:open", "name": "Abrir o painel HTML", "args": ["render", "--open"],
     "desc": "Regenera as views e abre o painel (um arquivo, offline) no navegador."},
    {"id": "sys:openpf", "name": "Abrir o mapa de oportunidades (HTML)", "args": ["render", "--open", "portfolio"],
     "desc": "Regenera as views e abre o mapa do portfólio — oportunidades, processos, áreas, pessoas e arquivos — "
             "num arquivo só, offline e navegável, feito para compartilhar (FRESH/dashboard/portfolio.html)."},
    {"id": "sys:sync", "name": "Colher edições do dono", "args": ["sync"],
     "desc": "Só colhe o que você editou à mão (checkbox em todo.md, status: na ficha da ação, goals.md), sem redesenhar as views."},
    {"id": "sys:validate", "name": "Validar o ledger", "args": ["validate"],
     "desc": "Relê o livro-razão inteiro, o PLANNING e os aliases. Sai com código 4 se achar inconsistência."},
    {"id": "sys:doctor", "name": "Saúde online", "args": ["doctor", "--online"], "show": "Saúde da instância",
     "desc": "O mesmo que a aba Saúde, mais o teste do servidor de memória (Hindsight), se estiver ligado."},
    {"id": "sys:update", "name": "Atualizar o framework", "args": ["update", "--check"], "apply": ["update"],
     "desc": "git pull seguro, sem tocar no vault nem na config. Mostra primeiro o que chegou (--check); U aplica."},
    {"id": "sys:upstream", "name": "Varredura upstream", "args": ["upstream", "scan"], "show": "Varredura upstream",
     "desc": "Procura dado pessoal em melhorias locais antes de elas subirem ao repositório público."},
    {"id": "sys:hook", "name": "Hook pre-push: status", "args": ["upstream", "hook", "status"],
     "desc": "Mostra se o hook que roda a varredura antes do push está instalado."},
    {"id": "sys:memory", "name": "Memória: sincronizar", "args": ["memory", "sync"],
     "desc": "Envia ao Hindsight só o que mudou. O vault continua sendo a verdade. Exige [memory] engine = hindsight."},
    {"id": "sys:memstatus", "name": "Memória: status", "args": ["memory", "status"],
     "desc": "Estado dos bancos brain-mem e brain-raw e o que está pendente."},
    {"id": "sys:recall", "name": "Memória: perguntar", "form": "memory", "show": "Memória",
     "desc": "recall devolve os trechos; reflect pede uma resposta sintetizada. O trecho ainda precisa apontar para um "
             "documento do vault (/ask confirma no arquivo)."},
    {"id": "sys:memsetup", "name": "Memória: criar bancos", "args": ["memory", "setup"], "confirm": True,
     "desc": "Cria ou atualiza os bancos brain-mem e brain-raw no servidor."},
    {"id": "sys:provshow", "name": "Memória: provedores", "args": ["memory", "providers", "show"],
     "show": "Provedores",
     "desc": "O stack atual: LLM, embeddings e reranker — quem é local, quem é nuvem (egress), chave presente."},
    {"id": "sys:wizmem", "name": "Wizard da memória (terminal interativo)", "args": ["setup", "--only", "memoria"],
     "external": True,
     "desc": "Re-roda o passo Memória do setup: modo, provedores, chaves. Configuração é seção viva, não uma vez só."},
    {"id": "sys:hwverify", "name": "Harnesses: verificar", "args": ["memory", "harness", "verify"],
     "show": "Harnesses",
     "desc": "Conexão dos agentes de código com o Hindsight: banco existe, recall responde, configs apontando pra cá."},
    {"id": "sys:memrebuild", "name": "Memória: reconstruir tudo", "args": ["memory", "rebuild"], "confirm": True,
     "desc": "APAGA os dois bancos e reenvia tudo a partir do vault. Demora; o vault não é tocado."},
    {"id": "sys:backup", "name": "Backup do vault", "args": ["backup"], "door": "backup · Drive",
     "desc": "Zip do vault para a pasta de backup configurada (escopo drive.file). Retenção de 8 cópias."},
    {"id": "sys:backupst", "name": "Backup: ver últimos", "args": ["backup", "--status"],
     "desc": "Mostra o último backup e o total na pasta do Drive."},
    {"id": "sys:nightly", "name": "Rotina noturna agora", "args": ["nightly", "--skip-agent"], "confirm": True,
     "desc": "render, foco sync, memória, backup (se for o dia) e render final, sem o agente."},
    {"id": "sys:schedule", "name": "Agendar o noturno", "args": ["schedule", "install", "--time", "05:00"],
     "confirm": True, "desc": "Instala a entrada no crontab (05:00)."},
    {"id": "sys:schedst", "name": "Agendamento: ver", "args": ["schedule", "status"],
     "desc": "Mostra a linha do crontab, se houver."},
    {"id": "sys:unsched", "name": "Agendamento: remover", "args": ["schedule", "remove"], "confirm": True,
     "desc": "Remove a entrada do noturno do crontab."},
    # Comandos do agente (⚡ na lista): o mesmo que digitar /<skill> no chat. "do" são os passos mostrados antes de rodar;
    # "arg" abre um campo (req = obrigatório); os cinco primeiros têm fluxo próprio no app (agent_*).
    {"id": "sys:ai-dump", "name": "Processar a inbox (/dump)", "agent": "/dump",
     "desc": "Arquiva o que está em RAW/inbox/, extrai decisões, ações e fatos com proveniência e grava tudo pelo ./brain."},
    {"id": "sys:ai-update", "name": "Atualizar tudo (/update)", "agent": "/update",
     "desc": "Puxa as fontes do watch.toml pelo MCP de leitura, grava os snapshots, processa a inbox e regenera as views."},
    {"id": "sys:ai-connect", "name": "Puxar uma fonte (/connect)", "agent": "/connect",
     "desc": "Escolhe uma fonte, lê o estado atual pelo MCP (só leitura), grava o snapshot e processa a novidade."},
    {"id": "sys:ai-brief", "name": "Brief do dia (/brief)", "agent": "/brief",
     "desc": "Hoje, ações atrasadas, próximos 3 dias e goal em foco. A narrativa vai para FRESH/notes/."},
    {"id": "sys:ai-week", "name": "Cockpit da semana (/week)", "agent": "/week",
     "do": ["Lookahead de 14 dias, radar de goals e ações envelhecendo", "Escreve a narrativa em FRESH/notes/semana.md",
            "Mudança em goals só vira proposta: o gate continua seu"],
     "desc": "Lookahead de 14 dias, radar de goals, ações envelhecendo e foco sugerido."},
    {"id": "sys:ai-gmail", "name": "Ler emails (/gmail)", "agent": "/gmail", "arg": ("filtro ou janela", "da Marina-demo · assunto X · 3d (vazio = hoje)", False),
     "do": ["Lê a caixa pelo MCP, só leitura (nunca compõe nem envia)", "Grava com brain snapshot e processa (/dump)",
            "Fechar ação com base no email vira proposta, não fecho"],
     "desc": "Puxa emails pelo MCP de leitura: snapshot na inbox, /dump e um digest do que é novo e do que cobra você."},
    {"id": "sys:ai-slack", "name": "Ler Slack (/slack)", "agent": "/slack", "arg": ("canal ou pessoa", "#canal @user 7d", True),
     "do": ["Lê o canal ou a conversa pelo MCP, só leitura (janela padrão 7d)", "Grava com brain snapshot e processa (/dump)",
            "Enviar mensagem é a outbox (aba Aprovar), não este comando"],
     "desc": "Puxa mensagens de um canal ou conversa pelo MCP de leitura e processa o que mudou."},
    {"id": "sys:ai-drive", "name": "Ler doc do Drive (/drive)", "agent": "/drive", "arg": ("termo ou id", "nome do doc ou id do arquivo", True),
     "do": ["Busca ou exporta o doc pelo MCP, só leitura (nunca cria nem edita)", "Grava o snapshot datado e processa (/dump)",
            "Primeira vez = estado inicial; depois, o que mudou"],
     "desc": "Docs vivos do Drive: busca um termo ou exporta um id, e processa como change digest."},
    {"id": "sys:ai-calendar", "name": "Ler a agenda (/calendar)", "agent": "/calendar", "arg": ("janela", "14d (vazio = padrão)", False),
     "do": ["Lê a agenda pelo MCP, só leitura (janela padrão 14d)", "Grava o snapshot gcal-primary na inbox",
            "Não cria evento: bloco de foco é a aba Aprovar › Foco"],
     "desc": "Snapshot da agenda: combustível do planejador de foco."},
    {"id": "sys:ai-recap", "name": "Recap de goal, projeto ou período (/recap)", "agent": "/recap",
     "arg": ("alvo", "GOAL-1 · PROJ-2 · 2025-01-01:2025-03-31", True),
     "do": ["Gera o documento datado em vault/reports/ (brain share)", "Escreve só fatos do ledger, cada um com fonte",
            "Publicar é outra porta, com seu gate"],
     "desc": "Documento datado e compartilhável com histórico e impacto de um goal, projeto ou período."},
    {"id": "sys:ai-upgrade", "name": "Reconciliar o framework (/upgrade)", "agent": "/upgrade",
     "do": ["brain update --check, depois o avanço com autostash", "Reconcilia edições locais (drift vs. edição) e semeia template/ novo",
            "Melhorias nascidas aqui voltam ao repo só com o seu ok"],
     "desc": "Atualiza o framework e devolve ao repo as melhorias locais. Use quando um git pull puro falhar por divergência."},
    {"id": "sys:ai-init", "name": "Primeira entrevista (/init)", "agent": "/init",
     "desc": "Descobre quem é o dono, seus goals, projetos e pessoas, e monta PROFILE e PLANNING como proposta, com gate."},
    {"id": "sys:mcp", "name": "Servidor MCP (somente leitura)", "args": ["mcp"], "info": True,
     "desc": "Expõe o cérebro por stdio para outras IAs consultarem; nenhuma ferramenta escreve. "
             "Registre com: claude mcp add segundo-cerebro -- brain mcp"},
]


@dataclass
class Item:
    id: str
    kind: str
    data: Any = None
    q: str = ""
    extra: dict = field(default_factory=dict)


class Store:
    def __init__(self, inst: config.Instance):
        self.inst = inst
        self.brain: Brain = Brain(inst)
        self.m: dict = {}
        self.health: list[dict] = []
        self.inbox = 0
        self.rendered_age_h: float | None = None
        self._cfg_stat = self._stat(self._cfg_file)
        self.load()

    # ── carga ──────────────────────────────────────────────────────────────
    def load(self) -> None:
        """Relê tudo do disco. Pode levantar BrainError (ledger corrompido)."""
        self._reload_cfg()
        brain = Brain(self.inst)
        m = model.build(brain)
        health = doctor.checks(brain)
        inbox = [p for p in self.inst.inbox.glob("*") if p.is_file() and p.name != ".keep.md"] \
            if self.inst.inbox.exists() else []
        rs = util.read_json(self.inst.fresh / ".render-state.json", {})
        age = None
        if rs.get("rendered_at"):
            age = max(0.0, (util.now() - util.parse_dt(rs["rendered_at"])).total_seconds() / 3600)
        self.brain, self.m, self.health, self.inbox, self.rendered_age_h = brain, m, health, len(inbox), age
        self.by_action = {a["id"]: a for a in m["actions"]}
        self.by_project = {p["id"]: p for p in m["projects"]}
        self.by_goal = {g["id"]: g for g in m["goals"]}
        self.by_deliv = {d["id"]: (p, d) for p in m["projects"] for d in p["deliverables"]}
        self.by_person = {p["id"]: p for p in m["people"]}
        self.by_artifact = {a["id"]: a for a in m["artifacts"]}
        self.by_msg = {x["id"]: x for x in m["outbox"]}
        pf = m["portfolio"]
        self.pf = pf
        self.by_opp = {o["id"]: o for o in pf["opportunities"]}
        self.by_proc = {p["id"]: p for p in pf["processes"]}
        self.by_area = {a["id"]: a for a in pf["areas"]}
        self._build_graph(m)
        self.notes = notes_mod.scan(self.inst)
        self.notes_by_link: dict[str, list[notes_mod.Note]] = {}
        for n in self.notes:
            self.notes_by_link.setdefault(n.link, []).append(n)
        self.watch_error = ""
        try:
            self.sources = self._sources()
        except util.BrainError as e:
            self.sources, self.watch_error = [], str(e)
        self.sig = self.signature()

    @property
    def _cfg_file(self):
        return self.inst.config_dir / "brain.toml"

    @staticmethod
    def _stat(p) -> tuple:
        try:
            x = p.stat()
            return (x.st_mtime_ns, x.st_size)
        except OSError:
            return (0, 0)

    def _reload_cfg(self) -> None:
        """brain.toml mudou desde a última leitura (`brain agent allow`, outro editor)? Relê: o allowlist do agente, o
        [outbound].allow e os destinos do publish valem já, sem reabrir o TUI. TOML quebrado mantém a config anterior."""
        st = self._stat(self._cfg_file)
        if st == self._cfg_stat:
            return
        try:
            user = tomllib.loads(self._cfg_file.read_text(encoding="utf-8")) if self._cfg_file.exists() else {}
        except (OSError, tomllib.TOMLDecodeError):
            return
        self.inst.cfg = config._merge(config.DEFAULTS, user)
        self._cfg_stat = st

    def signature(self) -> tuple:
        """Muda quando o vault muda fora do TUI (agente, outro terminal): ledger, PLANNING, inbox, watch.toml e brain.toml."""
        st = self._stat
        inbox = sorted(p.name for p in self.inst.inbox.glob("*")) if self.inst.inbox.exists() else []
        return (st(self.brain.ledger_path), st(self.inst.planning_file), st(watch.path(self.inst)), st(self._cfg_file), tuple(inbox))

    def _sources(self) -> list[dict]:
        """Fontes do watch.toml + o que o ledger sabe de cada pull; pulls avulsos (/connect) aparecem fora do watch."""
        conns, out, seen = self.brain.state.connectors, [], set()
        for s in watch.list_sources(self.inst):
            c = conns.get(s.get("key", ""))
            seen.add(s.get("key"))
            out.append({**s, "in_watch": True, "last_ok": c.last_ok if c else "", "last_error": c.last_error if c else "",
                        "failures": c.consecutive_failures if c else 0, "pulls": c.pulls if c else 0,
                        "last_changed": c.last_changed if c else ""})
        for k, c in conns.items():
            if k not in seen:
                out.append({"key": k, "kind": "", "in_watch": False, "last_ok": c.last_ok, "last_error": c.last_error,
                            "failures": c.consecutive_failures, "pulls": c.pulls, "last_changed": c.last_changed})
        return out

    def is_empty(self) -> bool:
        """Cérebro novo: sem goals e sem ninguém no ledger além do dono."""
        return not self.m["goals"] and len(self.m["people"]) <= 1 and not self.m["actions"]

    # ── apoio ──────────────────────────────────────────────────────────────
    # ── associações: o que está ligado a quê ──────────────────────────────
    ID_RE = ids.ANY_ID

    def _build_graph(self, m: dict) -> None:
        adj: dict[str, set[str]] = defaultdict(set)

        def link(a, b) -> None:
            if a and b and a != b:
                adj[a].add(b)
                adj[b].add(a)

        for a in m["actions"]:
            link(a["id"], a["project"])
            link(a["id"], a["deliverable"])
            for x in [*(a["blocked_by_all"] or []), *(a["unblocks"] or []), *a["people"], a["owner"]]:
                link(a["id"], x)
        for d in m["decisions"]:
            link(d["id"], d["project"])
            for x in [*d["decided_by"], d["supersedes"], d["superseded_by"]]:
                link(d["id"], x)
        for e in m["deliveries"]:
            link(e["id"], e["ref"])
            link(e["id"], e["project"])
        for a in m["artifacts"]:
            for x in [*a["projects"], *a["people"]]:
                link(a["id"], x)
        for r in m["proposals"]:
            link(r["id"], r["target"])
        for x in m["outbox"]:
            link(x["id"], x["ref"])
            link(x["id"], x["to"])
        self.adj = adj
        self.all_ids = ({a["id"] for a in m["actions"]} | {d["id"] for d in m["decisions"]} | {e["id"] for e in m["deliveries"]}
                        | {r["id"] for r in m["proposals"]} | {x["id"] for x in m["outbox"]} | {x["id"] for x in m["shares"]}
                        | set(self.brain.state.questions))
        self.plan_nodes = set(self.by_goal) | set(self.by_project) | set(self.by_deliv)

    def tree_up(self, node: str) -> set[str]:
        """Ancestrais na árvore do plano: PROJ-1.2 → PROJ-1, GOAL-1."""
        out: set[str] = set()
        if node in self.by_deliv:
            node = self.by_deliv[node][0]["id"]
            out.add(node)
        if node in self.by_project:
            out.add(self.by_project[node]["goal"])
        return out

    def tree_down(self, node: str) -> set[str]:
        if node in self.by_goal:
            projs = self.by_goal[node]["projects"]
            return set(projs) | {d["id"] for p in projs for d in self.by_project[p]["deliverables"]}
        if node in self.by_project:
            return {d["id"] for d in self.by_project[node]["deliverables"]}
        return set()

    def node_for(self, text: str) -> str | None:
        """O texto do filtro é exatamente um id (TASK-####, DEC-####, GOAL-#, PROJ-#, PROJ-#.#…; os nomes antigos também)?
        Devolve o id no formato do ledger."""
        t = ids.normalize((text or "").strip().upper())
        if not self.ID_RE.match(t):
            return None
        return t if t in self.plan_nodes | self.all_ids else None

    def related(self, node: str) -> set[str]:
        """Tudo que está associado a `node`, para o filtro: no plano, o próprio nó, os de cima e os de baixo com tudo
        que se liga a eles (ações, decisões, entregas…); nos demais, os vizinhos diretos e a árvore acima deles."""
        if node in self.plan_nodes:
            below = self.tree_down(node)
            res = {node} | self.tree_up(node) | below
            for x in {node} | below:
                res |= self.adj[x]
            if node in self.by_deliv:                               # decisões são do projeto
                proj = self.by_deliv[node][0]["id"]
                res |= {x for x in self.adj[proj] if x.startswith("DEC-")}
        else:
            res = {node} | self.adj[node]
            for x in list(res):
                res |= self.tree_up(x)
                if x in self.by_deliv or x in self.by_project:
                    res.add(x)
        res |= {p for x in list(res) for p in self.adj[x] if p in self.by_person}
        return res

    def decisions_of(self, node: str) -> list[dict]:
        """Decisões ligadas a um goal (via seus projetos), projeto ou entregável (via o projeto), da mais nova para a mais antiga."""
        if node in self.by_goal:
            pids = set(self.by_goal[node]["projects"])
        elif node in self.by_project:
            pids = {node}
        elif node in self.by_deliv:
            pids = {self.by_deliv[node][0]["id"]}
        else:
            return []
        return sorted((d for d in self.m["decisions"] if d["project"] in pids), key=lambda d: d["date"] or "", reverse=True)

    def notes_of(self, link: str) -> list[notes_mod.Note]:
        """Notas vinculadas a TASK-####/GOAL-#/PROJ-#/PROJ-#.#, da mais nova para a mais antiga."""
        return self.notes_by_link.get(link, [])

    def open_asks(self) -> list:
        """Perguntas abertas (esperam o dono), da mais antiga para a mais nova."""
        return sorted((q for q in self.brain.state.questions.values() if q.status == "aberta"), key=lambda q: q.id)

    def answered_asks(self) -> list:
        """Respondidas e ainda não aplicadas: a fila de reserva do passo 0."""
        return sorted((q for q in self.brain.state.questions.values() if q.status == "respondida"), key=lambda q: q.id)

    def person_name(self, pid: str) -> str:
        if pid.startswith("#"):
            return pid
        p = self.by_person.get(pid)
        return p["name"] if p else pid

    def first_name(self, pid: str) -> str:
        return self.person_name(pid).split(" ")[0]

    def _vault_file(self, ref: str) -> Path | None:
        """Arquivo real de um caminho do ledger (RAW/… acha a pasta do tipo); None se não for arquivo do vault."""
        ref = (ref or "").split("#")[0].strip()
        p = Path(ref)
        if not ref or ref == "chat" or p.is_absolute() or ".." in p.parts:
            return None
        f = rawsort.resolve(self.inst, ref) if p.parts[0] == "RAW" else self.inst.vault / p
        return f if f and f.is_file() and f.resolve().is_relative_to(self.inst.vault.resolve()) else None

    def linked_files(self, node: str = "", sources: tuple = (), docs: list | None = None) -> list[dict]:
        """Arquivos do vault ligados a um item, sem repetir: notas do vínculo, artefatos do projeto, fontes (artefato + RAW) e documentos.

        Cada um: {kind, name, rel (relativo ao vault), app (aplicativo que abre; vazio = padrão do sistema)}."""
        out: dict[str, dict] = {}

        def add(kind: str, name: str, ref: str) -> None:
            f = self._vault_file(ref)
            if f is None:
                return
            rel = self.inst.rel(f)
            if rel not in out:
                out[rel] = {"kind": kind, "name": name or f.name, "rel": rel, "app": opener.app_for(self.inst.cfg, f)}

        for n in self.notes_of(node) if node else []:
            add("nota", f"{n.created} {n.title}", n.path)
        pids = set(self.by_goal[node]["projects"]) if node in self.by_goal else \
            {self.by_deliv[node][0]["id"]} if node in self.by_deliv else {node} if node in self.by_project else set()
        for a in self.m["artifacts"]:
            if pids & set(a["projects"]):
                add("artefato", a["title"], a["id"])
                add("RAW", Path(a["raw"]).name if a["raw"] else "", a["raw"])
        for src in sources:
            key = (src or "").split("#")[0]
            art = self.by_artifact.get(key)
            if art:
                add("artefato", art["title"], art["id"])
                add("RAW", Path(art["raw"]).name if art["raw"] else "", art["raw"])
            else:
                add("RAW" if key.startswith("RAW/") else "documento", "", key)
        for d in docs or []:
            add("documento", d.get("title") or "", d["ref"])
        return list(out.values())

    def title_of(self, ref: str) -> str:
        """Título da entidade citada (ação, goal, projeto, entregável, decisão, oportunidade, processo); vazio se não for ID conhecido."""
        ref = ids.normalize(ref or "")
        if ref in self.by_deliv:
            return self.by_deliv[ref][1]["title"]
        for tbl in (self.by_action, self.by_goal, self.by_project, self.by_opp, self.by_proc):
            if ref in tbl:
                return tbl[ref]["title"]
        for key in ("decisions", "deliveries"):
            for x in self.m[key]:
                if x["id"] == ref:
                    return x["title"]
        return ""

    @property
    def owner(self) -> str:
        return self.m["owner"]["id"]

    @property
    def counts(self) -> dict:
        return self.m["counts"]

    def allow(self) -> list[str]:
        return list(self.inst.cfg["outbound"]["allow"])

    def destinations(self) -> list[str]:
        return list(self.inst.cfg["publish"]["destinations"])

    def active_goals(self, keep: str = "") -> list[dict]:
        """Goals ativos, na ordem do goals.md (`keep` = um goal que já está escolhido e precisa continuar na lista)."""
        return [g for g in self.m["goals"] if g["status"] == "ativo" or g["id"] == keep]

    def active_projects(self, goal: str = "", keep: str = "") -> list[dict]:
        """Projetos ativos — de um goal, ou de todos. `keep` = projeto já escolhido que precisa continuar na lista."""
        return [p for p in self.m["projects"]
                if (p["status"] == "ativo" and (not goal or p["goal"] == goal)) or p["id"] == keep]

    def text_sha(self, mid: str) -> str:
        m = self.brain.state.messages.get(mid)
        return (m.text_sha or "")[:12] if m else ""

    def sent_today(self) -> int:
        t = util.today().isoformat()
        return sum(1 for x in self.m["outbox"] if x["status"] == "enviada" and x["sent"] == t)

    def focus_days(self) -> list[tuple[str, list[dict]]]:
        f = self.m["focus"]
        if not f:
            return []
        blocks = f["applied"] if f["status"] == "aplicado" and f["applied"] else f["blocks"]
        days: dict[str, list[dict]] = {}
        for b in sorted(blocks, key=lambda x: x["start"]):
            days.setdefault(b["start"][:10], []).append(b)
        return sorted(days.items())

    def reports(self) -> list[str]:
        d = self.inst.reports / "share"
        if not d.exists():
            return []
        return sorted((self.inst.rel(p) for p in d.glob("*.*") if p.is_file()), reverse=True)

    @staticmethod
    def _fix_for(c: dict) -> dict | None:
        """O que o TUI sabe fazer a respeito de um aviso do doctor (tecla f)."""
        if c["level"] == "ok" and not c["title"].startswith("fonte "):
            return None
        t = c["title"]
        if t == "inbox":
            return {"label": "processar com o agente", "agent": "dump"}
        if t == "noturno":
            return {"label": "agendar o noturno", "sys": "sys:schedule"}
        if t == "ações sem prazo":
            return {"label": "ir às ações e dar prazo", "go": (2, 0)}
        if t.startswith("fonte "):
            return {"label": "puxar agora com o agente", "agent": "connect", "key": t.split(" ", 1)[1]}
        if t == "mensagens":
            return {"label": "ir ao outbox", "go": (4, 2)}
        if t == "foco":
            return {"label": "ir ao plano de foco", "go": (4, 3)}
        if t == "propostas":
            return {"label": "ir às propostas", "go": (4, 1)}
        if t == "perguntas":
            return {"label": "ir às perguntas do agente", "go": (4, 0)}
        return None

    # ── listas por painel ──────────────────────────────────────────────────
    def items(self, face: int, panel: int, tab: int, show_all: bool = False, filt: str = "",
              collapsed: set[str] | None = None, view: int = 0, sort: int = 0) -> list[Item]:
        if panel == 6 and tab == 1:          # aba Feedback do painel do log: fila do que vira issue — comum a TODAS as faces
            fbs = [f for f in self.brain.state.feedbacks.values() if show_all or f.status != "criado"]
            order = {"pendente": 0, "falhou": 1, "criado": 2}      # acionável no topo
            fbs.sort(key=lambda f: (order.get(f.status, 3), f.id))
            out: list[Item] = [Item(f.id, "fb", f, q=f"{f.id} {f.kind} {f.title} {f.status} {f.url}") for f in fbs]
            if filt:
                fl = util.fold(filt)
                out = [i for i in out if fl in util.fold(i.q)]
            return out
        if face != 0:
            return self._items_face(face, panel, tab, show_all, filt)
        m, collapsed = self.m, (set() if filt else collapsed or set())     # filtrando, a árvore abre sozinha
        out = []
        if panel == 1:
            if tab == 0:
                out = [Item("resumo", "resumo", q="resumo hoje")]
            elif tab == 1:
                out = [Item(f"src:{s['key']}", "src", s, q=f"{s['key']} {s.get('kind', '')} {s.get('channel', '')}") for s in self.sources]
            else:
                out = [Item(o["id"], "sys", o, q=f"{o['name']} {' '.join(o.get('args', []))} {o.get('agent', '')}") for o in SYS_OPS]
        elif panel == 2:
            lst = ["mine", "waiting", "watching"][tab]
            rows = [a for a in m["actions"] if a["list"] == lst and (show_all or a["open"])]
            if view:
                today = util.today()
                rows = [a for a in rows if action_view(a, today) == view]
            if sort == 1:
                rows.sort(key=lambda a: (not a["open"], a["id"]))
            else:
                rows.sort(key=lambda a: (not a["open"], a["due"] is None, a["due"] or "", a["id"]))
            out = [Item(a["id"], "action", a, q=f"{a['id']} {a['title']} {a['project'] or ''} {a['owner_name']}")
                   for a in rows]
        elif panel == 3:
            want = PLAN_TAB_STATUS[tab] if tab < len(PLAN_TAB_STATUS) else None
            for g in m["goals"]:
                if want is not None and g["status"] != want:
                    pids = [pid for pid in g["projects"] if self.by_project[pid]["status"] == want]
                    if not pids:
                        continue                      # nem o goal nem um projeto dele está na aba
                else:
                    pids = list(g["projects"])
                out.append(Item(g["id"], "g", g, q=f"{g['id']} {g['title']}"))
                if g["id"] in collapsed:
                    continue
                for pid in pids:
                    p = self.by_project[pid]
                    out.append(Item(pid, "p", p, q=f"{pid} {p['title']}", extra={"goal": g}))
                    if pid in collapsed:
                        continue
                    for d in p["deliverables"]:
                        out.append(Item(d["id"], "d", d, q=f"{d['id']} {d['title']}", extra={"project": p, "goal": g}))
        elif panel == 4:
            if tab == 0:
                qs = [q for q in self.brain.state.questions.values() if show_all or q.status in ("aberta", "respondida")]
                qs.sort(key=lambda q: (q.status != "aberta", q.id))          # abertas no topo; respondidas aguardando aplicação abaixo
                out = [Item(q.id, "ask", q, q=f"{q.id} {q.kind} {q.text} {q.answer} {' '.join(q.context)}") for q in qs]
            elif tab == 1:
                props = [p for p in self.brain.state.proposals.values() if show_all or p.status == "aberta"]
                out = [Item(p.id, "prop", p, q=f"{p.id} {p.kind} {p.summary}") for p in props]
            elif tab == 2:
                rows = [x for x in m["outbox"] if show_all or x["status"] in ("rascunho", "aprovada")]
                out = [Item(x["id"], "msg", x, q=f"{x['id']} {x['to']} {x['text']}") for x in rows]
            elif tab == 3:
                days = self.focus_days()
                out = [Item(f"d:{d}", "fday", {"day": d, "blocks": bl}, q=d) for d, bl in days]
                out.append(Item("f:warn", "fwarn", m["focus"], q="não cabe sem prazo"))
            elif tab == 4:
                rows = [s for s in m["shares"] if show_all or s["status"] in ("solicitada", "aprovada")]
                out = [Item(s["id"], "pub", s, q=f"{s['id']} {s['report']} {s['destination']}") for s in rows]
        elif panel == 5:
            if tab == 0:
                out = [Item(d["id"], "dec", d, q=f"{d['id']} {d['title']}") for d in m["decisions"]]
            elif tab == 1:
                out = [Item(e["id"], "del", e, q=f"{e['id']} {e['title']}") for e in m["deliveries"]]
            elif tab == 2:
                out = [Item(p["id"], "per", p, q=f"{p['id']} {p['name']} {' '.join(p['aliases'])}") for p in m["people"]]
            else:
                out = [Item(a["id"], "art", a, q=f"{a['title']} {a['kind']} {a['summary']}") for a in m["artifacts"]]
        if filt:
            f, node = util.fold(filt), self.node_for(filt)
            if node:                                  # filtro é um id: mostra tudo que está associado a ele
                rel = self.related(node)
                out = [i for i in out if self._shown(i, rel, f)]
            else:
                out = [i for i in out if f in util.fold(i.q)]
        return out

    def _items_face(self, face: int, panel: int, tab: int, show_all: bool, filt: str) -> list[Item]:
        """Listas das faces além da Execução: Portfólio (1) e Configurações (2)."""
        if face == 2:
            return self._items_cfg(panel, tab, filt)
        if face != 1:
            return []
        pf, out = self.pf, []
        opps, procs = pf["opportunities"], [p for p in pf["processes"] if p["status"] == "ativo"]

        def opp_item(o: dict, **extra) -> Item:
            return Item(o["id"], "opp", o, q=f"{o['id']} {o['title']} {o['status']} {o['area']} {o['problem']}", extra=extra)

        def proc_item(p: dict) -> Item:
            return Item(p["id"], "proc", p, q=f"{p['id']} {p['title']} {p['area']} {p['owner_name'] or ''} {' '.join(p['pains'])}")

        def ranked(rows: list[dict]) -> list[dict]:
            return sorted(rows, key=lambda o: (-(o["score"] or 0), o["id"]))

        def grouped(groups: list[tuple[str, dict, list[Item]]]) -> list[Item]:
            rows: list[Item] = []
            for gid, data, children in groups:
                if not filt:
                    rows.append(Item(f"grp:{gid}", "pgrp", data, q=data["label"]))
                rows += children
            return rows

        if panel == 1:
            if tab == 0:
                out = [Item("pv:funil", "pvfunil", pf, q="funil status")]
                out += [opp_item(self.by_opp[i], rank=n) for n, i in enumerate(pf["ranking"][:5], 1)]
                out.append(Item("pv:gaps", "pvgaps", pf, q="lacunas"))
            elif tab == 1:
                out = grouped([(a["id"], {"label": a["name"], "sub": f"{a['processes']} processos · {a['opportunities']} oportunidades"},
                                [opp_item(o) for o in ranked(opps) if o["area"] == a["id"]]) for a in pf["areas"]])
            else:
                groups = [(g["id"], {"label": f"{g['id']} {g['title']}", "sub": f"{g['progress']['pct'] if g['progress']['pct'] is not None else '—'}%"},
                           [opp_item(o) for o in ranked(opps) if o["goal"] == g["id"]]) for g in self.m["goals"]]
                none = [opp_item(o) for o in ranked(opps) if not o["goal"]]
                groups.append(("none", {"label": "sem goal ainda", "sub": f"{len(none)}"}, none))
                out = grouped([g for g in groups if g[2] or g[0] != "none"])
        elif panel == 2:
            if tab == 1:
                out = grouped([(a["id"], {"label": a["name"], "sub": f"{a['processes']} processos"},
                                [proc_item(p) for p in procs if p["area"] == a["id"]]) for a in pf["areas"]])
            else:
                rows = [p for p in procs if tab == 0 or p["gaps"]]
                out = [proc_item(p) for p in sorted(rows, key=lambda p: (p["area"], p["id"]))]
        elif panel == 3:
            out = [opp_item(o) for o in ranked(opps) if o["status"] in OPP_TABS[tab]]
        elif panel == 4:
            if tab == 0:
                from .. import portfolio
                out = [Item(f"mx:{q}", "mx", {"quadrant": q, "ids": pf["matrix"][q]}, q=q) for q in portfolio.QUADRANTS]
            else:
                out = [opp_item(self.by_opp[i], rank=n) for n, i in enumerate(pf["ranking"], 1)]
        elif panel == 5:
            if tab == 0:
                out = [Item(a["id"], "area", a, q=f"{a['id']} {a['name']} {' '.join(a['aliases'])}") for a in pf["areas"]]
            else:
                for t in [*pf["processes"], *pf["opportunities"]]:
                    for n, d in enumerate(t["docs"]):
                        out.append(Item(f"{t['id']}#{n}", "docl", {**d, "target": t["id"], "target_title": t["title"], "n": n},
                                        q=f"{t['id']} {d['kind']} {d['title']} {d['ref']}"))
        if filt:
            f = util.fold(filt)
            out = [i for i in out if f in util.fold(i.q)]
        return out

    def _shown(self, it: Item, rel: set[str], f: str) -> bool:
        if it.kind in ("action", "g", "p", "d", "prop", "ask", "msg", "dec", "del", "per", "art"):
            return it.id in rel
        if it.kind == "fday":
            return any(b["action"] in rel for b in it.data["blocks"])
        return f in util.fold(it.q)

    def locate(self, node: str) -> tuple[int, int, int] | None:
        """Onde um id aparece: (face, painel, aba). Usado nos links do detalhe, na busca e na paleta."""
        if node in self.by_opp:
            status = self.by_opp[node]["status"]
            # fora dos grupos nomeados (status novo/exótico) cai na última aba, que é o "resto" por design
            return (1, 3, next((i for i, g in enumerate(OPP_TABS) if status in g), len(OPP_TABS) - 1))
        if node in self.by_proc:
            return (1, 2, 0)
        loc = self._locate_exec(node)
        return (0, *loc) if loc else None

    def _locate_exec(self, node: str) -> tuple[int, int] | None:
        node = ids.normalize(node)
        if node.startswith("TASK-"):
            a = self.by_action.get(node)
            return (2, ["mine", "waiting", "watching"].index(a["list"])) if a else None
        if ids.PLAN_NODE.match(node):
            return (3, 0)
        for prefix, loc in (("ASK-", (4, 0)), ("PROP-", (4, 1)), ("MSG-", (4, 2)), ("d:", (4, 3)), ("PUB-", (4, 4)),
                            ("DEC-", (5, 0)), ("WIN-", (5, 1))):
            if node.startswith(prefix):
                return loc
        if node in self.by_person:
            return (5, 2)
        if any(a["id"] == node for a in self.m["artifacts"]):
            return (5, 3)
        return None

    def _items_cfg(self, panel: int, tab: int, filt: str) -> list[Item]:
        """Face Configurações: provedores da memória (llm · embeddings · reranker), harnesses, saúde."""
        out: list[Item] = []
        if panel == 1:
            if tab == 0:
                from .. import providers as _prov
                icons = {"llm": "LLM", "embeddings": "Embeddings", "reranker": "Reranker"}
                st = _prov.stack(self.brain)
                for slot in _prov.SLOTS:
                    s = st[slot]
                    out.append(Item(f"prov:{slot}", "prov", {"slot": slot, "icon": icons[slot], **s},
                                    q=f"{slot} {s['provider']} {s['model']} {s['label']}"))
            else:
                from .. import harness as _h
                wired = self.inst.cfg["memory"].get("harnesses") or []
                det = _h.detect()
                for name in ("claude-code", "cursor-cli", "codex", "hermes"):
                    label = _h.AGENTS.get(name, "Hermes")
                    out.append(Item(f"hw:{name}", "hw",
                                    {"name": name, "label": label, "wired": name in wired,
                                     "detected": det.get(name, False)},
                                    q=f"{name} {label} {'cablado' if name in wired else 'desligado'}"))
        elif panel == 2:
            out = [Item(f"doc:{i}", "doc", c, q=f"{c['title']} {c['detail']}",
                        extra={"fix": self._fix_for(c)}) for i, c in enumerate(self.health)]
        if filt:
            f = util.fold(filt)
            out = [i for i in out if f in util.fold(i.q)]
        return out
