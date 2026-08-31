"""Locating and streaming the observations.

The dataset lives on the Hub (`feregrino/london-cycles`), laid out as::

    data/year=YYYY/month=MM/day=DD/part.csv      a finished, compacted day
    data/year=YYYY/month=MM/day=DD/HHMMSS.csv    one 15-minute run, not yet compacted

Files are replayed in chronological order, earliest first. The repo is listed
once and then files are downloaded one at a time: a `snapshot_download` of
`data/**` would pull the whole multi-year history before the caller saw its
first row. Downloads are cached under `HF_HOME`, so a restart re-reads from
disk instead of re-fetching.

The full history is >10^8 rows, so `start`/`end` is usually what you want.
Filtering is by whole day -- a bound selects files, it does not trim rows
inside one -- so a partial day is all-or-nothing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from .rows import read_csv

log = logging.getLogger(__name__)

#: The dataset this library reads. Public, so it can be overridden for a fork.
REPO_ID = "feregrino/london-cycles"

#: The compacted rows of a day, which precede that day's individual runs.
COMPACTED = "part.csv"

#: The versioned station dimension, at the repo root rather than under `data/`.
STATIONS_FILE = "stations.csv"

_PARTITION_RE = re.compile(r"^data/year=(\d{4})/month=(\d{2})/day=(\d{2})/(part\.csv|\d{6}\.csv)$")

#: `start=`/`end=` accept a `date` or an ISO `YYYY-MM-DD` string.
DateLike = date | str | None


def as_date(value: DateLike) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _sort_key(path: str) -> tuple[date, int, str] | None:
    """Chronological position of a data file, or None if it isn't one.

    Sorting the raw path strings would be wrong: `part.csv` sorts *after* the
    `HHMMSS.csv` files, but it holds the earlier, already-compacted rows of the
    same day. The explicit key also gives us the date to filter on.
    """
    match = _PARTITION_RE.match(path)
    if match is None:
        return None
    year, month, day, name = match.groups()
    return date(int(year), int(month), int(day)), (0 if name == COMPACTED else 1), name


def list_files(
    start: DateLike = None,
    end: DateLike = None,
    token: str | None = None,
    repo_id: str = REPO_ID,
) -> list[str]:
    """Every observation file in the repo, earliest first.

    `start` and `end` are inclusive day bounds.
    """
    from huggingface_hub import HfApi

    start, end = as_date(start), as_date(end)
    keyed = []
    for path in HfApi(token=token).list_repo_files(repo_id, repo_type="dataset"):
        key = _sort_key(path)
        if key is None:
            continue
        day = key[0]
        if (start and day < start) or (end and day > end):
            continue
        keyed.append((key, path))
    return [path for _, path in sorted(keyed)]


def download(path: str, token: str | None = None, repo_id: str = REPO_ID) -> str:
    """Local path to one file from the repo, fetching it if it isn't cached."""
    from huggingface_hub import hf_hub_download

    return hf_hub_download(repo_id, path, repo_type="dataset", token=token)


def stream(
    start: DateLike = None,
    end: DateLike = None,
    loop: bool = False,
    token: str | None = None,
    repo_id: str = REPO_ID,
) -> Iterator[dict[str, Any]]:
    """Observations for a date range, earliest first, one file at a time.

    `token` is only needed for a private fork; the cycles dataset is public.
    `loop=True` replays the selected range forever, for a demo feed that
    outlives its data.
    """
    files = list_files(start=start, end=end, token=token, repo_id=repo_id)
    if not files:
        log.warning("No data files in %s for the requested range", repo_id)
        return
    log.info("Replaying %d file(s) from %s, starting with %s", len(files), repo_id, files[0])
    while True:
        for path in files:
            log.info("Reading %s", path)
            yield from read_csv(download(path, token=token, repo_id=repo_id))
        if not loop:
            return


def local_files(directory: str | Path) -> list[Path]:
    """CSV snapshots under `directory`, earliest first.

    Searched recursively, so a local mirror of the Hub's
    `data/year=.../month=.../day=.../` layout works. Within a day, `part.csv`
    must come before that day's `HHMMSS.csv` runs, which a plain path sort
    would get backwards. `stations*.csv` is the dimension, not observations.
    """
    directory = Path(directory)
    paths = [p for p in directory.rglob("*.csv") if not p.name.startswith("stations")]
    return sorted(
        paths,
        key=lambda path: (
            path.parent.relative_to(directory).parts,
            0 if path.name == COMPACTED else 1,
            path.name,
        ),
    )


def stream_local(directory: str | Path, loop: bool = False) -> Iterator[dict[str, Any]]:
    """Observations from a local mirror of the dataset, earliest first."""
    files = local_files(directory)
    if not files:
        log.warning("No CSV snapshots found in %s", directory)
        return
    log.info("Replaying %d snapshot(s) from %s, starting with %s", len(files), directory, files[0].name)
    while True:
        for path in files:
            log.info("Reading %s", path.name)
            yield from read_csv(path)
        if not loop:
            return
