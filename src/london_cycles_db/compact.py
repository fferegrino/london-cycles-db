"""Compact a day's snapshot files into a single file on the Hub.

The 15-minute job writes one small file per run, which keeps appends cheap but
would accumulate ~35k files a year. This job folds a finished day into one
file. It runs as a *single* commit that adds the compacted file and deletes the
snapshots together, so there is no window in which the day's data is missing or
duplicated.

Usage:  python -m london_cycles_db.compact [YYYY-MM-DD ...]
Default: yesterday (UTC), since today is still accumulating snapshots.
"""

import csv
import io
import re
import sys
from datetime import datetime, timedelta, timezone

from huggingface_hub import hf_hub_download

from london_cycles_db import hf_publish
from london_cycles_db.dataset import HEADERS

COMPACTED = "part.csv"
SNAPSHOT_RE = re.compile(r"^\d{6}\.csv$")


def day_prefix(day):
    return f"data/year={day.year:04d}/month={day.month:02d}/day={day.day:02d}/"


def day_files(client, prefix):
    return sorted(
        path for path in client.list_repo_files(hf_publish.REPO_ID, repo_type="dataset") if path.startswith(prefix)
    )


def read_remote(path):
    local = hf_hub_download(hf_publish.REPO_ID, path, repo_type="dataset")
    with open(local, newline="") as handle:
        return list(csv.DictReader(handle))


def compact(day, client):
    prefix = day_prefix(day)
    paths = day_files(client, prefix)
    snapshots = [p for p in paths if SNAPSHOT_RE.match(p[len(prefix) :])]
    existing = [p for p in paths if p[len(prefix) :] == COMPACTED]

    if not snapshots:
        print(f"{day}: nothing to compact ({len(paths)} file(s) present)")
        return

    rows = {}
    for path in existing + snapshots:
        for row in read_remote(path):
            # Keyed so a re-run, or a retried snapshot, cannot duplicate rows.
            rows[(row["query_time"], row["place_id"])] = row

    ordered = [rows[key] for key in sorted(rows)]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADERS)
    writer.writeheader()
    writer.writerows(ordered)

    operations = [hf_publish.add(prefix + COMPACTED, buffer.getvalue())]
    operations += [hf_publish.delete(path) for path in snapshots]

    snapshot_count = len({row["query_time"] for row in ordered})
    hf_publish.commit(
        operations,
        f"Compact {day} ({snapshot_count} snapshots, {len(ordered)} rows, {len(snapshots)} files merged)",
        client=client,
    )
    print(
        f"{day}: merged {len(snapshots)} file(s) -> {COMPACTED} " f"({snapshot_count} snapshots, {len(ordered)} rows)"
    )


def main(argv):
    if argv:
        days = [datetime.strptime(arg, "%Y-%m-%d").date() for arg in argv]
    else:
        days = [(datetime.now(timezone.utc) - timedelta(days=1)).date()]

    client = hf_publish.api()
    for day in days:
        compact(day, client)


if __name__ == "__main__":
    main(sys.argv[1:])
