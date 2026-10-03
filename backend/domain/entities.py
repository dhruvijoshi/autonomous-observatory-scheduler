"""Core domain entities.

Immutable configuration (Observatory, ObservationTarget, RequestDefinition, Mission)
is kept separate from mutable runtime state (Run, ObservationRequest, Observation,
Telescope, Instrument).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


# --- Immutable configuration -------------------------------------------------


@dataclass(frozen=True)
class Observatory:
    id: str
    name: str
    latitude: float  # degrees, +N
    longitude: float  # degrees, stored for realism only — not consumed by visibility math
    elevation: float  # metres, stored for realism only — not consumed by visibility math
    default_minimum_altitude: float  # degrees
    telescope_slew_rate_deg_per_sec: float


@dataclass(frozen=True)
class ObservationTarget:
    id: str
    name: str
    ra: float  # degrees, [0, 360)
    dec: float  # degrees, [-90, 90]
    minimum_altitude_override: Optional[float] = None

    def effective_minimum_altitude(self, observatory: Observatory) -> float:
        if self.minimum_altitude_override is not None:
            return self.minimum_altitude_override
        return observatory.default_minimum_altitude


@dataclass(frozen=True)
class RequestDefinition:
    id: str
    target_id: str
    priority: int
    required_exposure_duration: int  # sim minutes
    deadline: int  # sim_time (minutes since night_window.start)


@dataclass(frozen=True)
class Mission:
    id: str
    name: str
    observatory_id: str
    request_definitions: Tuple[RequestDefinition, ...]
    weather_script: Tuple[Tuple[int, "WeatherCondition"], ...]  # sorted (sim_time, condition)
    night_window: Tuple[int, int]  # (start, end), minutes
    starting_local_sidereal_time: float  # degrees


# --- Weather -------------------------------------------------------------


class WeatherCondition(str, Enum):
    CLEAR = "CLEAR"
    CLOUDY = "CLOUDY"
    HIGH_WIND = "HIGH_WIND"

    @property
    def can_observe(self) -> bool:
        return self is WeatherCondition.CLEAR


# --- Mutable runtime state (Run-scoped) ----------------------------------


class TelescopeState(str, Enum):
    IDLE = "IDLE"
    SLEWING = "SLEWING"
    TRACKING = "TRACKING"
    OBSERVING = "OBSERVING"
    PARKING = "PARKING"
    PARKED = "PARKED"
    ERROR = "ERROR"


class InstrumentState(str, Enum):
    IDLE = "IDLE"
    EXPOSING = "EXPOSING"
    ERROR = "ERROR"


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class ObservationOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    INCOMPLETE = "INCOMPLETE"


@dataclass
class Telescope:
    """Run-scoped mutable runtime state. Static config (slew rate) lives on Observatory."""

    state: TelescopeState = TelescopeState.IDLE
    current_ra: Optional[float] = None
    current_dec: Optional[float] = None
    state_entered_at: int = 0


@dataclass
class Instrument:
    """Run-scoped mutable runtime state."""

    state: InstrumentState = InstrumentState.IDLE
    state_entered_at: int = 0


@dataclass
class ObservationRequest:
    """Run-scoped mutable runtime state, one instantiated per RequestDefinition at Run start."""

    id: str
    run_id: str
    definition_id: str
    status: RequestStatus = RequestStatus.PENDING


@dataclass
class Observation:
    """Run-scoped, immutable once finalized (end_time/outcome set)."""

    id: str
    request_id: str
    telescope_id: str
    instrument_id: str
    created_from_proposal_id: Optional[str]
    start_time: int
    planned_duration: int
    end_time: Optional[int] = None
    actual_duration: Optional[int] = None
    outcome: Optional[ObservationOutcome] = None
    incomplete_reason: Optional[str] = None

    def is_open(self) -> bool:
        return self.outcome is None

    def finalize(self, end_time: int, outcome: ObservationOutcome, incomplete_reason: Optional[str] = None) -> None:
        if not self.is_open():
            raise ValueError(f"Observation {self.id} is already finalized")
        self.end_time = end_time
        self.actual_duration = end_time - self.start_time
        self.outcome = outcome
        self.incomplete_reason = incomplete_reason


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"


@dataclass
class Run:
    """All mutable state for one planner's attempt at one Mission. A data container —
    the Simulator and Orchestrator act on it; it has no behavior of its own beyond
    simple bookkeeping helpers.
    """

    run_id: str
    mission_id: str
    planner_id: str
    telescope_id: str
    instrument_id: str
    status: RunStatus = RunStatus.RUNNING
    sim_time: int = 0
    telescope: Telescope = field(default_factory=Telescope)
    instrument: Instrument = field(default_factory=Instrument)
    current_weather: WeatherCondition = WeatherCondition.CLEAR
    observation_requests: dict = field(default_factory=dict)  # id -> ObservationRequest
    observations: dict = field(default_factory=dict)  # id -> Observation
    _event_seq: int = 0
    _observation_seq: int = 0
    _proposal_seq: int = 0

    def next_event_id(self) -> str:
        self._event_seq += 1
        return f"{self.run_id}-evt-{self._event_seq}"

    def next_observation_id(self) -> str:
        self._observation_seq += 1
        return f"{self.run_id}-obs-{self._observation_seq}"

    def next_proposal_id(self) -> str:
        self._proposal_seq += 1
        return f"{self.run_id}-proposal-{self._proposal_seq}"

    def pending_requests(self):
        return [r for r in self.observation_requests.values() if r.status == RequestStatus.PENDING]
