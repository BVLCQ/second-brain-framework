"""PLANNING/goals.md — a árvore curada (goal → projeto → entregável), em Markdown estrito.

    ## G1 — Nome do goal
    - status: ativo
    - horizonte: 2027-06-30
    - por quê: o que isto destrava

    ### P1 — Nome do projeto
    - status: ativo
    - dono: ana
    - [ ] P1.1 Entregável · prazo: 2026-10-30 · peso: 2
    - [x] P1.2 Entregável · prazo: 2026-11-15 · feito: 2026-11-10
    - [-] P1.3 Entregável cancelado

Progresso de projeto/goal = peso dos entregáveis feitos / peso dos não cancelados.
O agente só muda a ESTRUTURA com aprovação (gate); o estado factual (checkbox,
data de conclusão) muda com log — via `brain plan deliverable`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import util

GOAL_RE = re.compile(r"^##\s+(G\d+)\s*[—–-]\s*(.+?)\s*$")
PROJ_RE = re.compile(r"^###\s+(P\d+)\s*[—–-]\s*(.+?)\s*$")
DELIV_RE = re.compile(r"^(\s*-\s+\[)( |x|X|-)(\]\s+)(P\d+\.\d+)\s+(.+?)\s*$")
META_RE = re.compile(r"^\s*-\s+([^\[\]:]{2,24}):\s*(.+?)\s*$")
H2_RE = re.compile(r"^##\s+")

ACTIVE = {"ativo", "ativa"}


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
        return util.fold(self.meta.get("status", "ativo"))

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
        return util.fold(self.meta.get("status", "ativo"))

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
        return node in self.goals or node in self.projects or node in self.deliverables

    def goal_of(self, node: str | None) -> str | None:
        if not node:
            return None
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
        if node in self.projects:
            return node
        if node in self.deliverables:
            return self.deliverables[node].project_id
        return None

    def title(self, node: str) -> str:
        for coll in (self.goals, self.projects, self.deliverables):
            if node in coll:
                return coll[node].title
        return node

    def deliverables_of(self, node: str) -> list[Deliverable]:
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
        if "<!--" in ln and "-->" not in ln.split("<!--", 1)[1]:
            in_html = True
            out.append(ln.split("<!--", 1)[0])
            continue
        out.append(re.sub(r"<!--.*?-->", "", ln))
    return out


def parse(text: str) -> Plan:
    plan = Plan()
    goal: Goal | None = None
    proj: Project | None = None
    for i, ln in enumerate(_strip_comments(text.splitlines()), start=1):
        m = GOAL_RE.match(ln)
        if m:
            gid, title = m.groups()
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
            pid, title = m.groups()
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
            box, did, rest = m.group(2), m.group(4), m.group(5)
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


def set_deliverable(path: Path, did: str, status: str, when: date | None) -> bool:
    """Atualiza o checkbox (estado factual) de um entregável. Retorna True se mudou."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    plan = parse("".join(lines))
    d = plan.deliverables.get(did)
    if d is None:
        raise util.BrainError(f"entregável {did} não encontrado em {path.name}")
    ln = lines[d.line_no - 1]
    eol = "\n" if ln.endswith("\n") else ""
    m = DELIV_RE.match(ln.rstrip("\n"))
    if m is None:
        raise util.BrainError(f"linha {d.line_no} de {did} não está no formato do parser — não alterei o arquivo")
    head, _, mid, _, rest = m.groups()
    title, seg = _parse_segments(rest)
    seg.pop("estado", None)
    seg.pop("feito", None)
    box = " "
    if status == "feito":
        box = "x"
        seg["feito"] = (when or util.today()).isoformat()
    elif status == "cancelado":
        box = "-"
    elif status == "em-andamento":
        seg["estado"] = "em-andamento"
    order = ["prazo", "peso", "estado", "feito"]
    keys = sorted(seg, key=lambda k: order.index(k) if k in order else len(order))
    tail = "".join(f" · {k}: {seg[k]}" if seg[k] != "sim" else f" · {k}" for k in keys)
    new = f"{head}{box}{mid}{did} {title}{tail}{eol}"
    if new == ln:
        return False
    lines[d.line_no - 1] = new
    util.atomic_write(path, "".join(lines))
    return True


# ── criar nós (goal, projeto, entregável) ────────────────────────────────────
def _next(prefix: str, ids) -> int:
    nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(prefix + r"(\d+)", i))]
    return max(nums, default=0) + 1


def next_goal_id(plan: Plan) -> str:
    return f"G{_next('G', plan.goals)}"


def next_project_id(plan: Plan) -> str:
    return f"P{_next('P', plan.projects)}"


def next_deliverable_id(plan: Plan, project_id: str) -> str:
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
    lines = text.splitlines()
    if anchor is None:
        at = len(lines)
        while at and not lines[at - 1].strip():
            at -= 1
    else:
        clean = _strip_comments(lines)
        start = next((i for i, ln in enumerate(clean) if (m := rx.match(ln)) and m.group(1) == anchor), None)
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


def add_project(path: Path, goal_id: str, title: str, owner: str = "") -> str:
    plan = load(path)
    if goal_id not in plan.goals:
        raise util.BrainError(f"goal {goal_id} não existe em {path.name}", code=3)
    pid = next_project_id(plan)
    block = ["", f"### {pid} — {_clean(title, 'título')}", "- status: ativo"]
    if owner:
        block.append(f"- dono: {_clean(owner, 'dono')}")
    _insert(path, pid, goal_id, block, ("## ",), GOAL_RE)
    return pid


def add_deliverable(path: Path, project_id: str, title: str, due: str = "", weight: int = 1) -> str:
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
