"""Reading rows out of a cycles CSV snapshot.

One row per station per poll. The columns are fixed by how the history was
collected, so the numeric ones are known up front rather than sniffed: an
empty string means "not reported", which is a different thing from zero and
has to survive as `None`.

Fact rows carry no coordinates -- `lat`/`lon`/`common_name` are station
attributes and live in the versioned `stations.csv`. See `stations.py`.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Columns that should come back as numbers rather than strings.
NUMERIC_FIELDS: dict[str, type] = {
    "bikes": int,
    "empty_docks": int,
    "docks": int,
}


def coerce_row(row: dict[str, str]) -> dict[str, Any]:
    """One CSV row as an event: numbers parsed, blanks as `None`."""
    event: dict[str, Any] = {}
    for key, raw in row.items():
        if key is None:
            continue
        value = (raw or "").strip()
        cast = NUMERIC_FIELDS.get(key)
        if cast is not None and value:
            try:
                event[key] = cast(value)
                continue
            except ValueError:
                log.debug("Could not parse %s=%r as %s", key, value, cast.__name__)
        event[key] = value or None
    return event


def read_csv(path: str | Path) -> Iterator[dict[str, Any]]:
    """Stream one event per row of a cycles CSV snapshot."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            yield coerce_row(row)
