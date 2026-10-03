"""Proposal validation against the constraint checks."""
from backend.constraints.validator import validate
from backend.domain.entities import (
    InstrumentState,
    Mission,
    ObservationTarget,
    RequestDefinition,
    TelescopeState,
    WeatherCondition,
)
from backend.domain.value_objects import Action, ActionProposal, Rationale
from backend.missions.mission_loader import instantiate_run
from backend.simulator.engine import Simulator
from tests.support import OBSERVATORY, TARGET, build_simple_mission


def make_snapshot(mission=None, observatory=OBSERVATORY, targets=None):
    mission = mission or build_simple_mission()
    targets = targets if targets is not None else [TARGET]
    run = instantiate_run(mission, planner_id="baseline")
    simulator = Simulator.start(mission, observatory, targets, run)
    simulator.advance()  # dispatch ObservatoryOpened so sim_time/state settle
    return simulator, run, simulator.snapshot()


def observe(request_id):
    return ActionProposal(
        action=Action.OBSERVE,
        request_id=request_id,
        planner_id="baseline",
        proposed_at=0,
        rationale=Rationale(summary="test"),
    )


def wait():
    return ActionProposal(action=Action.WAIT, planner_id="baseline", proposed_at=0, rationale=Rationale())


def test_wait_is_always_approved():
    _, _, snapshot = make_snapshot()
    result = validate(wait(), snapshot)
    assert result.approved
    assert result.violated_constraints == ()


def test_valid_observe_proposal_is_approved():
    _, run, snapshot = make_snapshot()
    request = next(iter(run.observation_requests.values()))
    result = validate(observe(request.id), snapshot)
    assert result.approved, result.reason
    assert result.violated_constraints == ()


def test_unknown_request_id_is_rejected():
    _, _, snapshot = make_snapshot()
    result = validate(observe("does-not-exist"), snapshot)
    assert not result.approved
    assert "VALID_REQUEST" in result.violated_constraints


def test_target_not_visible_is_rejected():
    # dec = -60 seen from lat = 40: max altitude = 90 - |40 - (-60)| = -10 < 30.
    far_south = ObservationTarget(id="t-south", name="Far South", ra=180.0, dec=-60.0)
    definition = RequestDefinition(id="d-south", target_id="t-south", priority=5, required_exposure_duration=30, deadline=200)
    mission = Mission(
        id="m-south",
        name="Never visible mission",
        observatory_id=OBSERVATORY.id,
        request_definitions=(definition,),
        weather_script=((0, WeatherCondition.CLEAR),),
        night_window=(0, 400),
        starting_local_sidereal_time=170.0,
    )
    _, run, snapshot = make_snapshot(mission=mission, targets=[far_south])
    request = next(iter(run.observation_requests.values()))
    result = validate(observe(request.id), snapshot)
    assert not result.approved
    assert "VISIBILITY" in result.violated_constraints


def test_telescope_busy_is_rejected():
    _, run, snapshot_before = make_snapshot()
    request = next(iter(run.observation_requests.values()))
    run.telescope.state = TelescopeState.SLEWING
    # Rebuild the snapshot after mutating runtime state, same way the
    # orchestrator would take a fresh snapshot before each proposal.
    snapshot = snapshot_before.__class__(
        sim_time=snapshot_before.sim_time,
        telescope_state=run.telescope.state,
        instrument_state=snapshot_before.instrument_state,
        weather=snapshot_before.weather,
        pending_requests=snapshot_before.pending_requests,
        recent_events=snapshot_before.recent_events,
    )
    result = validate(observe(request.id), snapshot)
    assert not result.approved
    assert "TELESCOPE_AVAILABLE" in result.violated_constraints


def test_weather_blocks_observation():
    _, run, snapshot_before = make_snapshot()
    request = next(iter(run.observation_requests.values()))
    snapshot = snapshot_before.__class__(
        sim_time=snapshot_before.sim_time,
        telescope_state=snapshot_before.telescope_state,
        instrument_state=snapshot_before.instrument_state,
        weather=WeatherCondition.CLOUDY,
        pending_requests=snapshot_before.pending_requests,
        recent_events=snapshot_before.recent_events,
    )
    result = validate(observe(request.id), snapshot)
    assert not result.approved
    assert "WEATHER_PERMITS" in result.violated_constraints


def test_deadline_infeasible_is_rejected():
    tight_definition = RequestDefinition(id="d-tight", target_id="t1", priority=5, required_exposure_duration=30, deadline=10)
    mission = build_simple_mission(request_definitions=(tight_definition,))
    _, run, snapshot = make_snapshot(mission=mission)
    request = next(iter(run.observation_requests.values()))
    # sim_time (0) + duration (30) = 30 > deadline (10).
    result = validate(observe(request.id), snapshot)
    assert not result.approved
    assert "DEADLINE_FEASIBLE" in result.violated_constraints
