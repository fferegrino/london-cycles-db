"""Fixtures shared across the suite.

Nothing here talks to the Hub. `list_files` and `download` are the only two
functions that would, and both are stubbed per-test; `no_network` is the net
underneath that, so a stub that stops matching the code fails loudly instead
of quietly reaching for the real dataset.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

#: One line per station per poll, in the column order the dataset uses.
SNAPSHOT_HEADER = "place_id,query_time,bikes,empty_docks,docks"

#: A trimmed `stations.csv`: three stations, one of them (BikePoints_14) with
#: a closed interval and a second version, so the fixture covers both the
#: still-valid and the superseded case.
STATIONS_CSV = textwrap.dedent("""\
    place_id,common_name,lat,lon,terminal_name,installed,temporary,install_date,removal_date,valid_from,valid_to
    BikePoints_1,"River Street , Clerkenwell",51.529163,-0.10997,001023,true,false,2010-07-12,,2022-04-29,
    BikePoints_14,"Belgrove Street , King's Cross",51.529943,-0.123616,001011,true,false,2010-07-05,,2022-04-29,2023-07-18
    BikePoints_14,"Belgrove Street, King's Cross",51.529999,-0.123600,001011,true,false,2010-07-05,,2023-07-18,
    BikePoints_9,"New Globe Walk, Bankside",51.507385,-0.096440,001024,false,true,2010-07-01,2021-03-02,2022-04-29,
    """)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make a real Hub call impossible, rather than merely slow."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_HOME", "/nonexistent-hf-home")


@pytest.fixture
def stations_csv(tmp_path: Path) -> Path:
    path = tmp_path / "stations.csv"
    path.write_text(STATIONS_CSV, encoding="utf-8")
    return path


def write_snapshot(path: Path, rows: list[str]) -> Path:
    """A CSV snapshot at `path`, parents created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([SNAPSHOT_HEADER, *rows]) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A local mirror of the Hub layout: two days, one of them mid-compaction.

    Day 01 is finished (`part.csv` only). Day 02 has been compacted up to
    09:00 and has two later runs still sitting as their own files -- the case
    where a plain path sort puts `part.csv` last and gets the day backwards.
    """
    root = tmp_path / "mirror"
    day1 = root / "data/year=2023/month=07/day=01"
    day2 = root / "data/year=2023/month=07/day=02"
    write_snapshot(day1 / "part.csv", ["BikePoints_1,2023-07-01T09:00:00,12,8,20"])
    write_snapshot(day2 / "part.csv", ["BikePoints_1,2023-07-02T09:00:00,10,10,20"])
    write_snapshot(day2 / "091500.csv", ["BikePoints_1,2023-07-02T09:15:00,9,11,20"])
    write_snapshot(day2 / "093000.csv", ["BikePoints_1,2023-07-02T09:30:00,,12,20"])
    # The dimension sits at the repo root and is not an observation file.
    (root / "stations.csv").write_text(STATIONS_CSV, encoding="utf-8")
    return root
