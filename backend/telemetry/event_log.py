"""An in-memory event log that supports append() and query().

Events are held in memory only. The interface is the one a persisted log would
implement, so a storage backend can replace this class without changing callers.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from backend.domain.events import Event, EventType


class InMemoryEventLog:
    def __init__(self) -> None:
        self._events: List[Event] = []

    def append(self, event: Event) -> None:
        self._events.append(event)

    def append_all(self, events: Iterable[Event]) -> None:
        for event in events:
            self.append(event)

    def query(
        self,
        run_id: Optional[str] = None,
        since: Optional[int] = None,
        event_types: Optional[Iterable[EventType]] = None,
    ) -> List[Event]:
        types = set(event_types) if event_types is not None else None
        results = self._events
        if run_id is not None:
            results = [e for e in results if e.run_id == run_id]
        if since is not None:
            results = [e for e in results if e.sim_time >= since]
        if types is not None:
            results = [e for e in results if e.type in types]
        return list(results)

    def all(self) -> List[Event]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)
