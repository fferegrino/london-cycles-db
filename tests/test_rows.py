"""Parsing a snapshot row."""

from __future__ import annotations

from pathlib import Path

from london_cycles import coerce_row, read_csv

from conftest import write_snapshot


def test_counts_are_numbers_not_strings() -> None:
    row = coerce_row(
        {
            "place_id": "BikePoints_1",
            "query_time": "2023-07-01T09:00:00",
            "bikes": "12",
            "empty_docks": "8",
            "docks": "20",
        }
    )
    assert row == {
        "place_id": "BikePoints_1",
        "query_time": "2023-07-01T09:00:00",
        "bikes": 12,
        "empty_docks": 8,
        "docks": 20,
    }


def test_missing_count_is_none_not_zero() -> None:
    """A station that did not report is not a station reporting no bikes.

    Coercing the blank to 0 would invent an empty dock in every average
    downstream, which is the kind of thing nobody notices for months.
    """
    row = coerce_row({"place_id": "BikePoints_1", "bikes": "", "docks": "20"})
    assert row["bikes"] is None
    assert row["docks"] == 20


def test_whitespace_is_stripped() -> None:
    row = coerce_row({"place_id": " BikePoints_1 ", "bikes": " 12 "})
    assert row == {"place_id": "BikePoints_1", "bikes": 12}


def test_unparseable_count_survives_as_text() -> None:
    """Better a string downstream than a row silently dropped or zeroed."""
    row = coerce_row({"place_id": "BikePoints_1", "bikes": "n/a"})
    assert row["bikes"] == "n/a"


def test_unknown_columns_pass_through() -> None:
    """The dataset can gain a column without this library being taught it."""
    row = coerce_row({"place_id": "BikePoints_1", "some_new_column": "hello"})
    assert row["some_new_column"] == "hello"


def test_read_csv_yields_one_event_per_row(tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path / "part.csv",
        [
            "BikePoints_1,2023-07-01T09:00:00,12,8,20",
            "BikePoints_2,2023-07-01T09:00:00,3,17,20",
        ],
    )
    events = list(read_csv(path))
    assert [event["place_id"] for event in events] == ["BikePoints_1", "BikePoints_2"]
    assert events[0]["bikes"] == 12


def test_read_csv_is_lazy(tmp_path: Path) -> None:
    """Streamed, not read whole: a day of the real dataset is ~800 rows and a
    range is thousands of files, so nothing should materialise a file."""
    path = write_snapshot(tmp_path / "part.csv", ["BikePoints_1,2023-07-01T09:00:00,12,8,20"])
    events = read_csv(path)
    assert next(iter(events))["place_id"] == "BikePoints_1"
