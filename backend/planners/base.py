"""The Planner protocol that every scheduling strategy implements.

Planners must be stateless: propose() depends only on the snapshot it is passed,
never on hidden memory. This keeps a Run reproducible from {Mission, planner_id}.
"""
from __future__ import annotations

from typing import Protocol

from backend.domain.value_objects import ActionProposal, WorldSnapshot


class Planner(Protocol):
    planner_id: str

    def propose(self, snapshot: WorldSnapshot) -> ActionProposal:
        ...
