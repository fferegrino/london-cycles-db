"""One-off migration of the existing git-stored CSVs to the Hub.

For each historical day it:
  * trims query_time to whole seconds,
  * drops lat/lon from the fact rows,
  * folds that day's lat/lon and station attributes into stations.csv, so the
    coordinates dropped from the fact rows remain recoverable for every day
    (including for stations that have since been retired),
  * uploads the day as a single compacted file.

Commits are batched, since 1,581 separate commits would be unkind to the Hub.

Usage:
    python backfill.py --dry-run --out /tmp/out    # verify locally, no upload
    python backfill.py                             # upload to the Hub
"""

import argparse
import csv
import io
import os
import re
from datetime import date
from glob import glob
from pathlib import Path

import stations

DAILY_RE = re.compile(r"^data/(\d{4})-(\d{2})-(\d{2})\.csv$")
HEADERS = ["query_time", "place_id", "bikes", "empty_docks", "docks"]
COMMIT_BATCH = 60


def daily_files(data_dir="data"):
    found = []
    for path in sorted(glob(os.path.join(data_dir, "*.csv"))):
        match = DAILY_RE.match(path.replace(os.sep, "/"))
        if match:
            found.append((date(*(int(g) for g in match.groups())), path))
    return found


def station_attributes(day, data_dir="data"):
    """Attributes from that day's stations-*.csv, if one was written."""
    path = Path(data_dir, f"stations-{day.isoformat()}.csv")
    if not path.exists():
        return {}
    with open(path, newline="") as handle:
        return {row["place_id"]: row for row in csv.DictReader(handle) if row.get("place_id")}


def earliest_known_attributes(data_dir="data"):
    """First-ever attribute set per station.

    Collection began 2022-04-29 but the first stations-*.csv is 2022-05-20, so
    the first three weeks have fact rows and no station attributes. Rather than
    emit a version with an empty name for those days (which cost ~850 spurious
    versions, one per station), seed them with the earliest attributes we ever
    saw. Names and terminal ids are stable, so this records what was already
    true rather than inventing it.
    """
    earliest = {}
    for path in sorted(glob(os.path.join(data_dir, "stations-*.csv"))):
        with open(path, newline="") as handle:
            for row in csv.DictReader(handle):
                place_id = row.get("place_id")
                if place_id and place_id not in earliest:
                    earliest[place_id] = row
    return earliest


def convert_day(day, path, data_dir="data", seed=None):
    """Return (csv_text, row_count, observations) for one historical day."""
    attributes = station_attributes(day, data_dir)
    seed = seed or {}
    observed = {}
    rows = []
    seen = set()

    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            place_id = row.get("place_id")
            if not place_id:
                continue
            timestamp = (row.get("query_time") or "")[:19]
            if not timestamp:
                continue
            key = (timestamp, place_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "query_time": timestamp,
                "place_id": place_id,
                "bikes": row.get("bikes", ""),
                "empty_docks": row.get("empty_docks", ""),
                "docks": row.get("docks", ""),
            })
            if place_id not in observed:
                extra = attributes.get(place_id) or seed.get(place_id) or {}
                observed[place_id] = {
                    "common_name": extra.get("common_name", ""),
                    "lat": row.get("lat", ""),
                    "lon": row.get("lon", ""),
                    **{k: extra.get(k, "") for k in stations.ATTRIBUTES
                       if k not in ("common_name", "lat", "lon")},
                }

    rows.sort(key=lambda r: (r["query_time"], r["place_id"]))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue(), len(rows), observed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="write locally instead of uploading")
    parser.add_argument("--out", default="backfill-out", help="output directory for --dry-run")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--limit", type=int, help="only process the first N days (for testing)")
    args = parser.parse_args()

    files = daily_files(args.data_dir)
    if args.limit:
        files = files[: args.limit]
    print(f"{len(files)} day(s) to migrate")

    seed = earliest_known_attributes(args.data_dir)
    print(f"seeded earliest attributes for {len(seed)} station(s)")

    history = []
    pending = []
    totals = {"days": 0, "rows": 0, "in_bytes": 0, "out_bytes": 0}

    if not args.dry_run:
        import hf_publish
        client = hf_publish.api()

    def flush(label):
        nonlocal pending
        if not pending:
            return
        if args.dry_run:
            for path_in_repo, payload in pending:
                target = Path(args.out, path_in_repo)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(payload)
        else:
            hf_publish.commit(
                [hf_publish.add(p, payload) for p, payload in pending],
                f"Backfill {label} ({len(pending)} file(s))",
                client=client,
            )
        pending = []

    for day, path in files:
        payload, count, observed = convert_day(day, path, args.data_dir, seed)
        history, _ = stations.apply_observations(history, observed, day.isoformat())

        path_in_repo = (f"data/year={day.year:04d}/month={day.month:02d}"
                        f"/day={day.day:02d}/part.csv")
        pending.append((path_in_repo, payload))

        totals["days"] += 1
        totals["rows"] += count
        totals["in_bytes"] += os.path.getsize(path)
        totals["out_bytes"] += len(payload)

        if len(pending) >= COMMIT_BATCH:
            flush(f"through {day.isoformat()}")

    flush("final")

    # stations.csv last, so it is never newer than the facts it describes.
    stations_path = Path(args.out, "stations.csv") if args.dry_run else stations.STATIONS_FILE
    stations_path.parent.mkdir(parents=True, exist_ok=True)
    stations.write_history(history, stations_path)
    if not args.dry_run:
        with open(stations_path, newline="") as handle:
            hf_publish.commit([hf_publish.add("stations.csv", handle.read())],
                              f"Station history ({len(history)} versions)", client=client)

    versions = len(history)
    ids = len({row["place_id"] for row in history})
    print(f"\ndays        : {totals['days']:,}")
    print(f"rows        : {totals['rows']:,}")
    print(f"input       : {totals['in_bytes']/1e9:.2f} GB")
    print(f"output      : {totals['out_bytes']/1e9:.2f} GB "
          f"({totals['in_bytes']/max(totals['out_bytes'],1):.2f}x smaller)")
    print(f"stations    : {ids} distinct, {versions} versions "
          f"({versions - ids} attribute change(s) captured)")


if __name__ == "__main__":
    main()
