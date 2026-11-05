"""PLANNING/goals.md — a árvore curada (goal → projeto → entregável), em Markdown estrito.

    ## GOAL-1 — Nome do goal
    - status: ativo
    - horizonte: 2027-06-30
    - por quê: o que isto destrava

    ### PROJ-1 — Nome do projeto
    - status: ativo
    - dono: marina-demo
    - [ ] PROJ-1.1 Entregável · prazo: 2026-10-30 · peso: 2
    - [x] PROJ-1.2 Entregável · prazo: 2026-11-15 · feito: 2026-11-10
    - [-] PROJ-1.3 Entregável cancelado

Na leitura, `G1` / `P1` / `P1.1` (nomes antigos) valem como sinônimo de `GOAL-1` / `PROJ-1` / `PROJ-1.1`; o parser
devolve sempre o nome novo, e o arquivo só passa ao formato novo quando o cérebro reescreve a linha (ou em `migrate ids`).

Progresso de projeto/goal = peso dos entregáveis feitos / peso dos não cancelados.
O agente só muda a ESTRUTURA com aprovação (gate); o estado factual (checkbox,
data de conclusão) muda com log — via `brain plan deliverable`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import ids, util

# o parser lê os dois formatos (GOAL-1 e o antigo G1…); ids.normalize devolve sempre o novo
GOAL_RE = re.compile(rf"^##\s+(GOAL-\d+|{ids.LEGACY_GOAL_SRC})\s*[—–-]\s*(.+?)\s*$")
PROJ_RE = re.compile(rf"^###\s+(PROJ-\d+|{ids.LEGACY_PROJ_SRC})\s*[—–-]\s*(.+?)\s*$")
DELIV_RE = re.compile(rf"^(\s*-\s+\[)( |x|X|-)(\]\s+)(PROJ-\d+\.\d+|{ids.LEGACY_DELIV_SRC})\s+(.+?)\s*$")
META_RE = re.compile(r"^\s*-\s+([^\[\]:]{2,24}):\s*(.+?)\s*$")
H2_RE = re.compile(r"^##\s+")


@dataclass
class Deliverable:
    id: str
    title: str
    project_id: str
    status: str            # nao-iniciado | em-andamento | feito | cancelado
    due: date | None = None
    done_date: date | None = None
    weight: int = 1
    line_no: int = 0

    @property
    def done(self) -> bool:
        return self.status == "feito"


@dataclass
class Project:
    id: str
    title: str
    goal_id: str
    meta: dict = field(default_factory=dict)
    deliverables: list[Deliverable] = field(default_factory=list)

    @property
    def status(self) -> str:
        return norm_status(self.meta.get("status", "ativo"))

    @property
    def owner(self) -> str | None:
        return self.meta.get("dono")


@dataclass
class Goal:
    id: str
    title: str
    meta: dict = field(default_factory=dict)
    projects: list[Project] = field(default_factory=list)

    @property
    def status(self) -> str:
        return norm_status(self.meta.get("status", "ativo"))

    @property
    def horizon(self) -> str | None:
        return self.meta.get("horizonte")

    @property
    def why(self) -> str | None:
        return self.meta.get("por que") or self.meta.get("porque")


@dataclass
class Plan:
    goals: dict[str, Goal] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    deliverables: dict[str, Deliverable] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def has(self, node: str) -> bool:
        node = ids.normalize(node)
        return node in self.goals or node in self.projects or node in self.deliverables

    def goal_of(self, node: str | None) -> str | None:
        if not node:
            return None
        node = ids.normalize(node)
        if node in self.goals:
            return node
        if node in self.projects:
            return self.projects[node].goal_id
        if node in self.deliverables:
            return self.projects[self.deliverables[node].project_id].goal_id
        return None

    def project_of(self, node: str | None) -> str | None:
        if not node:
            return None
        node = ids.normalize(node)
        if node in self.projects:
            return node
        if node in self.deliverables:
            return self.deliverables[node].project_id
        return None

    def title(self, node: str) -> str:
        node = ids.normalize(node)
        for coll in (self.goals, self.projects, self.deliverables):
            if node in coll:
                return coll[node].title
        return node

    def deliverables_of(self, node: str) -> list[Deliverable]:
        node = ids.normalize(node)
        if node in self.projects:
            return list(self.projects[node].deliverables)
        if node in self.goals:
            return [d for p in self.goals[node].projects for d in p.deliverables]
        if node in self.deliverables:
            return [self.deliverables[node]]
        return []

    def progress(self, node: str) -> dict:
        items = [d for d in self.deliverables_of(node) if d.status != "cancelado"]
        weight_total = sum(d.weight for d in items)
        weight_done = sum(d.weight for d in items if d.done)
        return {
            "done": sum(1 for d in items if d.done),
            "total": len(items),
            "weight_done": weight_done,
            "weight_total": weight_total,
            "pct": round(100 * weight_done / weight_total) if weight_total else None,
        }


def _lines(text: str) -> list[str]:
    """Linhas do goals.md quebradas só no fim de linha de verdade (o `read_text` já traduz CRLF). `str.splitlines`
    também quebra em U+2028, form feed, NEL…: reescrever o arquivo trocava esses caracteres do texto do dono por
    quebras de linha (e desalinhava a numeração entre o parser e quem reescreve)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _parse_segments(rest: str) -> tuple[str, dict]:
    parts = [p.strip() for p in rest.split("·")]
    title = parts[0]
    seg: dict[str, str] = {}
    for p in parts[1:]:
        if ":" in p:
            k, _, v = p.partition(":")
            seg[util.fold(k)] = v.strip()
        elif p:
            seg[util.fold(p)] = "sim"
    return title, seg


def _raw_segments(rest: str) -> tuple[str, list[list[str]]]:
    """Como `_parse_segments`, mas guarda o texto original de cada segmento ([chave dobrada, texto]), na ordem do
    dono: reescrever a linha só troca os segmentos que o cérebro mexe (prazo, peso, estado, feito)."""
    parts = [p.strip() for p in rest.split("·")]
    segs = [[util.fold(p.partition(":")[0]), p] for p in parts[1:] if p]
    return parts[0], segs


def _set_seg(segs: list[list[str]], key: str, value: str | None) -> None:
    """Troca (no lugar), acrescenta (no fim) ou remove (`value` vazio) o segmento `key`."""
    idx = [i for i, (k, _) in enumerate(segs) if k == key]
    for i in reversed(idx[1:] if value else idx):
        del segs[i]
    if value:
        if idx:
            segs[idx[0]][1] = f"{key}: {value}"
        else:
            segs.append([key, f"{key}: {value}"])


def _strip_comments(lines: list[str]) -> list[str]:
    """Troca linhas dentro de <!-- --> ou ``` por vazias (preserva numeração)."""
    out, in_html, in_fence = [], False, False
    for ln in lines:
        if in_fence:
            out.append("")
            if ln.strip().startswith("```"):
                in_fence = False
            continue
        if in_html:
            out.append("")
            if "-->" in ln:
                in_html = False
            continue
        if ln.strip().startswith("```"):
            in_fence = True
            out.append("")
            continue
        ln = re.sub(r"<!--.*?-->", "", ln)
        if "<!--" in ln:                    # abre e não fecha nesta linha (mesmo depois de outro comentário fechado)
            in_html = True
            out.append(ln.split("<!--", 1)[0])
            continue
        out.append(ln)
    return out


def parse(text: str) -> Plan:
    plan = Plan()
    goal: Goal | None = None
    proj: Project | None = None
    in_deliv = False                    # já passou de um entregável: sub-item recuado é nota dele, não metadado
    for i, ln in enumerate(_strip_comments(_lines(text)), start=1):
        if ln.startswith("#"):
            in_deliv = False
        m = GOAL_RE.match(ln)
        if m:
            gid, title = ids.normalize(m.group(1)), m.group(2)
            if gid in plan.goals:
                plan.warnings.append(f"linha {i}: {gid} duplicado")
            goal = Goal(gid, title)
            plan.goals[gid] = goal
            proj = None
            continue
        if H2_RE.match(ln):
            goal, proj = None, None
            continue
        m = PROJ_RE.match(ln)
        if m:
            pid, title = ids.normalize(m.group(1)), m.group(2)
            if goal is None:
                plan.warnings.append(f"linha {i}: projeto {pid} fora de um goal — ignorado")
                proj = None
                continue
            if pid in plan.projects:
                plan.warnings.append(f"linha {i}: {pid} duplicado")
            proj = Project(pid, title, goal.id)
            plan.projects[pid] = proj
            goal.projects.append(proj)
            continue
        m = DELIV_RE.match(ln)
        if m:
            box, did, rest = m.group(2), ids.normalize(m.group(4)), m.group(5)
            if proj is None:
                plan.warnings.append(f"linha {i}: entregável {did} fora de um projeto — ignorado")
                continue
            if not did.startswith(proj.id + "."):
                plan.warnings.append(f"linha {i}: {did} está sob {proj.id} (prefixo diferente)")
            title, seg = _parse_segments(rest)
            if box in "xX":
                status = "feito"
            elif box == "-":
                status = "cancelado"
            else:
                status = "em-andamento" if util.fold(seg.get("estado", "")) in {
                    "em-andamento", "em andamento"} else "nao-iniciado"
            d = Deliverable(did, title, proj.id, status, line_no=i)
            try:
                d.due = util.parse_date(seg.get("prazo")) if seg.get("prazo") not in (None, "?") else None
                d.done_date = util.parse_date(seg.get("feito")) if seg.get("feito") else None
            except util.BrainError as e:
                plan.warnings.append(f"linha {i}: {did}: {e}")
            try:
                d.weight = max(1, int(seg.get("peso", 1)))
            except ValueError:
                plan.warnings.append(f"linha {i}: {did}: peso inválido")
            if did in plan.deliverables:
                plan.warnings.append(f"linha {i}: {did} duplicado")
            plan.deliverables[did] = d
            proj.deliverables.append(d)
            in_deliv = True
            continue
        if in_deliv and ln[:1].isspace():
            continue
        m = META_RE.match(ln)
        if m:
            key, value = util.fold(m.group(1)), m.group(2)
            target = proj if proj is not None else goal
            if target is not None:
                target.meta[key] = value
    return plan


def format_progress(p: dict) -> str:
    """Percentual é por peso; a fração é por contagem. Mostra o peso quando os dois divergem."""
    if p.get("pct") is None:
        return "—"
    text = f"{p['pct']}% ({p['done']}/{p['total']})"
    wd, wt = p.get("weight_done"), p.get("weight_total")
    if wt is not None and (wd != p["done"] or wt != p["total"]):
        text += f", peso {wd}/{wt}"
    return text


def load(path: Path) -> Plan:
    if not path.exists():
        return Plan(warnings=[f"{path.name} não existe"])
    return parse(path.read_text(encoding="utf-8"))


def _deliv_line(head: str, box: str, mid: str, did: str, title: str, segs: list[list[str]]) -> str:
    """Remonta a linha do entregável; os segmentos que o cérebro não mexeu voltam com o texto exato do dono."""
    tail = "".join(f" · {text}" for _, text in segs)
    return f"{head}{box}{mid}{did} {title}{tail}"


def set_deliverable(path: Path, did: str, status: str, when: date | None) -> bool:
    """Atualiza o checkbox (estado factual) de um entregável. Retorna True se mudou."""
    did = ids.normalize(did)
    text = path.read_text(encoding="utf-8")
    lines = _lines(text)
    plan = parse(text)
    d = plan.deliverables.get(did)
    if d is None:
        raise util.BrainError(f"entregável {did} não encontrado em {path.name}", code=3)
    ln = lines[d.line_no - 1]
    m = DELIV_RE.match(ln)
    if m is None:
        raise util.BrainError(f"linha {d.line_no} de {did} não está no formato do parser — não alterei o arquivo", code=5)
    head, _, mid, _, rest = m.groups()
    title, segs = _raw_segments(rest)
    box, estado, feito = " ", None, None
    if status == "feito":
        box, feito = "x", (when or util.today()).isoformat()
    elif status == "cancelado":
        box = "-"
    elif status == "em-andamento":
        estado = "em-andamento"
    _set_seg(segs, "estado", estado)
    _set_seg(segs, "feito", feito)
    new = _deliv_line(head, box, mid, did, title, segs)
    if new == ln:
        return False
    lines[d.line_no - 1] = new
    util.atomic_write(path, "\n".join(lines) + "\n")
    return True


# ── criar nós (goal, projeto, entregável) ────────────────────────────────────
def _next(prefix: str, keys) -> int:
    nums = [int(m.group(1)) for i in keys if (m := re.fullmatch(prefix + r"(\d+)", i))]
    return max(nums, default=0) + 1


def next_goal_id(plan: Plan) -> str:
    return ids.make("goal", _next("GOAL-", plan.goals))


def next_project_id(plan: Plan) -> str:
    return ids.make("project", _next("PROJ-", plan.projects))


def next_deliverable_id(plan: Plan, project_id: str) -> str:
    project_id = ids.normalize(project_id)
    return f"{project_id}.{_next(re.escape(project_id) + r'[.]', plan.deliverables)}"


def _clean(value: str, what: str, forbid: str = "") -> str:
    v = (value or "").strip()
    if not v or "\n" in v or "\r" in v:
        raise util.BrainError(f"{what}: use uma linha só, não vazia", code=3)
    if forbid and forbid in v:
        raise util.BrainError(f"{what}: não pode conter {forbid!r} (o parser usa como separador)", code=3)
    return v


def _section_end(lines: list[str], start: int, stop_levels: tuple[str, ...]) -> int:
    """Índice logo depois da última linha com conteúdo da seção que começa em `start` (títulos dentro de comentário não contam)."""
    clean = _strip_comments(lines)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if clean[i].startswith(stop_levels):
            end = i
            break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def _insert(path: Path, new_id: str, anchor: str | None, block: list[str], stop: tuple[str, ...], rx: re.Pattern | None) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = _lines(text)
    if anchor is None:
        at = len(lines)
        while at and not lines[at - 1].strip():
            at -= 1
    else:
        clean = _strip_comments(lines)
        start = next((i for i, ln in enumerate(clean) if (m := rx.match(ln)) and ids.normalize(m.group(1)) == anchor), None)
        if start is None:
            raise util.BrainError(f"{anchor} não encontrado em {path.name}", code=3)
        at = _section_end(lines, start, stop)
    new = lines[:at] + block + lines[at:]
    out = "\n".join(new) + "\n"
    if not parse(out).has(new_id):                 # nunca deixa o arquivo num estado que o parser não entende
        raise util.BrainError(f"não consegui inserir {new_id} em {path.name} no formato do parser — arquivo intacto", code=5)
    util.atomic_write(path, out)


def add_goal(path: Path, title: str, horizon: str = "", why: str = "") -> str:
    plan = load(path)
    gid = next_goal_id(plan)
    block = ["", f"## {gid} — {_clean(title, 'título')}", "- status: ativo"]
    if horizon:
        block.append(f"- horizonte: {util.parse_date(horizon).isoformat()}")
    if why:
        block.append(f"- por quê: {_clean(why, 'por quê')}")
    _insert(path, gid, None, block, (), None)
    return gid


def add_project(path: Path, goal_id: str, title: str, owner: str = "", why: str = "") -> str:
    goal_id = ids.normalize(goal_id)
    plan = load(path)
    if goal_id not in plan.goals:
        raise util.BrainError(f"goal {goal_id} não existe em {path.name}", code=3)
    pid = next_project_id(plan)
    block = ["", f"### {pid} — {_clean(title, 'título')}", "- status: ativo"]
    if owner:
        block.append(f"- dono: {_clean(owner, 'dono')}")
    if why:
        block.append(f"- por quê: {_clean(why, 'por quê')}")
    _insert(path, pid, goal_id, block, ("## ",), GOAL_RE)
    return pid


def add_deliverable(path: Path, project_id: str, title: str, due: str = "", weight: int = 1) -> str:
    project_id = ids.normalize(project_id)
    plan = load(path)
    if project_id not in plan.projects:
        raise util.BrainError(f"projeto {project_id} não existe em {path.name}", code=3)
    if weight < 1:
        raise util.BrainError("peso: use um inteiro a partir de 1", code=3)
    did = next_deliverable_id(plan, project_id)
    line = f"- [ ] {did} {_clean(title, 'título', '·')}"
    if due:
        line += f" · prazo: {util.parse_date(due).isoformat()}"
    if weight != 1:
        line += f" · peso: {weight}"
    _insert(path, did, project_id, [line], ("## ", "### "), PROJ_RE)
    return did


# ── editar nós (goal, projeto, entregável) ───────────────────────────────────
NODE_STATUS = ["ativo", "congelado", "depois", "finalizado"]   # goal e projeto; fora de "ativo" o projeto sai da saúde normal
STATUS_ALIAS = {"fechado": "finalizado", "fechada": "finalizado",   # nome antigo: vale na entrada, nunca é escrito
                "ativa": "ativo", "congelada": "congelado"}


def norm_status(raw) -> str:
    """Status de goal/projeto no vocabulário novo: o goals.md do dono pode carregar `fechado`/`ativa` de antes."""
    f = util.fold(raw or "ativo")
    return STATUS_ALIAS.get(f, f)


_META_LABEL = {"status": "status", "horizonte": "horizonte", "por que": "por quê", "dono": "dono"}


def node_kind(plan: Plan, node: str) -> str | None:
    node = ids.normalize(node)
    return "goal" if node in plan.goals else "project" if node in plan.projects else \
        "deliverable" if node in plan.deliverables else None


_META_ALIASES = {"por que": {"por que", "porque"}}      # o parser lê `por quê` e `porque` como a mesma chave


def _set_meta(lines: list[str], start: int, key: str, value: str | None) -> None:
    """Troca (ou cria, ou remove quando `value` é vazio) a linha `- chave: valor` do título em `start`.
    As linhas de metadado ficam entre o título e o próximo título (de qualquer nível); sub-item recuado de um
    entregável não é metadado (como no parser). Com a chave repetida, o parser fica com a última: é ela que muda."""
    clean = _strip_comments(lines)
    end = next((i for i in range(start + 1, len(lines)) if clean[i].startswith(("## ", "### "))), len(lines))
    keys = _META_ALIASES.get(key, {key})
    last, hits, in_deliv = start, [], False
    for i in range(start + 1, end):
        if DELIV_RE.match(clean[i]):
            in_deliv = True
            continue
        if in_deliv and clean[i][:1].isspace():
            continue
        m = META_RE.match(clean[i])
        if m:
            last = i
            if util.fold(m.group(1)) in keys:
                hits.append(i)
    if value and hits:
        # lambda: o valor é texto do dono, não modelo de re.sub (`\n`, `\1` viravam quebra de linha / erro)
        lines[hits[-1]] = re.sub(r":\s*.+?\s*$", lambda _m: f": {value}", lines[hits[-1]], count=1)
    elif value:
        lines.insert(last + 1, f"- {_META_LABEL[key]}: {value}")
    else:
        for i in reversed(hits):
            del lines[i]


def _fold_eq(a: str | None, b: str | None) -> bool:
    return (a or "") == (b or "")


def _edit_landed(after: Plan, node: str, kind: str, changes: list[tuple[str, str, str]]) -> bool:
    """O arquivo reescrito, relido pelo parser, diz exatamente o que a edição prometeu (senão: arquivo intacto)."""
    for label, _old, new in changes:
        new = "" if new == "—" else new
        if kind == "deliverable":
            d = after.deliverables[node]
            got = {"título": d.title, "prazo": d.due.isoformat() if d.due else "", "peso": str(d.weight)}[label]
        else:
            obj = after.goals[node] if kind == "goal" else after.projects[node]
            got = obj.title if label == "título" else obj.why if label == "por quê" else \
                obj.meta.get({"status": "status", "horizonte": "horizonte", "dono": "dono"}[label])
        if (got or "") != new:
            return False
    return True


def edit_node(path: Path, node: str, **fields) -> list[tuple[str, str, str]]:
    """Edita goal/projeto/entregável no goals.md. `None` = não mexe; "" = remove (horizonte, por quê, dono, prazo).

    Campos: goal → title, status, horizon, why · projeto → title, status, owner · entregável → title, due, weight.
    Devolve [(campo, antes, depois)] só do que mudou; arquivo intacto se o resultado não passar pelo parser."""
    node = ids.normalize(node)
    text = path.read_text(encoding="utf-8")
    lines = _lines(text)
    plan = parse(text)
    kind = node_kind(plan, node)
    if kind is None:
        raise util.BrainError(f"{node} não existe em {path.name}", code=3)
    allowed = {"goal": {"title", "status", "horizon", "why"}, "project": {"title", "status", "owner"},
               "deliverable": {"title", "due", "weight"}}[kind]
    fields = {k: v for k, v in fields.items() if v is not None}
    bad = sorted(set(fields) - allowed)
    if bad:
        raise util.BrainError(f"{node} é {kind}: não tem {', '.join(bad)}", code=3)
    changes: list[tuple[str, str, str]] = []

    if kind == "deliverable":
        d = plan.deliverables[node]
        ln = lines[d.line_no - 1]
        m = DELIV_RE.match(ln)
        if m is None:
            raise util.BrainError(f"linha {d.line_no} de {node} não está no formato do parser — não alterei o arquivo", code=5)
        head, box, mid, _, rest = m.groups()
        title, segs = _raw_segments(rest)
        if "title" in fields:
            new = _clean(fields["title"], "título", "·")
            if new != title:
                changes.append(("título", title, new))
                title = new
        if "due" in fields:
            new = util.parse_date(fields["due"]).isoformat() if fields["due"] else ""
            if new != (d.due.isoformat() if d.due else ""):
                changes.append(("prazo", d.due.isoformat() if d.due else "—", new or "—"))
                _set_seg(segs, "prazo", new)
        if "weight" in fields:
            w = int(fields["weight"])
            if w < 1:
                raise util.BrainError("peso: use um inteiro a partir de 1", code=3)
            if w != d.weight:
                changes.append(("peso", str(d.weight), str(w)))
                _set_seg(segs, "peso", str(w) if w != 1 else None)
        if changes:
            lines[d.line_no - 1] = _deliv_line(head, box, mid, node, title, segs)
    else:
        node_obj = plan.goals[node] if kind == "goal" else plan.projects[node]
        clean = _strip_comments(lines)
        rx = GOAL_RE if kind == "goal" else PROJ_RE
        start = next(i for i, c in enumerate(clean) if (m := rx.match(c)) and ids.normalize(m.group(1)) == node)
        meta = {"status": ("status", node_obj.meta.get("status", "ativo")),
                "horizon": ("horizonte", node_obj.meta.get("horizonte", "")),
                "why": ("por que", node_obj.meta.get("por que") or node_obj.meta.get("porque") or ""),
                "owner": ("dono", node_obj.meta.get("dono", ""))}
        if "title" in fields:
            new = _clean(fields["title"], "título")
            if new != node_obj.title:
                changes.append(("título", node_obj.title, new))
                tm = rx.match(lines[start])
                if tm is None:
                    raise util.BrainError(f"título de {node} não está no formato do parser — não alterei o arquivo", code=5)
                # corta no início do título que o parser leu (`\S+` antes engolia "GOAL-1—Pré-" sem espaços)
                lines[start] = lines[start][:tm.start(2)] + new
        edits = []
        for f, value in fields.items():
            if f == "title":
                continue
            key, old = meta[f]
            if f == "status":
                value = norm_status(value)
                if value not in NODE_STATUS:
                    raise util.BrainError(f"status: use {', '.join(NODE_STATUS)}", code=3)
            elif f == "horizon":
                value = util.parse_date(value).isoformat() if value else ""
            else:
                value = _clean(value, f) if value else ""
            if not _fold_eq(value, old):
                changes.append((_META_LABEL[key], old or "—", value or "—"))
                edits.append((key, value))
        for key, value in edits:
            _set_meta(lines, start, key, value)
    if not changes:
        return []
    out = "\n".join(lines) + "\n"
    after = parse(out)
    if len(after.warnings) > len(plan.warnings) or node_kind(after, node) != kind or \
            list(after.goals) != list(plan.goals) or list(after.projects) != list(plan.projects) or \
            list(after.deliverables) != list(plan.deliverables) or not _edit_landed(after, node, kind, changes):
        raise util.BrainError(f"não consegui editar {node} em {path.name} no formato do parser — arquivo intacto", code=5)
    util.atomic_write(path, out)
    return changes
