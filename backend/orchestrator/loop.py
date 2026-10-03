"""The planner-agnostic scheduling loop.

snapshot -> planner.propose() -> validator.validate() -> (if approved)
simulator.execute() -> simulator.advance() -> publish events -> loop on
replan-trigger events, until Run.status becomes CLOSED.

This is the only module wired to both a Planner and the Simulator's execute().
The planner never receives a reference to the Simulator.
"""
from __future__ import annotations

from typing import List

from backend.constraints.validator import validate
from backend.domain.entities import Mission, ObservationTarget, Observatory, RunStatus
from backend.domain.events import Event, EventType
from backend.domain.value_objects import ActionProposal
from backend.missions.mission_loader import instantiate_run
from backend.planners.base import Planner
from backend.simulator.engine import Simulator
from backend.telemetry.event_log import InMemoryEventLog


def run_mission(
    mission: Mission,
    observatory: Observatory,
    targets: List[ObservationTarget],
    planner: Planner,
) -> InMemoryEventLog:
    run = instantiate_run(mission, planner.planner_id)
    simulator = Simulator.start(mission, observatory, targets, run)
    event_log = InMemoryEventLog()

    def emit(event_type: EventType, payload: dict, source: str) -> Event:
        event = Event(
            event_id=run.next_event_id(),
            run_id=run.run_id,
            sim_time=run.sim_time,
            type=event_type,
            payload=payload,
            source=source,
        )
        event_log.append(event)
        return event

    # Dispatches the precomputed world timeline up to the first invocation
    # point — ObservatoryOpened itself is what triggers the first PlannerInvoked.
    event_log.append_all(simulator.advance())

    while run.status == RunStatus.RUNNING:
        snapshot = simulator.snapshot()
        emit(EventType.PlannerInvoked, {}, source="orchestrator")

        proposal: ActionProposal = planner.propose(snapshot)
        proposal_id = run.next_proposal_id()
        emit(
            EventType.ActionProposed,
            {
                "proposal_id": proposal_id,
                "action": proposal.action.value,
                "request_id": proposal.request_id,
                "summary": proposal.rationale.summary,
                "factors": dict(proposal.rationale.factors),
            },
            source=f"planner:{planner.planner_id}",
        )

        result = validate(proposal, snapshot)
        if result.approved:
            emit(
                EventType.ActionApproved,
                {"proposal_id": proposal_id, "reason": result.reason},
                source="validator",
            )
            event_log.append_all(simulator.execute(proposal, proposal_id))
        else:
            emit(
                EventType.ActionRejected,
                {
                    "proposal_id": proposal_id,
                    "reason": result.reason,
                    "violated_constraints": list(result.violated_constraints),
                },
                source="validator",
            )
            # No retries, ever — a rejected proposal simply changes nothing;
            # the next advance() below resumes at the next replan trigger.

        emit(
            EventType.MissionReplanned,
            {"proposal_id": proposal_id, "approved": result.approved},
            source="orchestrator",
        )

        advanced = simulator.advance()
        event_log.append_all(advanced)
        if not advanced and run.status == RunStatus.RUNNING:
            # Defensive only: the queue always contains ObservatoryClosed at
            # night_window.end, so this should be unreachable.
            break

    return event_log
