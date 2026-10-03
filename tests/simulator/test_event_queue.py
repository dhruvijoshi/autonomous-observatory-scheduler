"""Event queue ordering and deterministic tie-breaking."""
from backend.domain.events import EventType
from backend.simulator.event_queue import EventQueue


def test_events_are_popped_in_sim_time_order():
    queue = EventQueue()
    queue.schedule(EventType.WeatherChanged, sim_time=50)
    queue.schedule(EventType.ObservatoryClosed, sim_time=480)
    queue.schedule(EventType.TargetBecameVisible, sim_time=10)

    times = [queue.pop().sim_time for _ in range(3)]
    assert times == [10, 50, 480]


def test_same_timestamp_events_break_ties_by_schedule_order():
    queue = EventQueue()
    first = queue.schedule(EventType.WeatherChanged, sim_time=100, payload={"label": "first"})
    second = queue.schedule(EventType.TargetBecameVisible, sim_time=100, payload={"label": "second"})
    third = queue.schedule(EventType.RequestExpired, sim_time=100, payload={"label": "third"})

    popped = [queue.pop() for _ in range(3)]
    assert [e.payload["label"] for e in popped] == ["first", "second", "third"]
    assert [e.sequence_no for e in popped] == [first.sequence_no, second.sequence_no, third.sequence_no]


def test_ordering_is_stable_regardless_of_schedule_interleaving():
    # Schedule out of chronological order and interleaved with same-timestamp
    # entries; the queue must still resolve to a single deterministic sequence.
    queue = EventQueue()
    queue.schedule(EventType.ObservatoryClosed, sim_time=480, payload={"label": "close"})
    queue.schedule(EventType.WeatherChanged, sim_time=60, payload={"label": "w1"})
    queue.schedule(EventType.TargetBecameVisible, sim_time=60, payload={"label": "tv1"})
    queue.schedule(EventType.ObservatoryOpened, sim_time=0, payload={"label": "open"})

    order = []
    while not queue.is_empty():
        order.append(queue.pop().payload["label"])
    assert order == ["open", "w1", "tv1", "close"]


def test_is_empty_and_len():
    queue = EventQueue()
    assert queue.is_empty()
    assert len(queue) == 0
    queue.schedule(EventType.ObservatoryOpened, sim_time=0)
    assert not queue.is_empty()
    assert len(queue) == 1
    queue.pop()
    assert queue.is_empty()
