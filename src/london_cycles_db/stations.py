"""Time-versioned station table (a slowly-changing dimension).

The fact rows in ``data/`` deliberately carry no ``lat``/``lon``: those are
station attributes, not measurements, and repeating them on every row was ~40%
of the compressed dataset. They live here instead.

This table is *versioned* rather than current-state because station attributes
are not static. Measured over 2022-2026: 21 of 838 stations changed coordinates
(relocations of up to ~82 m), 34 were retired and 42 added. A current-state
table would mislocate the movers and would have no row at all for the retired
ones, making four years of their fact rows unjoinable.

Each row is valid over ``[valid_from, valid_to)``; an empty ``valid_to`` means
"still current". To resolve a fact row, pick the version of its ``place_id``
whose interval contains the row's ``query_time``.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

STATIONS_FILE = Path("stations.csv")

# Attribute columns, in a fixed order. The original code used
# `list(set(properties))`, whose iteration order varies per process -- that is
# why the 1,560 historical stations-*.csv files all have shuffled headers.
# `locked` is deliberately absent: it is live dock status, not a station
# attribute. Including it produced 32,794 version changes across the history
# (versus 34 for lat/lon), because it flips constantly. If it is ever wanted it
# belongs on the fact rows, at snapshot granularity, not here.
ATTRIBUTES = [
    "common_name",
    "lat",
    "lon",
    "terminal_name",
    "installed",
    "temporary",
    "install_date",
    "removal_date",
]
FIELDNAMES = ["place_id", *ATTRIBUTES, "valid_from", "valid_to"]


def _coords_are_junk(lat, lon):
    """TfL occasionally returns 0,0 for a station (BikePoints_852 did for a
    stretch in 2022). That is missing data, not a relocation to the Gulf of
    Guinea, so it must not open a new version."""
    try:
        return float(lat) == 0.0 and float(lon) == 0.0
    except (TypeError, ValueError):
        return True


EPOCH_DATE_FIELDS = ("install_date", "removal_date")


def _epoch_millis_to_date(value):
    """TfL reports install_date/removal_date as epoch milliseconds, and shifts
    them by exactly one hour across British Summer Time boundaries: measured
    over the history, every single change to these fields was +/- 3,600,000 ms
    (440 down, 439 up), clustered at DST transitions. That is a timezone
    artifact, not a station being reinstalled, so it is reduced to a UTC date.
    """
    text = str(value).strip()
    if not text:
        return ""
    try:
        millis = int(text)
    except ValueError:
        return text
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _normalise(record):
    values = {key: ("" if record.get(key) is None else str(record[key])) for key in ATTRIBUTES}
    for key in EPOCH_DATE_FIELDS:
        values[key] = _epoch_millis_to_date(values[key])
    return values


def read_history(path=STATIONS_FILE):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def write_history(rows, path=STATIONS_FILE):
    # Deterministic order so the file diffs cleanly and uploads are stable.
    rows = sorted(rows, key=lambda r: (int(r["place_id"].rsplit("_", 1)[-1] or 0), r["valid_from"]))
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def apply_observations(history, observed, as_of):
    """Fold one day's observations into the version history.

    ``observed`` maps place_id -> attribute dict. ``as_of`` is an ISO date.
    Returns (rows, changed) where ``changed`` counts opened/closed versions.

    A station that simply stops appearing is *not* closed off: the collection
    is flaky enough (missed runs, API hiccups) that absence is a poor signal of
    retirement, and TfL carries that fact explicitly in ``removal_date``.
    Versions are opened only on a real attribute change.
    """
    rows = [dict(row) for row in history]
    open_row = {r["place_id"]: r for r in rows if not r["valid_to"]}
    changed = 0

    for place_id in sorted(observed):
        incoming = _normalise(observed[place_id])
        current = open_row.get(place_id)

        if current is not None:
            if _coords_are_junk(incoming["lat"], incoming["lon"]):
                # Keep the last known good position rather than recording 0,0.
                incoming["lat"], incoming["lon"] = current["lat"], current["lon"]
            # An absent value means "not observed", not "cleared". Only 1,560 of
            # the 1,581 historical days have a stations-*.csv, and the API can
            # omit fields; treating those as changes-to-empty made every
            # attribute flap '' -> value -> '' and produced ~33k spurious
            # versions. Carry the last known value forward instead.
            for key in ATTRIBUTES:
                if incoming[key] == "":
                    incoming[key] = current[key]

        if current is None:
            if _coords_are_junk(incoming["lat"], incoming["lon"]):
                incoming["lat"], incoming["lon"] = "", ""
            new = {"place_id": place_id, **incoming, "valid_from": as_of, "valid_to": ""}
            rows.append(new)
            open_row[place_id] = new
            changed += 1
            continue

        if all(current[key] == incoming[key] for key in ATTRIBUTES):
            continue

        # Same-day correction: overwrite in place instead of opening a
        # zero-width version that no query could ever select.
        if current["valid_from"] == as_of:
            current.update(incoming)
            continue

        current["valid_to"] = as_of
        new = {"place_id": place_id, **incoming, "valid_from": as_of, "valid_to": ""}
        rows.append(new)
        open_row[place_id] = new
        changed += 1

    return rows, changed


def observations_from_bike_points(bike_points):
    """Build an observation dict from the TfL API response."""
    import re

    camel_to_snake = re.compile(r"(?<!^)(?=[A-Z])")
    observed = {}
    for point in bike_points:
        props = {
            camel_to_snake.sub("_", prop.key).lower(): prop.value
            for prop in point.additionalProperties
            if not prop.key.startswith("Nb")
        }
        observed[point.id] = {
            "common_name": point.commonName,
            "lat": point.lat,
            "lon": point.lon,
            **{key: props.get(key, "") for key in ATTRIBUTES if key not in ("common_name", "lat", "lon")},
        }
    return observed
