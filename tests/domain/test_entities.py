"""Core domain construction."""
import dataclasses

import pytest

from backend.domain.entities import (
    Instrument,
    InstrumentState,
    Mission,
    Observation,
    ObservationOutcome,
    ObservationRequest,
    ObservationTarget,
    Observatory,
    RequestDefinition,
    RequestStatus,
    Run,
    RunStatus,
    Telescope,
    TelescopeState,
    WeatherCondition,
)


def test_observatory_and_target_construction():
    observatory = Observatory(
        id="obs1",
        name="Test Site",
        latitude=40.0,
        longitude=-105.0,
        elevation=1655.0,
        default_minimum_altitude=30.0,
        telescope_slew_rate_deg_per_sec=2.0,
    )
    target = ObservationTarget(id="m31", name="Andromeda", ra=10.68, dec=41.27)
    assert target.effective_minimum_altitude(observatory) == 30.0

    target_with_override = ObservationTarget(id="m42", name="Orion", ra=83.8, dec=-5.4, minimum_altitude_override=45.0)
    assert target_with_override.effective_minimum_altitude(observatory) == 45.0


def test_mission_is_immutable():
    definition = RequestDefinition(id="d1", target_id="m31", priority=8, required_exposure_duration=30, deadline=300)
    mission = Mission(
        id="mission1",
        name="Test Mission",
        observatory_id="obs1",
        request_definitions=(definition,),
        weather_script=((0, WeatherCondition.CLEAR),),
        night_window=(0, 480),
        starting_local_sidereal_time=120.0,
    )
    assert mission.request_definitions == (definition,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mission.name = "renamed"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.priority = 1  # type: ignore[misc]


def test_run_scoped_runtime_state_starts_fresh():
    run = Run(run_id="run1", mission_id="mission1", planner_id="baseline", telescope_id="tel1", instrument_id="inst1")
    assert run.status == RunStatus.RUNNING
    assert run.telescope.state == TelescopeState.IDLE
    assert run.telescope.current_ra is None
    assert run.instrument.state == InstrumentState.IDLE
    assert run.current_weather == WeatherCondition.CLEAR
    assert run.pending_requests() == []

    request = ObservationRequest(id="req1", run_id="run1", definition_id="d1")
    run.observation_requests[request.id] = request
    assert request.status == RequestStatus.PENDING
    assert run.pending_requests() == [request]


def test_observation_lifecycle_finalize_is_single_shot():
    observation = Observation(
        id="obs-1",
        request_id="req1",
        telescope_id="tel1",
        instrument_id="inst1",
        created_from_proposal_id="prop1",
        start_time=50,
        planned_duration=30,
    )
    assert observation.is_open()
    observation.finalize(end_time=80, outcome=ObservationOutcome.SUCCESS)
    assert not observation.is_open()
    assert observation.actual_duration == 30
    assert observation.outcome == ObservationOutcome.SUCCESS

    with pytest.raises(ValueError):
        observation.finalize(end_time=90, outcome=ObservationOutcome.SUCCESS)


def test_weather_condition_can_observe():
    assert WeatherCondition.CLEAR.can_observe
    assert not WeatherCondition.CLOUDY.can_observe
    assert not WeatherCondition.HIGH_WIND.can_observe
