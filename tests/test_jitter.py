"""Spreading a snapshot's rows out in event time.

The properties being pinned here are the two the design rests on: the offset
is reproducible, and it is forward-only and bounded by `spread`. Everything
downstream -- watermarks, windows, a second consumer reading the same range --
depends on those holding.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from london_cycles import jitter_event, jitter_events, jitter_time
from london_cycles.jitter import DEFAULT_SEED, DEFAULT_SPREAD

#: One poll: every station stamped with the same instant, which is the problem.
SNAPSHOT = [{"place_id": f"BikePoints_{n}", "query_time": "2023-07-01T09:00:00", "bikes": n} for n in range(1, 51)]

#: The dataset's polling interval. `spread` has to stay under it.
POLL_SECONDS = 15 * 60


def offset(event: dict[str, Any], original: str = "2023-07-01T09:00:00") -> float:
    moved = datetime.fromisoformat(event["query_time"]) - datetime.fromisoformat(original)
    return moved.total_seconds()


def test_offsets_are_reproducible() -> None:
    """A re-replay, or a second consumer on the same range, sees the same
    instants. No RNG state, no dependence on the order rows are visited in."""
    first = list(jitter_events(iter(SNAPSHOT), spread=45.0))
    second = list(jitter_events(iter(reversed(SNAPSHOT)), spread=45.0))
    assert first == list(reversed(second))


def test_offsets_are_stable_across_versions() -> None:
    """A golden value, so a change to the hash is a deliberate act.

    Silently reshuffling the offsets would mean a range replayed today no
    longer matches the same range replayed last month.
    """
    assert jitter_time("2023-07-01T09:00:00", "BikePoints_1", 45.0, "cycles") == ("2023-07-01T09:00:01.003")


def test_rows_only_ever_move_forward() -> None:
    """Never before the nominal instant: a row that moved backwards could
    land before the watermark of the snapshot it belongs to."""
    assert all(offset(event) >= 0 for event in jitter_events(iter(SNAPSHOT), spread=45.0))


def test_offsets_stay_inside_the_spread() -> None:
    assert all(offset(event) < 45.0 for event in jitter_events(iter(SNAPSHOT), spread=45.0))


def test_snapshots_do_not_overtake_each_other() -> None:
    """The reason `spread` must stay under the polling interval: event time
    still advances across the replay, snapshot by snapshot."""
    later = [{**row, "query_time": "2023-07-01T09:15:00"} for row in SNAPSHOT]
    jittered = list(jitter_events(iter([*SNAPSHOT, *later]), spread=DEFAULT_SPREAD))
    first_poll = [datetime.fromisoformat(e["query_time"]) for e in jittered[: len(SNAPSHOT)]]
    second_poll = [datetime.fromisoformat(e["query_time"]) for e in jittered[len(SNAPSHOT) :]]
    assert max(first_poll) < min(second_poll)


def test_the_default_spread_is_under_the_polling_interval() -> None:
    assert 0 < DEFAULT_SPREAD < POLL_SECONDS


def test_a_poll_no_longer_lands_on_one_instant() -> None:
    """The whole point: an event-time window over these now has structure
    rather than a single instant repeated 50 times."""
    jittered = list(jitter_events(iter(SNAPSHOT), spread=45.0))
    assert len({event["query_time"] for event in jittered}) > 1


def test_stations_are_spread_out_not_bunched() -> None:
    """Offsets should cover the range, not cluster in a corner of it."""
    offsets = sorted(offset(event) for event in jitter_events(iter(SNAPSHOT), spread=45.0))
    assert offsets[0] < 5.0
    assert offsets[-1] > 40.0


def test_milliseconds_are_kept() -> None:
    """~800 stations over a few tens of seconds would otherwise collide back
    onto the same second, which is the very thing being undone."""
    assert "." in jitter_time("2023-07-01T09:00:00", "BikePoints_1", 45.0, DEFAULT_SEED)


def test_the_seed_changes_the_arrangement() -> None:
    one = [event["query_time"] for event in jitter_events(iter(SNAPSHOT), spread=45.0, seed="a")]
    two = [event["query_time"] for event in jitter_events(iter(SNAPSHOT), spread=45.0, seed="b")]
    assert one != two


def test_each_station_moves_independently() -> None:
    """Same instant, different station: the offset is keyed on `place_id`, so
    two stations in one poll do not move together."""
    a = jitter_time("2023-07-01T09:00:00", "BikePoints_1", 45.0, DEFAULT_SEED)
    b = jitter_time("2023-07-01T09:00:00", "BikePoints_2", 45.0, DEFAULT_SEED)
    assert a != b


def test_a_spread_of_zero_replays_verbatim() -> None:
    """So the raw dataset stays reachable through the same code path."""
    assert list(jitter_events(iter(SNAPSHOT), spread=0)) == SNAPSHOT


def test_the_space_separator_is_preserved() -> None:
    """`YYYY-MM-DD HH:MM:SS` goes back out with the space it came in with."""
    assert jitter_time("2023-07-01 09:00:00", "BikePoints_1", 45.0, "cycles").startswith("2023-07-01 09:00:0")


@pytest.mark.parametrize(
    "event",
    [
        {"place_id": "BikePoints_1", "bikes": 12},
        {"place_id": "BikePoints_1", "query_time": None},
        {"place_id": "BikePoints_1", "query_time": ""},
        {"place_id": "BikePoints_1", "query_time": "not a timestamp"},
    ],
)
def test_rows_without_a_usable_timestamp_pass_through(event: dict[str, Any]) -> None:
    """A caller can feed this a mixed stream without filtering it first."""
    assert jitter_event(event, spread=45.0, seed=DEFAULT_SEED) == event


def test_a_row_with_no_station_still_moves() -> None:
    """Missing `place_id` degrades to a shared offset rather than raising."""
    event = jitter_event({"query_time": "2023-07-01T09:00:00"}, spread=45.0, seed=DEFAULT_SEED)
    assert 0 <= offset(event) < 45.0


def test_the_input_event_is_not_mutated() -> None:
    """The caller may still be holding the row; jitter returns a copy."""
    event = {"place_id": "BikePoints_1", "query_time": "2023-07-01T09:00:00"}
    jitter_event(event, spread=45.0, seed=DEFAULT_SEED)
    assert event["query_time"] == "2023-07-01T09:00:00"


def test_other_fields_are_left_alone() -> None:
    jittered = jitter_event(
        {"place_id": "BikePoints_1", "query_time": "2023-07-01T09:00:00", "bikes": 12},
        spread=45.0,
        seed=DEFAULT_SEED,
    )
    assert jittered["bikes"] == 12
    assert jittered["place_id"] == "BikePoints_1"


def test_jitter_is_lazy() -> None:
    """It wraps a stream; it must not drain one to get going."""

    def endless():
        while True:
            yield {"place_id": "BikePoints_1", "query_time": "2023-07-01T09:00:00"}

    jittered = jitter_events(endless(), spread=45.0)
    assert offset(next(jittered)) < 45.0


def test_a_larger_spread_moves_rows_further() -> None:
    small = max(offset(e) for e in jitter_events(iter(SNAPSHOT), spread=10.0))
    large = max(offset(e) for e in jitter_events(iter(SNAPSHOT), spread=600.0))
    assert small < 10.0 < large
    assert large < 600.0
    # Sanity: the same fraction scaled, not a different arrangement.
    assert timedelta(seconds=small * 60) - timedelta(seconds=large) < timedelta(seconds=1)
