# London's rental bicycle network usage

15-minute snapshots of every docking station in London's cycle hire scheme, collected from the [TfL BikePoint API](https://api.tfl.gov.uk/) since **2022-04-29**.

Data is published to the Hugging Face Hub: **[`feregrino/london-cycles`](https://huggingface.co/datasets/feregrino/london-cycles)**. This repository holds the collection code and the station reference table; it does not hold the observations.

## Layout

```
data/year=YYYY/month=MM/day=DD/part.csv     one row per station per snapshot
stations.csv                                versioned station attributes
```

During the current day you will also see `HHMMSS.csv` files in that day's directory, one per 15-minute run. A nightly job merges them into `part.csv`.

## Fact rows

| column | type | description |
|---|---|---|
| `query_time` | naive UTC timestamp, whole seconds | when the API was queried; identical across all rows of one snapshot |
| `place_id` | string | station identifier, e.g. `BikePoints_1`; joins to `stations.csv` |
| `bikes` | integer | bikes available |
| `empty_docks` | integer | free docks |
| `docks` | integer | total docks |

Rows carry no coordinates. `lat`/`lon` are station attributes rather than measurements, and repeating them on every row was about 40% of the compressed dataset. They live in `stations.csv`.

## `stations.csv`

One row per station per *version* of its attributes, valid over `[valid_from, valid_to)`. An empty `valid_to` means "still current" (it reads as `NULL` in DuckDB, pandas, and friends).

| column | description |
|---|---|
| `place_id` | joins to the fact rows |
| `common_name` | human-readable station name |
| `lat`, `lon` | position during this version's interval |
| `terminal_name` | TfL terminal identifier |
| `installed`, `temporary` | TfL status flags |
| `install_date`, `removal_date` | UTC dates (`YYYY-MM-DD`), or empty |
| `valid_from`, `valid_to` | UTC dates bounding this version |

The table is versioned because station attributes are not static. Over 2022-2026: 34 stations changed coordinates (relocations of up to ~82 m), 31 were renamed, and the set of live stations churned by several dozen. A current-state table would mislocate the movers and would have no row at all for retired stations, making years of their observations unjoinable.

## Joining

Pick the version of each `place_id` whose interval contains the row's `query_time`:

```sql
SELECT f.query_time, f.place_id, s.common_name, s.lat, s.lon,
       f.bikes, f.empty_docks, f.docks
FROM read_csv_auto('data/**/part.csv', hive_partitioning = true) AS f
JOIN read_csv_auto('stations.csv') AS s
  ON s.place_id = f.place_id
 AND s.valid_from <= CAST(f.query_time AS DATE)
 AND (s.valid_to IS NULL OR CAST(f.query_time AS DATE) < s.valid_to)
```

Joining on `place_id` alone will multiply rows for the ~100 stations that have more than one version.

## Known data quirks

These are artifacts of the upstream API, kept documented rather than silently patched:

- **Coordinates of `0,0`.** TfL has reported null-island coordinates for a station (`BikePoints_852`, 2022). These never open a new version; the last known good position is carried forward instead.
- **One-hour shifts in `install_date` / `removal_date`.** TfL reports these as epoch milliseconds and shifts them by exactly 3,600,000 ms across British Summer Time boundaries — every observed change to these fields was ±1 hour. They are reduced to UTC dates, which absorbs the shift except for a handful of values that sit near midnight.
- **Two positions in one day.** During a relocation TfL may report both the old and new position on the same day (`BikePoints_244`, 2025-04-15, 299 m apart). Day-granularity versioning records the majority position, so a small number of observations resolve to the stable location rather than the transient one.
- **Gaps.** Collection depends on GitHub Actions' scheduled runs, which are best-effort. Expect fewer than 96 snapshots on many days; 2026 ran as low as ~16/day before the collection job was repaired. Treat snapshot counts as variable and never assume a fixed cadence.
- **`locked` is not recorded.** It is live dock status rather than a station attribute, and flips constantly (32,794 changes across the history, against 34 for coordinates). It was excluded rather than pollute the version table.

## Running it

```sh
pip install -r requirements-query.txt

export HF_TOKEN=...                          # write access to the dataset repo
export HF_DATASET_REPO=feregrino/london-cycles

python dataset.py                            # publish one snapshot
python compact.py 2026-08-25                 # merge a day's snapshots
python backfill.py --dry-run --out /tmp/out   # migrate historical CSVs, locally
```

`requirements-viz.txt` covers `animate.py` only; those pins are old and need Python 3.10.

## Licence

Data: [CC-BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), per TfL's terms. Powered by TfL Open Data. Contains OS data © Crown copyright and database rights 2016.
