"""Propostas que o dono já resolveu por fora do painel.

O agente propõe fechar/atualizar uma ação; o dono, enquanto isso, fecha a ação num editor, no chat ou na TUI.
A proposta ficaria aberta para sempre. Aqui se detecta o conflito — função pura sobre o estado — e
`Brain.sweep_proposals()` grava `proposal.superseded` (by system) em seguida, com o desfecho que o gesto do
dono implica (`outcome`): não é a fala dele, por isso não vira `proposal.accepted`/`rejected` (OWNER_ONLY).

  fechar-acao     ação fechada → aceita · descartada → rejeitada · dono mexeu e deixou aberta → rejeitada
  atualizar-acao  dono mexeu → aceita · ação fechada/descartada antes → rejeitada
"""
from __future__ import annotations

from .state import State

ACTION_KINDS = {"fechar-acao", "atualizar-acao"}
OWNER_TOUCH = {"action.updated", "action.reopened"}


def conflicts(st: State) -> list[tuple[str, str, str]]:
    """[(id da proposta, motivo, desfecho)] das propostas abertas que o que o dono já fez resolve."""
    out = []
    for p in st.proposals.values():
        if p.status != "aberta" or p.kind not in ACTION_KINDS:
            continue
        a = st.actions.get(p.target)
        if a is None:
            continue
        if a.status in ("fechada", "descartada"):
            when = f" em {a.closed.isoformat()}" if a.closed else ""
            done = p.kind == "fechar-acao" and a.status == "fechada"
            out.append((p.id, f"{a.id} já está {a.status}{when}", "aceita" if done else "rejeitada"))
            continue
        touched = [e for e in a.history
                   if e.get("by") == "owner" and e.get("type") in OWNER_TOUCH and e.get("seq", 0) > p.seq]
        if touched:
            outcome = "aceita" if p.kind == "atualizar-acao" else "rejeitada"
            out.append((p.id, f"o dono já mexeu em {a.id} depois da proposta (seq {touched[-1]['seq']})", outcome))
    return out
