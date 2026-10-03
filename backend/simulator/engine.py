"""The discrete-event Simulator.

Owns a Run's mutable ground-truth state and is the only component that mutates
it. It exposes three operations: snapshot(), execute() and advance().

Implemented: propose -> validate -> execute -> slew -> observe -> complete -> close.
Not implemented: interrupting an exposure when the weather changes or equipment faults.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from backend.domain.astronomy import angular_separation_deg, compute_observation_windows
from backend.domain.entities import (
    InstrumentState,
    Mission,
    Observation,
    ObservationOutcome,
    ObservationTarget,
    Observatory,
    RequestDefinition,
    RequestStatus,
    Run,
    RunStatus,
    TelescopeState,
)
from backend.domain.events import REPLAN_TRIGGERS, Event, EventType
from backend.domain.value_objects import (
    Action,
    ActionProposal,
    PendingRequestView,
    WorldSnapshot,
)
from backend.simulator.event_queue import EventQueue, ScheduledEvent
from backend.simulator.weather import initial_weather, scheduled_weather_changes


class Simulator:
    def __init__(
        self,
        run: Run,
        mission: Mission,
        observatory: Observatory,
        definitions_by_id: Dict[str, RequestDefinition],
        targets_by_id: Dict[str, ObservationTarget],
        windows_by_target: Dict[str, list],
    ) -> None:
        self.run = run
        self.mission = mission
        self.observatory = observatory
        self.definitions_by_id = definitions_by_id
        self.targets_by_id = targets_by_id
        self.windows_by_target = windows_by_target
        self.queue = EventQueue()
        self._request_by_target: Dict[str, list] = {}
        for request in run.observation_requests.values():
            target_id = definitions_by_id[request.definition_id].target_id
            self._request_by_target.setdefault(target_id, []).append(request)

    # --- construction --------------------------------------------------

    @classmethod
    def start(
        cls,
        mission: Mission,
        observatory: Observatory,
        targets: List[ObservationTarget],
        run: Run,
    ) -> "Simulator":
        definitions_by_id = {d.id: d for d in mission.request_definitions}
        targets_by_id = {t.id: t for t in targets}

        windows_by_target = {
            target.id: compute_observation_windows(
                target, observatory, mission.night_window, mission.starting_local_sidereal_time
            )
            for target in targets
        }

        run.current_weather = initial_weather(mission.weather_script)

        simulator = cls(run, mission, observatory, definitions_by_id, targets_by_id, windows_by_target)
        simulator._precompute_world_timeline()
        return simulator

    def _precompute_world_timeline(self) -> None:
        start, end = self.mission.night_window
        # Scheduled first so it dispatches before any same-timestamp entry.
        self.queue.schedule(EventType.ObservatoryOpened, sim_time=start)

        for sim_time, condition in scheduled_weather_changes(self.mission.weather_script, self.mission.night_window):
            self.queue.schedule(EventType.WeatherChanged, sim_time=sim_time, payload={"condition": condition})

        for target_id, windows in self.windows_by_target.items():
            for window in windows:
                if window.rise_time > start:
                    self.queue.schedule(
                        EventType.TargetBecameVisible, sim_time=window.rise_time, payload={"target_id": target_id}
                    )
                if window.set_time < end:
                    self.queue.schedule(
                        EventType.TargetBecameUnavailable, sim_time=window.set_time, payload={"target_id": target_id}
                    )

        for request in self.run.observation_requests.values():
            definition = self.definitions_by_id[request.definition_id]
            if start < definition.deadline <= end:
                self.queue.schedule(
                    EventType.RequestExpired, sim_time=definition.deadline, payload={"request_id": request.id}
                )

        self.queue.schedule(EventType.ObservatoryClosed, sim_time=end)

    # --- public interface ------------------------------------------------

    def snapshot(self) -> WorldSnapshot:
        views = []
        for request in self.run.pending_requests():
            definition = self.definitions_by_id[request.definition_id]
            target = self.targets_by_id[definition.target_id]
            windows = tuple(self.windows_by_target.get(target.id, []))
            views.append(PendingRequestView(request=request, definition=definition, windows=windows))
        return WorldSnapshot(
            sim_time=self.run.sim_time,
            telescope_state=self.run.telescope.state,
            instrument_state=self.run.instrument.state,
            weather=self.run.current_weather,
            pending_requests=tuple(views),
            recent_events=(),  # not populated yet
        )

    def execute(self, proposal: ActionProposal, proposal_id: str) -> List[Event]:
        """Only ever called with an approved proposal."""
        if proposal.action == Action.WAIT:
            return []

        request = self.run.observation_requests[proposal.request_id]
        definition = self.definitions_by_id[request.definition_id]
        target = self.targets_by_id[definition.target_id]

        telescope = self.run.telescope
        if telescope.current_ra is None:
            # No pointing has been recorded in this Run yet, so the first slew is
            # instantaneous: there is no previous position to measure separation from.
            slew_minutes = 0
        else:
            separation = angular_separation_deg(telescope.current_ra, telescope.current_dec, target.ra, target.dec)
            slew_minutes = round(separation / (self.observatory.telescope_slew_rate_deg_per_sec * 60.0))

        request.status = RequestStatus.SCHEDULED
        telescope.state = TelescopeState.SLEWING
        telescope.state_entered_at = self.run.sim_time

        self.queue.schedule(
            EventType.TelescopeSlewCompleted,
            sim_time=self.run.sim_time + slew_minutes,
            payload={"request_id": request.id, "proposal_id": proposal_id},
        )

        return [self._emit(EventType.TelescopeSlewStarted, {"request_id": request.id}, source="simulator")]

    def advance(self) -> List[Event]:
        produced: List[Event] = []
        while self.run.status == RunStatus.RUNNING:
            if self.queue.is_empty():
                break
            scheduled = self.queue.pop()
            self.run.sim_time = scheduled.sim_time
            events = self._dispatch(scheduled)
            produced.extend(events)

            if any(e.type == EventType.ObservatoryClosed for e in events):
                self.run.status = RunStatus.CLOSED
                return produced
            if any(e.type == EventType.ObservatoryOpened for e in events):
                return produced
            if any(self._is_active_replan_trigger(e) for e in events):
                return produced
        return produced

    # --- dispatch handlers -----------------------------------------------

    def _dispatch(self, scheduled: ScheduledEvent) -> List[Event]:
        handler = {
            EventType.ObservatoryOpened: self._handle_observatory_opened,
            EventType.ObservatoryClosed: self._handle_observatory_closed,
            EventType.WeatherChanged: self._handle_weather_changed,
            EventType.TargetBecameVisible: self._handle_target_became_visible,
            EventType.TargetBecameUnavailable: self._handle_target_became_unavailable,
            EventType.RequestExpired: self._handle_request_expired,
            EventType.TelescopeSlewCompleted: self._handle_telescope_slew_completed,
            EventType.ObservationCompleted: self._handle_observation_completed,
        }[scheduled.kind]
        return handler(scheduled)

    def _handle_observatory_opened(self, scheduled: ScheduledEvent) -> List[Event]:
        return [self._emit(EventType.ObservatoryOpened, {})]

    def _handle_observatory_closed(self, scheduled: ScheduledEvent) -> List[Event]:
        # Parking takes no simulated time: any non-PARKED state moves straight to
        # PARKED, with no separate PARKING step.
        if self.run.telescope.state != TelescopeState.PARKED:
            self.run.telescope.state = TelescopeState.PARKED
            self.run.telescope.state_entered_at = self.run.sim_time
        return [self._emit(EventType.ObservatoryClosed, {})]

    def _handle_weather_changed(self, scheduled: ScheduledEvent) -> List[Event]:
        self.run.current_weather = scheduled.payload["condition"]
        return [self._emit(EventType.WeatherChanged, {"condition": self.run.current_weather.value})]

    def _handle_target_became_visible(self, scheduled: ScheduledEvent) -> List[Event]:
        return [self._emit(EventType.TargetBecameVisible, {"target_id": scheduled.payload["target_id"]})]

    def _handle_target_became_unavailable(self, scheduled: ScheduledEvent) -> List[Event]:
        return [self._emit(EventType.TargetBecameUnavailable, {"target_id": scheduled.payload["target_id"]})]

    def _handle_request_expired(self, scheduled: ScheduledEvent) -> List[Event]:
        request = self.run.observation_requests[scheduled.payload["request_id"]]
        if request.status in (RequestStatus.PENDING, RequestStatus.SCHEDULED, RequestStatus.IN_PROGRESS):
            request.status = RequestStatus.EXPIRED
            return [self._emit(EventType.RequestExpired, {"request_id": request.id})]
        return []

    def _handle_telescope_slew_completed(self, scheduled: ScheduledEvent) -> List[Event]:
        request = self.run.observation_requests[scheduled.payload["request_id"]]
        definition = self.definitions_by_id[request.definition_id]
        target = self.targets_by_id[definition.target_id]

        telescope = self.run.telescope
        telescope.state = TelescopeState.OBSERVING  # tracking is folded into this dispatch
        telescope.current_ra = target.ra
        telescope.current_dec = target.dec
        telescope.state_entered_at = self.run.sim_time

        instrument = self.run.instrument
        instrument.state = InstrumentState.EXPOSING
        instrument.state_entered_at = self.run.sim_time

        observation = Observation(
            id=self.run.next_observation_id(),
            request_id=request.id,
            telescope_id=self.run.telescope_id,
            instrument_id=self.run.instrument_id,
            created_from_proposal_id=scheduled.payload.get("proposal_id"),
            start_time=self.run.sim_time,
            planned_duration=definition.required_exposure_duration,
        )
        self.run.observations[observation.id] = observation
        request.status = RequestStatus.IN_PROGRESS

        self.queue.schedule(
            EventType.ObservationCompleted,
            sim_time=self.run.sim_time + definition.required_exposure_duration,
            payload={"observation_id": observation.id},
        )

        return [
            self._emit(EventType.TelescopeSlewCompleted, {"request_id": request.id}),
            self._emit(EventType.ObservationStarted, {"observation_id": observation.id, "request_id": request.id}),
        ]

    def _handle_observation_completed(self, scheduled: ScheduledEvent) -> List[Event]:
        observation = self.run.observations[scheduled.payload["observation_id"]]
        observation.finalize(end_time=self.run.sim_time, outcome=ObservationOutcome.SUCCESS)

        self.run.telescope.state = TelescopeState.IDLE
        self.run.instrument.state = InstrumentState.IDLE

        request = self.run.observation_requests[observation.request_id]
        request.status = RequestStatus.COMPLETED

        return [self._emit(EventType.ObservationCompleted, {"observation_id": observation.id})]

    # --- helpers -----------------------------------------------------------

    def _emit(self, event_type: EventType, payload: dict, source: str = "simulator") -> Event:
        return Event(
            event_id=self.run.next_event_id(),
            run_id=self.run.run_id,
            sim_time=self.run.sim_time,
            type=event_type,
            payload=payload,
            source=source,
        )

    def _is_active_replan_trigger(self, event: Event) -> bool:
        if event.type not in REPLAN_TRIGGERS:
            return False
        if event.type in (EventType.TargetBecameVisible, EventType.TargetBecameUnavailable):
            target_id = event.payload["target_id"]
            requests = self._request_by_target.get(target_id, [])
            return any(r.status == RequestStatus.PENDING for r in requests)
        return True
