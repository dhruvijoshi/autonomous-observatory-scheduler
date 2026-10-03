"""The Event dataclass and the enum of event types the simulator emits.

Fault injection and mid-exposure abort events are not implemented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class EventType(str, Enum):
    ObservatoryOpened = "ObservatoryOpened"
    ObservatoryClosed = "ObservatoryClosed"

    WeatherChanged = "WeatherChanged"
    TargetBecameVisible = "TargetBecameVisible"
    TargetBecameUnavailable = "TargetBecameUnavailable"

    TelescopeSlewStarted = "TelescopeSlewStarted"
    TelescopeSlewCompleted = "TelescopeSlewCompleted"

    ObservationStarted = "ObservationStarted"
    ObservationCompleted = "ObservationCompleted"

    RequestExpired = "RequestExpired"

    PlannerInvoked = "PlannerInvoked"
    ActionProposed = "ActionProposed"
    ActionApproved = "ActionApproved"
    ActionRejected = "ActionRejected"
    MissionReplanned = "MissionReplanned"


# Events that make the orchestrator replan. ObservatoryClosed is excluded because
# it halts the run instead of prompting a new decision.
REPLAN_TRIGGERS = frozenset(
    {
        EventType.ObservationCompleted,
        EventType.WeatherChanged,
        EventType.TargetBecameVisible,
        EventType.TargetBecameUnavailable,
    }
)


@dataclass(frozen=True)
class Event:
    event_id: str
    run_id: str
    sim_time: int
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = "simulator"
