"""Mission loading and Run instantiation.

`load_mission` converts already-parsed data (a dict) into an immutable Mission.
It does not read files, so the caller parses JSON, YAML or any other format.

`instantiate_run` is a pure function that turns a Mission and a planner_id into
a fresh Run. Every planner that runs the same Mission starts from identical state.
"""
from __future__ import annotations

from typing import Any, Dict

from backend.domain.entities import (
    Mission,
    ObservationRequest,
    RequestDefinition,
    Run,
    WeatherCondition,
)


def load_mission(data: Dict[str, Any]) -> Mission:
    request_definitions = tuple(
        RequestDefinition(
            id=d["id"],
            target_id=d["target_id"],
            priority=d["priority"],
            required_exposure_duration=d["required_exposure_duration"],
            deadline=d["deadline"],
        )
        for d in data["request_definitions"]
    )
    weather_script = tuple(
        (sim_time, WeatherCondition(condition)) for sim_time, condition in data["weather_script"]
    )
    return Mission(
        id=data["id"],
        name=data["name"],
        observatory_id=data["observatory_id"],
        request_definitions=request_definitions,
        weather_script=weather_script,
        night_window=tuple(data["night_window"]),
        starting_local_sidereal_time=data["starting_local_sidereal_time"],
    )


def instantiate_run(mission: Mission, planner_id: str) -> Run:
    """Pure function of (mission, planner_id): copies request_definitions into
    fresh PENDING ObservationRequests and resets sim_time to night_window.start.
    Telescope and instrument state start at their Run field defaults (IDLE, unpointed)."""
    run_id = f"{mission.id}-{planner_id}"
    telescope_id = f"{mission.observatory_id}-telescope"
    instrument_id = f"{mission.observatory_id}-instrument"

    run = Run(
        run_id=run_id,
        mission_id=mission.id,
        planner_id=planner_id,
        telescope_id=telescope_id,
        instrument_id=instrument_id,
        sim_time=mission.night_window[0],
    )
    for definition in mission.request_definitions:
        request = ObservationRequest(id=f"{run_id}-{definition.id}", run_id=run_id, definition_id=definition.id)
        run.observation_requests[request.id] = request
    return run
