"""A GitHub-style calendar of how many snapshots each day actually holds.

Finished days are counted from the compact commit title, which already records
the deduped total (`Compact 2026-10-05 (12 snapshots, ...)`). The day still in
progress has no such commit; its count is the number of `HHMMSS.csv` files
still in that day's directory. A day that was compacted and then gained more
snapshots contributes both.

Commit history is walked newest-first and stops at the start of the window, so
a three-month graph does not page back through the whole archive. Days loaded
in bulk have a `part.csv` and no compact commit; those are left blank.
"""

from __future__ import annotations

import argparse
import calendar
import logging
import math
import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .dataset import COMPACTED, REPO_ID, _sort_key, list_files

log = logging.getLogger(__name__)

#: A day of 15-minute polls. The colour scale fills at this count.
FULL_DAY = 96

#: Empty, then four greens. Same ramp as GitHub's contribution graph.
EMPTY = "#ebedf0"
SCALE = ("#9be9a8", "#40c463", "#30a14e", "#216e39")

_COMPACT_PREFIX = "Compact "
_SNAPSHOT_NAME = 6  # HHMMSS.csv

_CELL = 13
_GAP = 3
_STRIDE = _CELL + _GAP


def months_before(day: date, months: int) -> date:
    """The same day of the month, `months` earlier, clamped to the month's length."""
    if months < 0:
        raise ValueError("months must be >= 0")
    index = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def parse_compact_title(title: str) -> tuple[date, int] | None:
    """`(day, snapshots)` from a compact commit title, or None if it isn't one."""
    if not title.startswith(_COMPACT_PREFIX):
        return None
    rest = title[len(_COMPACT_PREFIX) :]
    day_text, _, tail = rest.partition(" ")
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        return None
    if not tail.startswith("("):
        return None
    count_text, _, _ = tail[1:].partition(" ")
    if not count_text.isdigit():
        return None
    return day, int(count_text)


def shade_index(count: int, full: int = FULL_DAY) -> int:
    """0 for no snapshots, 1–4 for quarters of a full day, 4 once `full` is reached."""
    if count <= 0:
        return 0
    if full <= 0:
        return len(SCALE)
    return min(len(SCALE), max(1, math.ceil(count / full * len(SCALE))))


def shade(count: int, full: int = FULL_DAY) -> str:
    index = shade_index(count, full)
    return EMPTY if index == 0 else SCALE[index - 1]


def commit_titles_since(pages: Iterable[Sequence[Mapping[str, Any]]], since: date) -> list[str]:
    """Titles from newest-first commit pages, stopping once commits fall before `since`.

    `since` is compared to the commit's own timestamp, not the day named in the
    title. A compact of `since` is committed the morning after, so it is kept;
    everything older than `since` is not read.
    """
    titles: list[str] = []
    for page in pages:
        for item in page:
            created = date.fromisoformat(str(item["date"])[:10])
            if created < since:
                return titles
            titles.append(item.get("title") or "")
    return titles


def snapshot_counts(
    titles: Iterable[str],
    files: Iterable[str],
    *,
    start: date,
    end: date,
) -> dict[date, int | None]:
    """Snapshots per day in `[start, end]`, inclusive.

    `titles` must be newest first: a day compacted twice keeps the later total.
    Loose `HHMMSS.csv` files are added on top, which is what a re-opened day
    looks like after the nightly compact.
    """
    if end < start:
        raise ValueError(f"start {start} is after end {end}")

    compact: dict[date, int] = {}
    for title in titles:
        parsed = parse_compact_title(title)
        if parsed is None:
            continue
        day, count = parsed
        if day < start or day > end or day in compact:
            continue
        compact[day] = count

    loose: dict[date, int] = {}
    compacted_files: set[date] = set()
    for path in files:
        key = _sort_key(path)
        if key is None:
            continue
        day, _, name = key
        if day < start or day > end:
            continue
        if name == COMPACTED:
            compacted_files.add(day)
        elif len(name) == _SNAPSHOT_NAME + 4 and name.endswith(".csv") and name[:_SNAPSHOT_NAME].isdigit():
            loose[day] = loose.get(day, 0) + 1

    uncounted = sorted(day for day in compacted_files if day not in compact)
    if uncounted:
        log.warning(
            "%d compacted day(s) have no compact commit to count, starting with %s",
            len(uncounted),
            uncounted[0],
        )

    counts: dict[date, int | None] = {}
    day = start
    while day <= end:
        # A part.csv with no compact commit was loaded in bulk. Leave it blank
        # rather than painting a zero over data that is actually there.
        if day in compacted_files and day not in compact:
            counts[day] = None
        else:
            counts[day] = compact.get(day, 0) + loose.get(day, 0)
        day += timedelta(days=1)
    return counts


def _weeks(start: date, end: date) -> list[date]:
    """Monday of each week that touches `[start, end]`."""
    monday = start - timedelta(days=start.weekday())
    last = end - timedelta(days=end.weekday())
    weeks = []
    while monday <= last:
        weeks.append(monday)
        monday += timedelta(days=7)
    return weeks


def _month_labels(weeks: Sequence[date], start: date) -> list[tuple[int, str]]:
    """Column index and short month name, skipping a label that would collide."""
    labels: list[tuple[int, str]] = []
    previous: str | None = None
    last_column = -10
    for column, monday in enumerate(weeks):
        # The first column's Monday can precede `start`; its squares are not drawn.
        name = max(monday, start).strftime("%b")
        if name == previous:
            continue
        previous = name
        if column - last_column < 2:
            continue
        labels.append((column, name))
        last_column = column
    return labels


def _text_width(text: str, size: int) -> int:
    """A conservative width so a caption is not clipped by the grid."""
    return math.ceil(len(text) * size * 0.62)


def render_svg(
    counts: Mapping[date, int | None],
    *,
    start: date,
    end: date,
    full: int = FULL_DAY,
) -> str:
    """The contribution graph for `[start, end]` as an SVG document.

    A count of None is a day whose file was loaded in bulk, with no compact
    commit to count. It is drawn as an empty box, not as zero snapshots.
    """
    weeks = _weeks(start, end)
    grid_w = len(weeks) * _STRIDE - _GAP
    grid_h = 7 * _STRIDE - _GAP

    total = sum(count for count in counts.values() if count)
    date_line = f"{_long(start)} – {_long(end)} · {total:,} snapshots"
    note = "Bulk-loaded days are blank."
    unknown = any(counts.get(day) is None for day in _days(start, end))
    caption_lines = [date_line, note] if unknown else [date_line]

    pad_x, pad_y = 16, 14
    label_w = 28
    title = "Snapshots collected"
    origin_x = pad_x + label_w
    origin_y = pad_y + 18 + 16 * len(caption_lines) + 16
    legend_y = origin_y + grid_h + 16
    legend = f"More · {full} fills a square"
    legend_end = origin_x + 28 + 5 * 13 + 4 + _text_width(legend, 9)
    width = max(
        origin_x + grid_w + pad_x,
        legend_end + pad_x,
        pad_x + _text_width(title, 14) + pad_x,
        *(pad_x + _text_width(line, 12) + pad_x for line in caption_lines),
    )
    height = legend_y + 14 + pad_y

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
        ),
        f"<title>{title}</title>",
        f"<desc>{escape(date_line)}</desc>",
        "<style>",
        "  text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }",
        "  .title { font-size: 14px; font-weight: 600; fill: #1f2328; }",
        "  .sub { font-size: 12px; fill: #656d76; }",
        "  .label { font-size: 9px; fill: #656d76; }",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="8" fill="#ffffff"/>',
        f'<text class="title" x="{pad_x}" y="{pad_y + 12}">{title}</text>',
    ]
    for index, line in enumerate(caption_lines):
        y = pad_y + 30 + index * 16
        parts.append(f'<text class="sub" x="{pad_x}" y="{y}">{escape(line)}</text>')

    for column, name in _month_labels(weeks, start):
        x = origin_x + column * _STRIDE
        parts.append(f'<text class="label" x="{x}" y="{origin_y - 6}">{name}</text>')

    for row, name in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
        y = origin_y + row * _STRIDE + _CELL / 2
        parts.append(f'<text class="label" x="{pad_x}" y="{y}" dominant-baseline="central">{name}</text>')

    for column, monday in enumerate(weeks):
        for row in range(7):
            day = monday + timedelta(days=row)
            if day < start or day > end:
                continue
            count = counts.get(day, 0)
            x = origin_x + column * _STRIDE
            y = origin_y + row * _STRIDE
            if count is None:
                tip = f"{day.isoformat()}: not counted"
                square = (
                    f'<rect x="{x}" y="{y}" width="{_CELL}" height="{_CELL}" rx="2" '
                    f'fill="#ffffff" stroke="#d0d7de" stroke-width="1" data-date="{day.isoformat()}">'
                )
            else:
                noun = "snapshot" if count == 1 else "snapshots"
                tip = f"{day.isoformat()}: no snapshots" if count == 0 else f"{day.isoformat()}: {count} {noun}"
                square = (
                    f'<rect x="{x}" y="{y}" width="{_CELL}" height="{_CELL}" rx="2" '
                    f'fill="{shade(count, full)}" data-date="{day.isoformat()}" data-count="{count}">'
                )
            parts.append(f"{square}<title>{escape(tip)}</title></rect>")

    legend_y_sq = legend_y
    cursor = origin_x
    parts.append(f'<text class="label" x="{cursor}" y="{legend_y_sq + 5}" dominant-baseline="central">Less</text>')
    cursor += 28
    for color in (EMPTY, *SCALE):
        parts.append(f'<rect x="{cursor}" y="{legend_y_sq}" width="10" height="10" rx="2" fill="{color}"/>')
        cursor += 13
    parts.append(
        f'<text class="label" x="{cursor + 4}" y="{legend_y_sq + 5}" dominant-baseline="central">{legend}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _long(day: date) -> str:
    return f"{day.day} {day:%b} {day:%Y}"


def iter_commit_pages(repo_id: str = REPO_ID, token: str | None = None) -> Iterator[list[dict[str, Any]]]:
    """Commit pages from the dataset repo, newest first."""
    from huggingface_hub.constants import ENDPOINT
    from huggingface_hub.utils import build_hf_headers, get_session, hf_raise_for_status

    headers = build_hf_headers(token=token)
    session = get_session()
    url: str | None = f"{ENDPOINT}/api/datasets/{repo_id}/commits/main"
    while url:
        response = session.get(url, headers=headers)
        hf_raise_for_status(response)
        page = response.json()
        if not isinstance(page, list):
            raise TypeError(f"Unexpected commit listing from {url}")
        log.debug("Read %d commit(s)", len(page))
        yield page
        if not page:
            return
        url = response.links.get("next", {}).get("url")


def collect_snapshot_counts(
    start: date,
    end: date,
    *,
    repo_id: str = REPO_ID,
    token: str | None = None,
) -> dict[date, int | None]:
    """Snapshot counts for `[start, end]` from the Hub.

    None is a bulk-loaded day: the file is there, and no compact commit records
    how many snapshots went into it.
    """
    titles = commit_titles_since(iter_commit_pages(repo_id, token=token), start)
    files = list_files(start=start, end=end, token=token, repo_id=repo_id)
    return snapshot_counts(titles, files, start=start, end=end)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in ("huggingface_hub", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Draw a snapshot contribution graph from the Hub.")
    parser.add_argument("--months", type=int, default=3, help="how far back from --end (default: 3)")
    parser.add_argument("--start", help="inclusive YYYY-MM-DD; overrides --months")
    parser.add_argument("--end", help="inclusive YYYY-MM-DD (default: yesterday, UTC)")
    parser.add_argument("--full", type=int, default=FULL_DAY, help="snapshots that fill a square (default: 96)")
    parser.add_argument("--repo", default=os.environ.get("HF_DATASET_REPO") or REPO_ID)
    parser.add_argument("--output", type=Path, default=Path("viz/coverage.svg"))
    args = parser.parse_args(argv)

    if args.months < 0:
        raise SystemExit("--months must be >= 0")
    if args.full < 1:
        raise SystemExit("--full must be >= 1")

    # Today is still being collected, so its square would always look nearly empty.
    end = date.fromisoformat(args.end) if args.end else datetime.now(UTC).date() - timedelta(days=1)
    start = date.fromisoformat(args.start) if args.start else months_before(end, args.months)
    if start > end:
        raise SystemExit(f"--start {start} is after --end {end}")

    token = os.environ.get("HF_TOKEN") or None
    counts = collect_snapshot_counts(start, end, repo_id=args.repo, token=token)
    svg = render_svg(counts, start=start, end=end, full=args.full)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    total = sum(count or 0 for count in counts.values())
    blank = sum(count is None for count in counts.values())
    detail = f"{total:,} snapshots" + (f", {blank} days blank" if blank else "")
    log.info("%s to %s: %s, wrote %s", start, end, detail, args.output)


if __name__ == "__main__":
    main()
