"""The versioned station dimension."""

from __future__ import annotations

from pathlib import Path

import pytest

from london_cycles import read_stations, stations


def test_versions_come_back_oldest_first(stations_csv: Path) -> None:
    """Anything replaying the dimension as a log needs the versions in the
    order they became true, so the sort is part of the contract."""
    versions = read_stations(str(stations_csv))
    assert [(row["place_id"], row["valid_from"]) for row in versions] == [
        ("BikePoints_1", "2022-04-29"),
        ("BikePoints_14", "2022-04-29"),
        ("BikePoints_9", "2022-04-29"),
        ("BikePoints_14", "2023-07-18"),
    ]


def test_coordinates_are_floats(stations_csv: Path) -> None:
    first = read_stations(str(stations_csv))[0]
    assert first["lat"] == pytest.approx(51.529163)
    assert first["lon"] == pytest.approx(-0.10997)


def test_flags_are_booleans(stations_csv: Path) -> None:
    by_id = {row["place_id"]: row for row in read_stations(str(stations_csv))}
    assert by_id["BikePoints_1"]["installed"] is True
    assert by_id["BikePoints_1"]["temporary"] is False
    assert by_id["BikePoints_9"]["installed"] is False
    assert by_id["BikePoints_9"]["temporary"] is True


def test_closed_intervals_are_kept(stations_csv: Path) -> None:
    """`valid_to` is real data. Dropping it is a choice for whoever publishes
    the dimension to a versioned table, not one this loader makes for them.
    """
    superseded = read_stations(str(stations_csv))[-1]
    replaced = [
        row for row in read_stations(str(stations_csv)) if row["place_id"] == "BikePoints_14" and row["valid_to"]
    ]
    assert replaced[0]["valid_to"] == "2023-07-18"
    # The version that replaced it is the one currently in force.
    assert superseded["valid_from"] == "2023-07-18"
    assert superseded["valid_to"] is None


def test_the_version_in_force_has_no_end(stations_csv: Path) -> None:
    """A station's last version stays valid forever, which is what lets a
    station retired in 2023 still resolve for the fact rows before it."""
    open_ended = [row for row in read_stations(str(stations_csv)) if row["valid_to"] is None]
    assert {row["place_id"] for row in open_ended} == {
        "BikePoints_1",
        "BikePoints_9",
        "BikePoints_14",
    }


def test_blanks_are_none_not_empty_strings(stations_csv: Path) -> None:
    by_id = {row["place_id"]: row for row in read_stations(str(stations_csv))}
    assert by_id["BikePoints_1"]["removal_date"] is None
    assert by_id["BikePoints_9"]["removal_date"] == "2021-03-02"


def test_every_column_is_returned(stations_csv: Path) -> None:
    """Including the ones the Kafka changelog drops -- a caller doing the
    as-of join itself should not have to go back to the CSV for them."""
    assert set(read_stations(str(stations_csv))[0]) == {
        "place_id",
        "common_name",
        "lat",
        "lon",
        "terminal_name",
        "installed",
        "temporary",
        "install_date",
        "removal_date",
        "valid_from",
        "valid_to",
    }


def test_stations_reads_the_dimension_from_the_hub(monkeypatch: pytest.MonkeyPatch, stations_csv: Path) -> None:
    asked: list[tuple[str, str]] = []

    def fake_download(repo_id: str, path: str, repo_type: str, token: str | None) -> str:
        asked.append((repo_id, path))
        return str(stations_csv)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    versions = stations(repo_id="someone/a-fork")
    assert asked == [("someone/a-fork", "stations.csv")]
    assert len(versions) == 4
