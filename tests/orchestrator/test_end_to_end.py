"""End-to-end deterministic mission run.
The same Mission and baseline planner run twice
must produce identical event logs.
"""
import dataclasses

from backend.domain.entities import ObservationOutcome, RequestStatus, RunStatus, TelescopeState
from backend.domain.events import EventType
from backend.orchestrator.loop import run_mission
from backend.planners.baseline import BaselinePlanner
from tests.support import OBSERVATORY, TARGET, build_simple_mission


def run_once():
    mission = build_simple_mission()
    planner = BaselinePlanner()
    event_log = run_mission(mission, OBSERVATORY, [TARGET], planner)
    return mission, event_log


def test_end_to_end_deterministic_mission_completes_the_observation():
    mission, event_log = run_once()
    events = event_log.all()

    # The full pipeline fired, in order: open -> planner invoked -> proposed
    # -> approved -> slew -> observation -> replanned -> ... -> closed.
    types_in_order = [e.type for e in events]
    assert types_in_order[0] == EventType.ObservatoryOpened
    assert types_in_order[-1] == EventType.ObservatoryClosed
    assert EventType.PlannerInvoked in types_in_order
    assert EventType.ActionProposed in types_in_order
    assert EventType.ActionApproved in types_in_order
    assert EventType.TelescopeSlewStarted in types_in_order
    assert EventType.TelescopeSlewCompleted in types_in_order
    assert EventType.ObservationStarted in types_in_order
    assert EventType.ObservationCompleted in types_in_order
    assert EventType.MissionReplanned in types_in_order

    # Every ActionProposed/Approved/Rejected references a real proposal_id.
    for event in events:
        if event.type in (EventType.ActionProposed, EventType.ActionApproved, EventType.ActionRejected):
            assert event.payload.get("proposal_id")

    # Exactly one observation attempt, and it succeeded.
    completed = [e for e in events if e.type == EventType.ObservationCompleted]
    assert len(completed) == 1

    # Sim time is monotonically non-decreasing across the whole log.
    sim_times = [e.sim_time for e in events]
    assert sim_times == sorted(sim_times)


def test_end_to_end_final_domain_state_is_consistent():
    # Re-run via the orchestrator, then inspect final Run state directly
    # (run_mission doesn't return the Run, so re-instantiate the same way it
    # does internally, mirroring the public entry point's construction path).
    from backend.missions.mission_loader import instantiate_run
    from backend.simulator.engine import Simulator
    from backend.constraints.validator import validate
    from backend.planners.baseline import BaselinePlanner

    mission = build_simple_mission()
    planner = BaselinePlanner()
    run = instantiate_run(mission, planner.planner_id)
    simulator = Simulator.start(mission, OBSERVATORY, [TARGET], run)

    simulator.advance()
    while run.status == RunStatus.RUNNING:
        snapshot = simulator.snapshot()
        proposal = planner.propose(snapshot)
        result = validate(proposal, snapshot)
        if result.approved:
            simulator.execute(proposal, proposal_id="test-proposal")
        simulator.advance()

    assert run.status == RunStatus.CLOSED
    assert run.telescope.state == TelescopeState.PARKED

    request = next(iter(run.observation_requests.values()))
    assert request.status == RequestStatus.COMPLETED

    assert len(run.observations) == 1
    observation = next(iter(run.observations.values()))
    assert observation.outcome == ObservationOutcome.SUCCESS


def test_reproducibility_same_mission_and_baseline_planner_yields_identical_log():
    _, log_a = run_once()
    _, log_b = run_once()

    events_a = log_a.all()
    events_b = log_b.all()

    assert len(events_a) == len(events_b)
    for a, b in zip(events_a, events_b):
        assert a.sim_time == b.sim_time
        assert a.type == b.type
        assert a.source == b.source
        # event_id/run_id are deterministic (counter-based, not random), and
        # both runs use the same {mission, planner_id} pairing, so they must
        # match exactly too — not just structurally-equivalent payloads.
        assert a.event_id == b.event_id
        assert a.run_id == b.run_id
        assert a.payload == b.payload


def test_reproducibility_holds_across_a_larger_multi_request_mission():
    from backend.domain.entities import Mission, ObservationTarget, RequestDefinition, WeatherCondition

    targets = [
        ObservationTarget(id="t1", name="Star A", ra=180.0, dec=0.0),
        ObservationTarget(id="t2", name="Star B", ra=190.0, dec=10.0),
        ObservationTarget(id="t3", name="Star C", ra=170.0, dec=-5.0),
    ]
    definitions = (
        RequestDefinition(id="d1", target_id="t1", priority=5, required_exposure_duration=20, deadline=150),
        RequestDefinition(id="d2", target_id="t2", priority=8, required_exposure_duration=15, deadline=100),
        RequestDefinition(id="d3", target_id="t3", priority=3, required_exposure_duration=25, deadline=350),
    )
    mission = Mission(
        id="m-multi",
        name="Multi-request mission",
        observatory_id=OBSERVATORY.id,
        request_definitions=definitions,
        weather_script=((0, WeatherCondition.CLEAR), (80, WeatherCondition.CLOUDY), (150, WeatherCondition.CLEAR)),
        night_window=(0, 400),
        starting_local_sidereal_time=170.0,
    )

    def run_it():
        return run_mission(mission, OBSERVATORY, targets, BaselinePlanner())

    log_a = run_it()
    log_b = run_it()

    events_a, events_b = log_a.all(), log_b.all()
    assert len(events_a) == len(events_b)
    assert all(a == b for a, b in zip(events_a, events_b))
    assert log_a.all() != []
