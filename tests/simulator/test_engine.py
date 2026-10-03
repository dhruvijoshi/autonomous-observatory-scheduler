"""Telescope state transitions and the observation lifecycle."""
from backend.domain.entities import (
    InstrumentState,
    ObservationOutcome,
    RequestStatus,
    RunStatus,
    TelescopeState,
)
from backend.domain.events import EventType
from backend.domain.value_objects import Action, ActionProposal, Rationale
from backend.missions.mission_loader import instantiate_run
from backend.simulator.engine import Simulator
from tests.support import OBSERVATORY, TARGET, build_simple_mission


def start_simulator():
    mission = build_simple_mission()
    run = instantiate_run(mission, planner_id="baseline")
    simulator = Simulator.start(mission, OBSERVATORY, [TARGET], run)
    return simulator, run


def observe_proposal(run):
    request = next(iter(run.observation_requests.values()))
    return ActionProposal(
        action=Action.OBSERVE,
        request_id=request.id,
        planner_id="baseline",
        proposed_at=run.sim_time,
        rationale=Rationale(summary="test"),
    ), request


def test_telescope_state_transitions_idle_slewing_observing_idle():
    simulator, run = start_simulator()
    simulator.advance()  # dispatch ObservatoryOpened
    assert run.telescope.state == TelescopeState.IDLE

    proposal, request = observe_proposal(run)
    events = simulator.execute(proposal, proposal_id="p1")
    assert run.telescope.state == TelescopeState.SLEWING
    assert [e.type for e in events] == [EventType.TelescopeSlewStarted]

    advanced = simulator.advance()
    # Slew is instantaneous here (no prior pointing), so the same advance()
    # call carries the telescope through SLEWING -> OBSERVING and on to the
    # ObservationCompleted replan trigger.
    assert run.telescope.state == TelescopeState.IDLE  # after ObservationCompleted
    types = [e.type for e in advanced]
    assert EventType.TelescopeSlewCompleted in types
    assert EventType.ObservationStarted in types
    assert EventType.ObservationCompleted in types


def test_telescope_parks_at_observatory_closed():
    simulator, run = start_simulator()
    simulator.advance()
    while run.status == RunStatus.RUNNING:
        simulator.advance()
        if run.status == RunStatus.RUNNING:
            # No more proposals will be made in this raw-engine test (nothing
            # drives the orchestrator loop here) — just keep draining the
            # precomputed world timeline to reach ObservatoryClosed.
            continue
    assert run.status == RunStatus.CLOSED
    assert run.telescope.state == TelescopeState.PARKED


def test_observation_lifecycle_open_then_finalized_success():
    simulator, run = start_simulator()
    simulator.advance()
    proposal, request = observe_proposal(run)
    simulator.execute(proposal, proposal_id="p1")
    assert request.status == RequestStatus.SCHEDULED

    simulator.advance()  # slew completes -> observation starts -> completes
    assert len(run.observations) == 1
    observation = next(iter(run.observations.values()))
    assert observation.outcome == ObservationOutcome.SUCCESS
    assert observation.actual_duration == observation.planned_duration
    assert not observation.is_open()
    assert request.status == RequestStatus.COMPLETED
    assert run.instrument.state == InstrumentState.IDLE
