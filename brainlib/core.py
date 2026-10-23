"""Brain: fachada única sobre instância + PLANNING + livro-razão.

Toda escrita no ledger passa por `Brain.record()`: normaliza, atribui IDs,
valida contra o estado corrente (com referências cruzadas) e apensa em lote
atômico — todos os eventos do lote ou nenhum.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from . import config, planning, proposals, schema, util
from . import state as state_mod

try:
    import fcntl
except ImportError:  # pragma: no cover — Windows não é alvo (cron/launchd)
    fcntl = None

LEDGER_REL = Path("PROCESSED") / "_ledger" / "events.jsonl"
FACT_TYPES = {"action.opened", "action.closed", "decision.made", "delivery.recorded",
              "artifact.added", "deliverable.updated", "proposal.opened", "process.added",
              "opportunity.added", "opportunity.evidence", "question.asked"}
# No noturno (BRAIN_NIGHTLY=1) não há dono presente: nenhuma aprovação, envio ou publicação.
# Gates estruturais também: mudar a árvore, aceitar/rejeitar proposta, promover oportunidade, migrar IDs.
NIGHT_FORBIDDEN = {"question.answered", "message.approved", "message.sent", "share.approved", "share.published", "focus.approved",
                   "plan.changed", "proposal.accepted", "proposal.rejected", "opportunity.promoted", "ids.migrated"}
FIELD_ORDER = ["seq", "ts", "type", "id", "date", "actor", "by", "prov", "source", "data"]


class Brain:
    def __init__(self, inst: config.Instance | None = None):
        self.inst = inst or config.load()
        self.ledger_path = self.inst.vault / LEDGER_REL
        self._state: state_mod.State | None = None
        self._plan: planning.Plan | None = None

    # ── leitura ────────────────────────────────────────────────────────────
    def read_events(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        out = []
        # só "\n" separa eventos: `splitlines` também quebra em U+2028, \x85, \x0c… que o JSON (ensure_ascii=False)
        # grava crus dentro das strings — um título vindo de e-mail partiria a linha e corromperia o ledger.
        for n, line in enumerate(self.ledger_path.read_text(encoding="utf-8").split("\n"), start=1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise util.BrainError(f"ledger corrompido na linha {n}: {e}", code=5) from e
        return out

    @property
    def state(self) -> state_mod.State:
        if self._state is None:
            self._state = state_mod.build(self.read_events())
        return self._state

    @property
    def plan(self) -> planning.Plan:
        if self._plan is None:
            self._plan = planning.load(self.inst.planning_file)
        return self._plan

    def reload(self) -> None:
        self._state, self._plan = None, None

    @property
    def owner(self) -> str:
        return self.inst.owner_id

    # ── escrita ────────────────────────────────────────────────────────────
    @contextlib.contextmanager
    def _lock(self):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.ledger_path.with_suffix(".lock")
        with open(lock_path, "w") as fh:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _normalize(self, item: dict, working: state_mod.State) -> dict:
        if not isinstance(item, dict):
            raise util.BrainError(f"evento deve ser objeto JSON, recebido {type(item).__name__}", code=4)
        ev = {k: v for k, v in item.items() if v not in (None, "")}
        t = ev.get("type")
        spec = schema.TYPES.get(t)
        if spec is None:
            raise util.BrainError(f"tipo de evento desconhecido: {t!r}", code=4)
        if not isinstance(ev.get("data", {}), dict):
            raise util.BrainError(f"{t}: data deve ser objeto JSON", code=4)
        ev.setdefault("by", "agent")
        mode = (ev.get("data") or {}).get("mode")
        if os.environ.get("BRAIN_NIGHTLY") == "1" and (ev["by"] == "owner" or t in NIGHT_FORBIDDEN
                                                       or (t == "focus.applied" and mode == "google")):
            raise util.BrainError(f"{t}: proibido no noturno — exige o dono presente (aprovação/envio/publicação)",
                                  code=4)
        if ev["by"] == "owner":
            ev.setdefault("prov", "declarado")
            ev.setdefault("source", "chat")
            ev.setdefault("actor", self.owner if self.owner in working.people else None)
        elif ev["by"] == "system":
            ev.setdefault("prov", "sistema")
        if not ev.get("prov"):
            raise util.BrainError(f"{t}: proveniência obrigatória para fatos do agente "
                                  f"(--prov doc|observado|declarado|sem-fonte)", code=4)
        if ev["by"] == "agent" and t in FACT_TYPES and not ev.get("source"):
            raise util.BrainError(f"{t}: --source obrigatório (artefato/RAW de onde veio)", code=4)
        ev["date"] = (util.parse_date(ev.get("date")) or util.today()).isoformat()
        data = {k: v for k, v in (ev.get("data") or {}).items() if v not in (None, "")}
        ev["data"] = data
        schema.normalize_event(ev)              # entrada com nome antigo (A-0146, G1, P3.2) é gravada no formato novo

        if spec.get("prefix"):
            ev["id"] = working.next_id(spec["prefix"])
        elif t == "person.added":
            base = util.slugify(ev.get("id") or data.get("name", ""), 32)
            pid, n = base, 2
            while pid in working.people:
                pid, n = f"{base}-{n}", n + 1
            ev["id"] = pid
        elif t == "area.added":
            ev["id"] = util.slugify(ev.get("id") or data.get("name", ""), 32)
        elif t in ("doc.linked", "doc.unlinked"):
            ev["id"] = data.get("target")
        elif t == "artifact.added":
            ev["id"] = self._vault_rel(ev.get("id") or data.get("path", ""))
            data.pop("path", None)
            if data.get("raw"):
                data["raw"] = self._vault_rel(data["raw"])
        if spec["entity"] and spec["entity"] != "run" and not ev.get("id") and t != "plan.changed":
            raise util.BrainError(f"{t}: id obrigatório", code=4)
        return ev

    def _vault_rel(self, p: str) -> str:
        if not p or not isinstance(p, str):
            raise util.BrainError("caminho obrigatório", code=4)
        path = Path(p)
        rel = util.relpath(path, self.inst.vault) if path.is_absolute() else (p[len("vault/"):] if p.startswith("vault/") else p)
        # o id do artefato vira caminho de leitura (busca, MCP): nada fora do vault
        norm = os.path.normpath(rel)
        if os.path.isabs(norm) or norm == ".." or norm.startswith(".." + os.sep):
            raise util.BrainError(f"caminho fora do vault: {p!r}", code=4)
        return rel

    def _append_one(self, item: dict, working: state_mod.State, plan: planning.Plan, new: list[dict]) -> None:
        ev = self._normalize(item, working)
        schema.validate(ev, working, plan)
        ev["seq"] = working.max_seq() + 1
        ev["ts"] = util.iso_now()
        ordered = {k: ev[k] for k in FIELD_ORDER
                   if k == "data" or ev.get(k) not in (None, "")}
        state_mod.apply(working, ordered)
        new.append(ordered)

    def record(self, items: list[dict], sweep: bool = True) -> list[dict]:
        """Grava o lote; com `sweep`, fecha junto as propostas que o lote tornou obsoletas."""
        if not items:
            return []
        with self._lock():
            working = state_mod.build(self.read_events())
            plan = planning.load(self.inst.planning_file)
            new: list[dict] = []
            for item in items:
                self._append_one(item, working, plan, new)
            if sweep:
                self._sweep_proposals(working, plan, new)
            self._flush(new)
        self._state = working
        self._plan = plan
        return new

    def sweep_proposals(self) -> list[dict]:
        """Fecha (`proposal.superseded`) as propostas abertas que o dono já resolveu por fora do painel."""
        with self._lock():
            working = state_mod.build(self.read_events())
            plan = planning.load(self.inst.planning_file)
            new: list[dict] = []
            self._sweep_proposals(working, plan, new)
            self._flush(new)
        self._state = working
        self._plan = plan
        return new

    def _sweep_proposals(self, working: state_mod.State, plan: planning.Plan, new: list[dict]) -> None:
        for pid, reason in proposals.conflicts(working):
            self._append_one({"type": "proposal.superseded", "id": pid, "by": "system",
                              "data": {"reason": reason}}, working, plan, new)

    def _flush(self, new: list[dict]) -> None:
        """Apensa o lote num único write (O_APPEND) + fsync: o lote inteiro ou nada, sem linha partida no meio."""
        if not new:
            return
        payload = "".join(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n" for ev in new).encode("utf-8")
        fd = os.open(self.ledger_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            size = os.fstat(fd).st_size
            if size:                                  # última linha sem \n (editada à mão): não colar o evento novo nela
                with open(self.ledger_path, "rb") as rh:
                    rh.seek(size - 1)
                    if rh.read(1) != b"\n":
                        payload = b"\n" + payload
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)

    def record_one(self, item: dict) -> dict:
        return self.record([item])[0]

    # ── auditoria ──────────────────────────────────────────────────────────
    def validate_all(self) -> list[str]:
        """Revalida o ledger inteiro em ordem. Retorna problemas (vazio = saudável)."""
        return self.validate_events(self.read_events(), self.plan)

    def validate_events(self, events: list[dict], plan) -> list[str]:
        """Revalida uma lista de eventos (o ledger, ou o que a migração vai gravar) contra um PLANNING."""
        problems: list[str] = []
        working = state_mod.State()
        last_seq = 0
        for ev in events:
            schema.normalize_event(ev)
            seq = ev.get("seq", 0)
            if seq <= last_seq:
                problems.append(f"seq {seq}: fora de ordem (anterior {last_seq})")
            last_seq = seq
            probe = dict(ev)
            try:
                if schema.TYPES.get(ev.get("type"), {}).get("new"):
                    coll = working.collection(schema.TYPES[ev["type"]]["entity"])
                    if ev.get("id") in coll:
                        raise util.BrainError(f"id duplicado {ev.get('id')}")
                schema.validate(probe, working, plan)
            except util.BrainError as e:
                problems.append(f"seq {seq} ({ev.get('type')} {ev.get('id', '')}): {e}")
            except KeyError as e:
                problems.append(f"seq {seq}: campo ausente {e}")
            try:
                state_mod.apply(working, ev)
            except KeyError as e:
                problems.append(f"seq {seq}: referência quebrada {e}")
        return problems
