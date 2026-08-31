"""Spreading a snapshot's rows out in event time.

The dataset is polled on a 15-minute cadence and every station in a run is
stamped with the same `query_time`, to the second. That is an artefact of how
the history was collected, not of how a live feed behaves: real stations report
independently, and a poll that walks ~800 of them takes a while. Replaying the
rows as they are stored gives event-time windows that each contain
exactly one instant, so anything windowed is really just a group-by.

So each row's `query_time` is nudged forward by an offset derived from a hash of
`(seed, place_id, query_time)`. Two properties fall out of that choice:

* **Reproducible.** The offset is a pure function of the row, so a re-replay --
  or a second consumer reading the same range -- sees the same instants. No RNG
  state, no dependence on the order rows are visited in.
* **Forward-only, bounded by `spread`.** A row never moves before its nominal
  instant and never past `spread` seconds after it, so as long as `spread` is
  under the polling interval, snapshot N still lands entirely before snapshot
  N+1's nominal time and event time keeps advancing across the replay.

`spread` is bounded by however much out-of-orderness the consumer tolerates:
rows within one snapshot now arrive up to `spread` seconds apart, so a stream
processor's watermark tolerance has to be at least that or the late rows are
dropped. Raise one and raise the other.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

#: Timestamp field to jitter, and the key that seeds it per station.
TIME_FIELD = "query_time"
KEY_FIELD = "place_id"

#: A spread comfortably inside the 15-minute polling interval, and a seed that
#: only needs changing for a different-but-still-reproducible arrangement.
DEFAULT_SPREAD = 45.0
DEFAULT_SEED = "cycles"


def _fraction(seed: str, key: str, value: str) -> float:
    """A stable number in [0, 1) for this row."""
    digest = hashlib.blake2b(f"{seed}\0{key}\0{value}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def jitter_time(value: str, key: str, spread: float, seed: str) -> str:
    """`value` moved forward by up to `spread` seconds, deterministically.

    Milliseconds are kept: 800 stations over a few tens of seconds would
    otherwise collide back onto the same second, which is the very thing being
    undone here. A millisecond timestamp costs nothing to carry.
    """
    moment = datetime.fromisoformat(value)
    offset = _fraction(seed, key, value) * spread
    return (moment + timedelta(seconds=offset)).isoformat(
        sep=value[10] if len(value) > 10 else "T", timespec="milliseconds"
    )


def jitter_event(event: dict[str, Any], spread: float, seed: str) -> dict[str, Any]:
    """Return `event` with a jittered `query_time`, or unchanged if it can't be.

    Rows without a `query_time` pass straight through, so a caller can feed
    this a mixed stream without filtering it first.
    """
    value = event.get(TIME_FIELD)
    key = event.get(KEY_FIELD)
    if not isinstance(value, str) or not value:
        return event
    try:
        jittered = jitter_time(value, str(key or ""), spread, seed)
    except ValueError:
        log.debug("Not a timestamp, left alone: %s=%r", TIME_FIELD, value)
        return event
    return {**event, TIME_FIELD: jittered}


def jitter_events(
    events: Iterator[dict[str, Any]],
    spread: float = DEFAULT_SPREAD,
    seed: str = DEFAULT_SEED,
) -> Iterator[dict[str, Any]]:
    """Pass-through when `spread` is 0, so the raw dataset stays reachable."""
    if spread <= 0:
        log.info("Query-time jitter disabled; replaying stored timestamps as-is")
        return events
    log.info("Jittering %s by 0-%.1fs (seed=%r)", TIME_FIELD, spread, seed)
    return (jitter_event(event, spread, seed) for event in events)
