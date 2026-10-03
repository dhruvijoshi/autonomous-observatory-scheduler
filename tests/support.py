"""Shared test fixtures — not a pytest conftest, just plain factory functions
used across the domain/simulator/constraints/orchestrator test suites so the
scenario setup isn't duplicated.
"""
from typing import Any

from backend.domain.entities import Mission, ObservationTarget, Observatory, RequestDefinition, WeatherCondition

# Chosen so the target is already visible at night_window start (H(0) = -10 deg,
# altitude ~49 deg, well above the 30 deg minimum) and sets around t~236,
# comfortably inside an 8-hour (480 min) truncated to a 400 min night_window
# used by these tests for a snappier suite.
OBSERVATORY = Observatory(
    id="obs1",
    name="Test Site",
    latitude=40.0,
    longitude=-105.0,
    elevation=1655.0,
    default_minimum_altitude=30.0,
    telescope_slew_rate_deg_per_sec=2.0,
)

TARGET = ObservationTarget(id="t1", name="TestStar", ra=180.0, dec=0.0)

REQUEST_DEFINITION = RequestDefinition(
    id="d1", target_id="t1", priority=5, required_exposure_duration=30, deadline=200
)


def build_simple_mission(**overrides) -> Mission:
    fields: dict[str, Any] = dict(
        id="m1",
        name="Simple Test Mission",
        observatory_id=OBSERVATORY.id,
        request_definitions=(REQUEST_DEFINITION,),
        weather_script=((0, WeatherCondition.CLEAR),),
        night_window=(0, 400),
        starting_local_sidereal_time=170.0,
    )
    fields.update(overrides)
    return Mission(**fields)
