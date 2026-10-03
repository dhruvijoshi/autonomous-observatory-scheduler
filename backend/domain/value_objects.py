"""Value objects: immutable, derived or transient, no identity of their own."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from backend.domain.entities import (
    InstrumentState,
    ObservationRequest,
    RequestDefinition,
    TelescopeState,
    WeatherCondition,
)


@dataclass(frozen=True)
class ObservationWindow:
    """A maximal interval during the night_window in which a target's altitude
    is at or above its effective minimum altitude."""

    rise_time: int
    set_time: int

    def contains(self, start_time: int, duration: int) -> bool:
        return self.rise_time <= start_time and start_time + duration <= self.set_time


class Action(str, Enum):
    OBSERVE = "OBSERVE"
    WAIT = "WAIT"


@dataclass(frozen=True)
class Rationale:
    factors: Dict[str, float] = field(default_factory=dict)
    summary: str = ""


@dataclass(frozen=True)
class ActionProposal:
    action: Action
    planner_id: str
    proposed_at: int
    rationale: Rationale
    request_id: Optional[str] = None  # required iff action == OBSERVE

    def __post_init__(self):
        if self.action == Action.OBSERVE and self.request_id is None:
            raise ValueError("OBSERVE proposals must carry a request_id")


@dataclass(frozen=True)
class ValidationResult:
    approved: bool
    reason: str
    violated_constraints: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PendingRequestView:
    """What a planner sees about one pending request — the RequestDefinition's
    immutable fields resolved together with the mutable ObservationRequest's status
    and its precomputed visibility windows."""

    request: ObservationRequest
    definition: RequestDefinition
    windows: Tuple[ObservationWindow, ...]


@dataclass(frozen=True)
class WorldSnapshot:
    """The entire read-only view handed to a Planner. Identical shape regardless
    of which planner is active — this is what makes them comparable."""

    sim_time: int
    telescope_state: TelescopeState
    instrument_state: InstrumentState
    weather: WeatherCondition
    pending_requests: Tuple[PendingRequestView, ...]
    recent_events: Tuple[object, ...] = field(default_factory=tuple)
