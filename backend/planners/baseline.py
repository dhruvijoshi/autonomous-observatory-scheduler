"""The deterministic baseline planner.

Selects the highest-priority pending request that is visible for its full
exposure, breaking ties by earliest deadline. Returns WAIT when no request
qualifies.
"""
from __future__ import annotations

from backend.domain.astronomy import is_visible_for
from backend.domain.value_objects import Action, ActionProposal, Rationale, WorldSnapshot


class BaselinePlanner:
    planner_id = "baseline"

    def propose(self, snapshot: WorldSnapshot) -> ActionProposal:
        candidates = [
            view
            for view in snapshot.pending_requests
            if is_visible_for(list(view.windows), snapshot.sim_time, view.definition.required_exposure_duration)
        ]

        if not candidates:
            return ActionProposal(
                action=Action.WAIT,
                planner_id=self.planner_id,
                proposed_at=snapshot.sim_time,
                rationale=Rationale(summary="no visible, feasible pending request"),
            )

        # priority desc, deadline asc, then definition id asc — the last term
        # exists purely to keep the choice deterministic under exact ties.
        best = min(candidates, key=lambda v: (-v.definition.priority, v.definition.deadline, v.definition.id))

        return ActionProposal(
            action=Action.OBSERVE,
            request_id=best.request.id,
            planner_id=self.planner_id,
            proposed_at=snapshot.sim_time,
            rationale=Rationale(
                factors={
                    "priority": float(best.definition.priority),
                    "time_to_deadline": float(best.definition.deadline - snapshot.sim_time),
                },
                summary=f"highest-priority visible, feasible request: {best.definition.id}",
            ),
        )
