"""Listing and streaming the observations.

The Hub is stubbed at its two entry points -- `HfApi.list_repo_files` and
`hf_hub_download` -- which are imported inside the functions that use them, so
patching the `huggingface_hub` attributes is enough.
"""

from __future__ import annotations

from datetime import date
from itertools import islice
from pathlib import Path

import pytest

from london_cycles import list_files, local_files, stream, stream_local
from london_cycles.dataset import as_date

from conftest import write_snapshot

#: Deliberately not in order, and with repo furniture mixed in: what the Hub
#: hands back is an unordered listing of everything in the repo.
REPO_FILES = [
    ".gitattributes",
    "readme.md",
    "stations.csv",
    "data/year=2023/month=07/day=02/091500.csv",
    "data/year=2023/month=07/day=02/part.csv",
    "data/year=2023/month=07/day=02/093000.csv",
    "data/year=2023/month=07/day=01/part.csv",
    "data/year=2023/month=06/day=30/part.csv",
    "data/year=2024/month=01/day=05/part.csv",
]

OBSERVATIONS = [path for path in REPO_FILES if path.startswith("data/")]


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub `HfApi`, returning the list of repo ids it was asked about."""
    seen: list[str] = []

    class FakeApi:
        def __init__(self, token: str | None = None) -> None:
            self.token = token

        def list_repo_files(self, repo_id: str, repo_type: str) -> list[str]:
            assert repo_type == "dataset"
            seen.append(repo_id)
            return list(REPO_FILES)

    monkeypatch.setattr("huggingface_hub.HfApi", FakeApi)
    return seen


def timestamp_for(path: str) -> str:
    """The instant a file in `REPO_FILES` holds, derived from its own name.

    Building the fake repo's contents out of its paths keeps the two from
    drifting apart -- a file added to `REPO_FILES` gets a row to match.
    """
    _, year, month, day, name = path.split("/")
    time = "09:00:00" if name == "part.csv" else f"{name[:2]}:{name[2:4]}:{name[4:6]}"
    return f"{year[5:]}-{month[6:]}-{day[4:]}T{time}"


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Stub `hf_hub_download` with a file per observation, recording each call."""
    root = tmp_path / "hub"
    for path in OBSERVATIONS:
        write_snapshot(root / path, [f"BikePoints_1,{timestamp_for(path)},12,8,20"])

    called: list[str] = []

    def fake_download(repo_id: str, path: str, repo_type: str, token: str | None) -> str:
        called.append(path)
        return str(root / path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    return called


def test_accepts_dates_as_strings_or_dates() -> None:
    """So a notebook can pass "2023-07-01" without importing datetime."""
    assert as_date("2023-07-01") == date(2023, 7, 1)
    assert as_date(date(2023, 7, 1)) == date(2023, 7, 1)
    assert as_date(None) is None


def test_files_come_back_in_chronological_order(hub: list[str]) -> None:
    """Including `part.csv` before the same day's runs.

    Sorting the path strings would put `091500.csv` first, which is backwards:
    it holds the *later* rows of a day whose earlier ones are already
    compacted into `part.csv`.
    """
    assert list_files() == [
        "data/year=2023/month=06/day=30/part.csv",
        "data/year=2023/month=07/day=01/part.csv",
        "data/year=2023/month=07/day=02/part.csv",
        "data/year=2023/month=07/day=02/091500.csv",
        "data/year=2023/month=07/day=02/093000.csv",
        "data/year=2024/month=01/day=05/part.csv",
    ]


def test_non_observation_files_are_ignored(hub: list[str]) -> None:
    """`stations.csv` is the dimension, and the rest is repo furniture."""
    assert not any(path.endswith(("readme.md", "stations.csv", ".gitattributes")) for path in list_files())


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (None, None, 6),
        ("2023-07-01", None, 5),
        (None, "2023-07-01", 2),
        ("2023-07-01", "2023-07-02", 4),
        (date(2023, 7, 2), date(2023, 7, 2), 3),
        ("2023-07-03", "2023-12-31", 0),
    ],
)
def test_date_bounds_are_inclusive(hub: list[str], start: str | None, end: str | None, expected: int) -> None:
    assert len(list_files(start=start, end=end)) == expected


def test_a_bound_selects_whole_days(hub: list[str]) -> None:
    """Day 02 comes back complete -- both the compacted part and the run."""
    assert list_files(start="2023-07-02", end="2023-07-02") == [
        "data/year=2023/month=07/day=02/part.csv",
        "data/year=2023/month=07/day=02/091500.csv",
        "data/year=2023/month=07/day=02/093000.csv",
    ]


def test_repo_id_is_overridable(hub: list[str]) -> None:
    list_files(repo_id="someone/a-fork")
    assert hub == ["someone/a-fork"]


def test_stream_reads_files_in_order(hub: list[str], downloads: list[str]) -> None:
    events = list(stream(start="2023-07-01", end="2023-07-02"))
    assert [event["query_time"] for event in events] == [
        "2023-07-01T09:00:00",
        "2023-07-02T09:00:00",
        "2023-07-02T09:15:00",
        "2023-07-02T09:30:00",
    ]
    assert events[0]["bikes"] == 12


def test_stream_downloads_one_file_at_a_time(hub: list[str], downloads: list[str]) -> None:
    """The point of the whole design: a caller sees its first row without the
    multi-year history being fetched first."""
    events = stream()
    assert downloads == []
    next(events)
    assert len(downloads) == 1
    # Draining the first file pulls the second, and no more than the second.
    list(islice(events, 1))
    assert len(downloads) == 2


def test_stream_ends_when_the_range_is_exhausted(hub: list[str], downloads: list[str]) -> None:
    assert len(list(stream(start="2023-07-01", end="2023-07-01"))) == 1


def test_stream_loops_forever_when_asked(hub: list[str], downloads: list[str]) -> None:
    """For a demo feed that has to outlive its data."""
    events = list(islice(stream(start="2023-07-01", end="2023-07-01", loop=True), 3))
    assert [event["query_time"] for event in events] == ["2023-07-01T09:00:00"] * 3
    assert len(downloads) == 3


def test_an_empty_range_is_not_an_error(hub: list[str], downloads: list[str], caplog: pytest.LogCaptureFixture) -> None:
    """A window with no data warns and stops; it does not raise, so a replay
    bounded past the end of the dataset exits cleanly."""
    assert list(stream(start="2030-01-01")) == []
    assert downloads == []
    assert "No data files" in caplog.text


def test_local_mirror_is_ordered_like_the_hub(mirror: Path) -> None:
    assert [path.name for path in local_files(mirror)] == [
        "part.csv",
        "part.csv",
        "091500.csv",
        "093000.csv",
    ]


def test_local_mirror_ignores_the_dimension(mirror: Path) -> None:
    assert not any(path.name.startswith("stations") for path in local_files(mirror))


def test_stream_local_matches_stream(mirror: Path) -> None:
    assert [event["query_time"] for event in stream_local(mirror)] == [
        "2023-07-01T09:00:00",
        "2023-07-02T09:00:00",
        "2023-07-02T09:15:00",
        "2023-07-02T09:30:00",
    ]


def test_stream_local_on_an_empty_directory(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert list(stream_local(tmp_path)) == []
    assert "No CSV snapshots" in caplog.text
