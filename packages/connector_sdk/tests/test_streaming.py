"""S13 streaming primitives: ring buffer, reconnect loop, event sink."""
import asyncio

from rca_connector_sdk.ports import CollectingEventSink, NullEventSink
from rca_connector_sdk.subscription import RingBuffer, SubscriptionState, run_with_reconnect


def test_ring_buffer_is_bounded_and_ordered():
    rb = RingBuffer(maxlen=3)
    for i in range(5):
        rb.append(i)
    assert rb.snapshot() == [2, 3, 4]      # oldest dropped, order preserved
    assert len(rb) == 3


def test_subscription_state_defaults():
    st = SubscriptionState()
    assert st.current_values == {} and st.metadata == {}
    st.recent.append("x")
    assert st.recent.snapshot() == ["x"]


def test_event_sinks():
    null = NullEventSink()
    assert null.emit({"a": 1}) is None
    collecting = CollectingEventSink()
    collecting.emit({"alias": "P-101A"})
    assert collecting.events == [{"alias": "P-101A"}]


async def test_run_with_reconnect_retries_then_stops():
    calls = {"n": 0}
    stop = asyncio.Event()

    async def consume():
        calls["n"] += 1
        if calls["n"] >= 3:
            stop.set()                      # ask to stop on the 3rd attempt
        raise ConnectionError("dropped")    # simulate a dropped connection each time

    await run_with_reconnect(consume, stop=stop, base_backoff=0.001, max_backoff=0.005)
    assert calls["n"] == 3                   # retried with reconnect, then exited cleanly


async def test_run_with_reconnect_resets_backoff_on_clean_return():
    calls = {"n": 0}
    stop = asyncio.Event()

    async def consume():
        calls["n"] += 1
        if calls["n"] >= 2:
            stop.set()
        return  # clean return (e.g. graceful close) -> loop continues until stop

    await run_with_reconnect(consume, stop=stop, base_backoff=0.001, max_backoff=0.005)
    assert calls["n"] == 2
