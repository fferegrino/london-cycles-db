"""The station dimension.

`stations.csv` is a slowly-changing dimension: one row per station per
*version* of its attributes, valid over `[valid_from, valid_to)`. A station
that moves, is renamed, or is retired gains a new row rather than overwriting
the old one, so a fact row from 2022 can still be resolved against the
attributes that were true at its `query_time`.

Versions are returned as stored, both bounds included. `valid_to` is empty on
the version that is currently in force -- 116 of 963 rows have a closed
interval at the time of writing -- and `None` here. Consumers that publish
this as a changelog to a versioned table will want to drop `valid_to` and let
the next version's `valid_from` end the previous one; that is their call to
make, not this loader's.
"""

from __future__ import annotations

import csv
import logging
from typing import Any

from .dataset import REPO_ID, STATIONS_FILE, download

log = logging.getLogger(__name__)

#: Columns parsed out of their string form. The rest pass through as text,
#: with blanks as `None`.
_FLOAT_FIELDS = frozenset({"lat", "lon"})
_BOOL_FIELDS = frozenset({"installed", "temporary"})


def _coerce(key: str, raw: str) -> Any:
    value = (raw or "").strip()
    if not value:
        return None
    if key in _FLOAT_FIELDS:
        try:
            return float(value)
        except ValueError:
            log.debug("Could not parse %s=%r as float", key, value)
            return None
    if key in _BOOL_FIELDS:
        return value.lower() == "true"
    return value


def read_stations(path: str) -> list[dict[str, Any]]:
    """Every version in a `stations.csv`, oldest first.

    Sorted by `(valid_from, place_id)` rather than left in file order: anything
    replaying the dimension as a log needs the versions to arrive in the order
    they became true, and the tie-break on `place_id` makes the result stable
    across reads.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    versions = [{key: _coerce(key, raw) for key, raw in row.items() if key is not None} for row in rows]
    versions.sort(key=lambda row: (row["valid_from"] or "", row["place_id"] or ""))
    return versions


def stations(token: str | None = None, repo_id: str = REPO_ID) -> list[dict[str, Any]]:
    """The dimension from the Hub, oldest version first.

    Small enough (a thousand rows) to hand back as a list rather than an
    iterator, which is what makes an as-of join against it practical in memory.
    """
    versions = read_stations(download(STATIONS_FILE, token=token, repo_id=repo_id))
    log.info(
        "Loaded %d version(s) of %d station(s)",
        len(versions),
        len({row["place_id"] for row in versions}),
    )
    return versions
