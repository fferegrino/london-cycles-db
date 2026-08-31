"""Load the London cycles dataset from the Hugging Face Hub.

    from london_cycles import stream, stations, jitter_events

    for event in jitter_events(stream(start="2023-07-01", end="2023-07-02")):
        ...

`stream` fetches one file at a time and caches under `HF_HOME`, so a range is
usable long before the multi-year history would finish downloading. `stations`
returns the versioned dimension the observations join against, and
`jitter_events` spreads a snapshot's shared `query_time` into something that
looks like a live feed. See each module for the details.
"""

from .dataset import (
    COMPACTED,
    REPO_ID,
    STATIONS_FILE,
    download,
    list_files,
    local_files,
    stream,
    stream_local,
)
from .jitter import DEFAULT_SEED, DEFAULT_SPREAD, jitter_event, jitter_events, jitter_time
from .rows import NUMERIC_FIELDS, coerce_row, read_csv
from .stations import read_stations, stations

__all__ = [
    "COMPACTED",
    "DEFAULT_SEED",
    "DEFAULT_SPREAD",
    "NUMERIC_FIELDS",
    "REPO_ID",
    "STATIONS_FILE",
    "coerce_row",
    "download",
    "jitter_event",
    "jitter_events",
    "jitter_time",
    "list_files",
    "local_files",
    "read_csv",
    "read_stations",
    "stations",
    "stream",
    "stream_local",
]
