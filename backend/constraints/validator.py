"""Constraint checks for observation proposals.

Pure functions only: no side effects, and nothing here touches the Simulator.
Every check reads only the WorldSnapshot it is given.

The snapshot carries telescope_state but not telescope pointing. DEADLINE_FEASIBLE
therefore checks that the exposure finishes by the request's deadline and does
not add slew time, because the validator cannot compute it from the snapshot.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from backend.domain.entities import InstrumentState, TelescopeState
from backend.domain.value_objects import Action, ActionProposal, PendingRequestView, ValidationResult, WorldSnapshot
from backend.domain.astronomy import is_visible_for


def _find_pending_view(snapshot: WorldSnapshot, request_id: Optional[str]) -> Optional[PendingRequestView]:
    for view in snapshot.pending_requests:
        if view.request.id == request_id:
            return view
    return None


def _valid_request(proposal: ActionProposal, snapshot: WorldSnapshot) -> Tuple[bool, str]:
    if _find_pending_view(snapshot, proposal.request_id) is None:
        return False, f"request {proposal.request_id!r} is not a pending request in this run"
    return True, ""


def _visibility(proposal: ActionProposal, snapshot: WorldSnapshot) -> Tuple[bool, str]:
    view = _find_pending_view(snapshot, proposal.request_id)
    if view is None:
        return True, ""  # VALID_REQUEST already reports this failure
    if not is_visible_for(list(view.windows), snapshot.sim_time, view.definition.required_exposure_duration):
        return False, "target is not visible for the full proposed exposure duration"
    return True, ""


def _telescope_available(proposal: ActionProposal, snapshot: WorldSnapshot) -> Tuple[bool, str]:
    if snapshot.telescope_state != TelescopeState.IDLE:
        return False, f"telescope is {snapshot.telescope_state.value}, not IDLE"
    return True, ""


def _instrument_available(proposal: ActionProposal, snapshot: WorldSnapshot) -> Tuple[bool, str]:
    if snapshot.instrument_state != InstrumentState.IDLE:
        return False, f"instrument is {snapshot.instrument_state.value}, not IDLE"
    return True, ""


def _weather_permits(proposal: ActionProposal, snapshot: WorldSnapshot) -> Tuple[bool, str]:
    if not snapshot.weather.can_observe:
        return False, f"weather is {snapshot.weather.value}, observing not permitted"
    return True, ""


def _deadline_feasible(proposal: ActionProposal, snapshot: WorldSnapshot) -> Tuple[bool, str]:
    view = _find_pending_view(snapshot, proposal.request_id)
    if view is None:
        return True, ""
    if snapshot.sim_time + view.definition.required_exposure_duration > view.definition.deadline:
        return False, "completing the exposure would miss the request's deadline"
    return True, ""


# The constraints checked, in order, for every OBSERVE proposal. Not pluggable.
_OBSERVE_CONSTRAINTS = (
    ("VALID_REQUEST", _valid_request),
    ("VISIBILITY", _visibility),
    ("TELESCOPE_AVAILABLE", _telescope_available),
    ("INSTRUMENT_AVAILABLE", _instrument_available),
    ("WEATHER_PERMITS", _weather_permits),
    ("DEADLINE_FEASIBLE", _deadline_feasible),
)


def validate(proposal: ActionProposal, snapshot: WorldSnapshot) -> ValidationResult:
    if proposal.action == Action.WAIT:
        return ValidationResult(approved=True, reason="WAIT is always valid")

    violated: List[str] = []
    reasons: List[str] = []
    for name, check in _OBSERVE_CONSTRAINTS:
        satisfied, detail = check(proposal, snapshot)
        if not satisfied:
            violated.append(name)
            reasons.append(f"{name}: {detail}")

    if violated:
        return ValidationResult(approved=False, reason="; ".join(reasons), violated_constraints=tuple(violated))
    return ValidationResult(approved=True, reason="all constraints satisfied")
