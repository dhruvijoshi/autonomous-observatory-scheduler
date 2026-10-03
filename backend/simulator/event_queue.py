"""The discrete-event priority queue.

Ordering is (sim_time, sequence_no) — sequence_no is assigned in the order
events are scheduled, breaking ties between same-timestamp events
deterministically regardless of heap implementation details.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from backend.domain.events import EventType


@dataclass(order=True)
class ScheduledEvent:
    sim_time: int
    sequence_no: int
    kind: EventType = field(compare=False)
    payload: Dict[str, Any] = field(default_factory=dict, compare=False)


class EventQueue:
    """A min-heap of ScheduledEvents ordered by (sim_time, sequence_no)."""

    def __init__(self) -> None:
        self._heap: list = []
        self._next_sequence = 0

    def schedule(self, kind: EventType, sim_time: int, payload: Optional[Dict[str, Any]] = None) -> ScheduledEvent:
        event = ScheduledEvent(sim_time=sim_time, sequence_no=self._next_sequence, kind=kind, payload=payload or {})
        self._next_sequence += 1
        heapq.heappush(self._heap, event)
        return event

    def pop(self) -> ScheduledEvent:
        return heapq.heappop(self._heap)

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)
