"""Query the TfL bike-point API and publish one snapshot.

Runs every 15 minutes. Each run writes exactly one small immutable file to the
HuggingFace dataset and never rewrites anything, so the work per run does not
grow with the size of the dataset.

Fact rows carry no lat/lon -- those are station attributes and live in the
versioned ``stations.csv`` (see ``src/london_cycles_db/stations.py``). Timestamps are whole seconds:
the old microsecond precision was a single snapshot time stamped onto ~800
rows, so the extra digits were noise rather than resolution.
"""

import csv
import io
from datetime import UTC, datetime

from tfl.api import bike_point

from london_cycles_db import hf_publish, stations

HEADERS = ["query_time", "place_id", "bikes", "empty_docks", "docks"]


def get_number(additional_properties, key):
    """Return the named counter, or None if TfL omitted it.

    The original code destructured (``[nb] = [...]``), which raises ValueError
    when a property is missing -- one newly-installed or broken dock would then
    lose the entire snapshot.
    """
    values = [prop.value for prop in additional_properties if prop.key == key]
    if len(values) != 1:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def snapshot_rows(bike_points, execution_time):
    timestamp = execution_time.isoformat()
    rows, skipped = [], []
    for place in bike_points:
        counts = [get_number(place.additionalProperties, key) for key in ("NbBikes", "NbEmptyDocks", "NbDocks")]
        if any(count is None for count in counts):
            skipped.append(place.id)
            continue
        rows.append((timestamp, place.id, *counts))
    return rows, skipped


def to_csv(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return buffer.getvalue()


def main():
    # Naive UTC, whole seconds -- same shape as the existing history, no
    # +00:00 suffix, and no datetime.utcnow() deprecation warning.
    execution_time = datetime.now(UTC).replace(microsecond=0, tzinfo=None)

    bike_points = bike_point.all()
    if not bike_points:
        raise SystemExit("TfL returned no bike points; refusing to publish an empty snapshot.")

    rows, skipped = snapshot_rows(bike_points, execution_time)
    if skipped:
        print(f"Skipped {len(skipped)} station(s) with incomplete counters: {', '.join(sorted(skipped)[:10])}")
    if not rows:
        raise SystemExit("No usable rows in this snapshot; refusing to publish.")

    operations = [hf_publish.add(hf_publish.snapshot_path(execution_time), to_csv(rows))]

    # Fold today's station attributes into the versioned table, and only
    # re-publish it when something actually changed.
    history = stations.read_history()
    updated, changed = stations.apply_observations(
        history,
        stations.observations_from_bike_points(bike_points),
        execution_time.strftime("%Y-%m-%d"),
    )
    if changed or updated != history:
        stations.write_history(updated)
        with open(stations.STATIONS_FILE, newline="") as handle:
            operations.append(hf_publish.add("stations.csv", handle.read()))
        print(f"stations.csv updated ({changed} version(s) opened)")

    hf_publish.commit(operations, f"Snapshot {execution_time.isoformat()} ({len(rows)} stations)")
    print(f"Published {len(rows)} rows for {execution_time.isoformat()}")


if __name__ == "__main__":
    main()
