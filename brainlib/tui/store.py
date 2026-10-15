"""Leitura somente-leitura do cérebro para o TUI: view model, saúde e listas por painel.

Nada aqui escreve. O TUI recarrega depois de cada comando que ele mesmo dispara.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import config, doctor, model, util, watch
from ..core import Brain

PANELS = {
    1: ("Status", ["Resumo", "Saúde", "Fontes", "Sistema"]),
    2: ("Ações", ["mine", "waiting", "watching"]),
    3: ("Plano", ["Árvore"]),
    4: ("Aprovar", ["Propostas", "Outbox", "Foco", "Publicar"]),
    5: ("Registro", ["Decisões", "Entregas", "Pessoas", "Artefatos"]),
}

SYS_OPS = [
    {"id": "sys:render", "name": "Regenerar views", "args": ["render"],
     "desc": "Colhe checkboxes e status editados à mão e reescreve todo o FRESH (Markdown e painel HTML). "
             "Roda sozinho depois de cada escrita feita aqui."},
    {"id": "sys:open", "name": "Abrir o painel HTML", "args": ["render", "--open"],
     "desc": "Regenera as views e abre o painel (um arquivo, offline) no navegador."},
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
        self.load()

    # ── carga ──────────────────────────────────────────────────────────────
    def load(self) -> None:
        """Relê tudo do disco. Pode levantar BrainError (ledger corrompido)."""
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
        self.by_msg = {x["id"]: x for x in m["outbox"]}
        self.watch_error = ""
        try:
            self.sources = self._sources()
        except util.BrainError as e:
            self.sources, self.watch_error = [], str(e)
        self.sig = self.signature()

    def signature(self) -> tuple:
        """Muda quando o vault muda fora do TUI (agente, outro terminal): ledger, PLANNING e inbox."""
        def st(p) -> tuple:
            try:
                x = p.stat()
                return (x.st_mtime_ns, x.st_size)
            except OSError:
                return (0, 0)
        inbox = sorted(p.name for p in self.inst.inbox.glob("*")) if self.inst.inbox.exists() else []
        return (st(self.brain.ledger_path), st(self.inst.planning_file), st(watch.path(self.inst)), tuple(inbox))

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
    def person_name(self, pid: str) -> str:
        if pid.startswith("#"):
            return pid
        p = self.by_person.get(pid)
        return p["name"] if p else pid

    def first_name(self, pid: str) -> str:
        return self.person_name(pid).split(" ")[0]

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

    def project_ids(self) -> list[str]:
        return list(self.by_project)

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
            return {"label": "ir ao outbox", "go": (4, 1)}
        if t == "foco":
            return {"label": "ir ao plano de foco", "go": (4, 2)}
        if t == "propostas":
            return {"label": "ir às propostas", "go": (4, 0)}
        return None

    # ── listas por painel ──────────────────────────────────────────────────
    def items(self, panel: int, tab: int, show_all: bool = False, filt: str = "",
              collapsed: set[str] | None = None) -> list[Item]:
        m, collapsed = self.m, collapsed or set()
        out: list[Item] = []
        if panel == 1:
            if tab == 0:
                out = [Item("resumo", "resumo", q="resumo hoje")]
            elif tab == 1:
                out = [Item(f"doc:{i}", "doc", c, q=f"{c['title']} {c['detail']}", extra={"fix": self._fix_for(c)})
                       for i, c in enumerate(self.health)]
            elif tab == 2:
                out = [Item(f"src:{s['key']}", "src", s, q=f"{s['key']} {s.get('kind', '')} {s.get('channel', '')}") for s in self.sources]
            else:
                out = [Item(o["id"], "sys", o, q=f"{o['name']} {' '.join(o.get('args', []))}") for o in SYS_OPS]
        elif panel == 2:
            lst = ["mine", "waiting", "watching"][tab]
            rows = [a for a in m["actions"] if a["list"] == lst and (show_all or a["open"])]
            rows.sort(key=lambda a: (not a["open"], a["due"] is None, a["due"] or "", a["id"]))
            out = [Item(a["id"], "action", a, q=f"{a['id']} {a['title']} {a['project'] or ''} {a['owner_name']}")
                   for a in rows]
        elif panel == 3:
            for g in m["goals"]:
                out.append(Item(g["id"], "g", g, q=f"{g['id']} {g['title']}"))
                if g["id"] in collapsed:
                    continue
                for pid in g["projects"]:
                    p = self.by_project[pid]
                    out.append(Item(pid, "p", p, q=f"{pid} {p['title']}", extra={"goal": g}))
                    if pid in collapsed:
                        continue
                    for d in p["deliverables"]:
                        out.append(Item(d["id"], "d", d, q=f"{d['id']} {d['title']}", extra={"project": p, "goal": g}))
        elif panel == 4:
            if tab == 0:
                props = [p for p in self.brain.state.proposals.values() if show_all or p.status == "aberta"]
                out = [Item(p.id, "prop", p, q=f"{p.id} {p.kind} {p.summary}") for p in props]
            elif tab == 1:
                rows = [x for x in m["outbox"] if show_all or x["status"] in ("rascunho", "aprovada")]
                out = [Item(x["id"], "msg", x, q=f"{x['id']} {x['to']} {x['text']}") for x in rows]
            elif tab == 2:
                days = self.focus_days()
                out = [Item(f"d:{d}", "fday", {"day": d, "blocks": bl}, q=d) for d, bl in days]
                out.append(Item("f:warn", "fwarn", m["focus"], q="não cabe sem prazo"))
            else:
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
            f = util.fold(filt)
            out = [i for i in out if f in util.fold(i.q)]
        return out

    def locate(self, node: str) -> tuple[int, int] | None:
        """Onde um id aparece: (painel, aba). Usado nos links do detalhe, na busca e na paleta."""
        if node.startswith("A-"):
            a = self.by_action.get(node)
            return (2, ["mine", "waiting", "watching"].index(a["list"])) if a else None
        if node[:1] in "GP" and node[1:2].isdigit():
            return (3, 0)
        for prefix, loc in (("R-", (4, 0)), ("M-", (4, 1)), ("d:", (4, 2)), ("S-", (4, 3)),
                            ("D-", (5, 0)), ("E-", (5, 1))):
            if node.startswith(prefix):
                return loc
        if node in self.by_person:
            return (5, 2)
        if any(a["id"] == node for a in self.m["artifacts"]):
            return (5, 3)
        return None
