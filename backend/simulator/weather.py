"""Weather script lookup: a deterministic {sim_time: WeatherCondition} table,
never a live or random process."""
from __future__ import annotations

from typing import Tuple

from backend.domain.entities import WeatherCondition


def initial_weather(weather_script: Tuple[Tuple[int, WeatherCondition], ...]) -> WeatherCondition:
    if not weather_script:
        return WeatherCondition.CLEAR
    return weather_script[0][1]


def scheduled_weather_changes(
    weather_script: Tuple[Tuple[int, WeatherCondition], ...],
    night_window: Tuple[int, int],
):
    """Every script entry strictly after night_window.start is a real change to
    schedule; the entry at (or before) night_window.start is just the initial
    condition, not a change."""
    start, end = night_window
    for sim_time, condition in weather_script:
        if start < sim_time <= end:
            yield sim_time, condition
