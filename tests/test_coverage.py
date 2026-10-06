"""Counting snapshots for the contribution graph.

The Hub is not contacted. Commit pages and file listings are handed in.
"""

from __future__ import annotations

from datetime import date
from xml.etree import ElementTree

from london_cycles.coverage import (
    EMPTY,
    SCALE,
    commit_titles_since,
    months_before,
    parse_compact_title,
    render_svg,
    shade,
    snapshot_counts,
)

SVG = "{http://www.w3.org/2000/svg}"


def _rects(svg: str) -> list[ElementTree.Element]:
    root = ElementTree.fromstring(svg)
    return [el for el in root.iter(f"{SVG}rect") if "data-date" in el.attrib]


def test_parse_compact_title() -> None:
    assert parse_compact_title("Compact 2026-10-05 (12 snapshots, 9592 rows, 12 files merged)") == (
        date(2026, 10, 5),
        12,
    )
    assert parse_compact_title("Snapshot 2026-10-06T21:45:26 (799 stations)") is None
    assert parse_compact_title("Compact not-a-date (4 snapshots)") is None


def test_months_before_clamps_to_the_month() -> None:
    assert months_before(date(2026, 10, 6), 3) == date(2026, 7, 6)
    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_before(date(2024, 3, 31), 1) == date(2024, 2, 29)


def test_shade_is_quarters_of_a_full_day() -> None:
    assert shade(0) == EMPTY
    assert shade(1) == shade(24) == SCALE[0]
    assert shade(25) == shade(48) == SCALE[1]
    assert shade(49) == shade(72) == SCALE[2]
    assert shade(73) == shade(96) == shade(120) == SCALE[3]


def test_newest_compact_wins_and_loose_files_add() -> None:
    titles = [
        "Compact 2026-10-05 (12 snapshots, 9592 rows, 12 files merged)",
        "Compact 2026-10-05 (9 snapshots, 1 rows, 9 files merged)",
        "Snapshot 2026-10-05T12:00:00 (799 stations)",
        "Compact 2026-10-04 (22 snapshots, 17578 rows, 22 files merged)",
    ]
    files = [
        "data/year=2026/month=10/day=05/part.csv",
        "data/year=2026/month=10/day=05/130000.csv",
        "data/year=2026/month=10/day=06/090000.csv",
        "data/year=2026/month=10/day=06/091500.csv",
        "stations.csv",
    ]
    counts = snapshot_counts(titles, files, start=date(2026, 10, 4), end=date(2026, 10, 6))
    assert counts == {
        date(2026, 10, 4): 22,
        date(2026, 10, 5): 13,
        date(2026, 10, 6): 2,
    }


def test_compacted_day_without_a_commit_is_blank(caplog) -> None:
    counts = snapshot_counts(
        [],
        ["data/year=2026/month=07/day=01/part.csv"],
        start=date(2026, 7, 1),
        end=date(2026, 7, 2),
    )
    assert counts == {date(2026, 7, 1): None, date(2026, 7, 2): 0}
    assert "no compact commit" in caplog.text


def test_commit_walk_stops_before_the_window() -> None:
    pages = [
        [{"date": "2026-10-06T01:30:00.000Z", "title": "Compact 2026-10-05 (12 snapshots, 1 rows, 12 files merged)"}],
        [
            {"date": "2026-10-05T00:15:00.000Z", "title": "Snapshot 2026-10-05T00:15:00 (1 stations)"},
            {"date": "2026-10-04T23:00:00.000Z", "title": "should not be read"},
        ],
        [{"date": "2026-09-01T00:00:00.000Z", "title": "later page"}],
    ]
    assert commit_titles_since(pages, date(2026, 10, 5)) == [
        "Compact 2026-10-05 (12 snapshots, 1 rows, 12 files merged)",
        "Snapshot 2026-10-05T00:15:00 (1 stations)",
    ]


def test_svg_draws_one_square_per_day_in_range() -> None:
    start, end = date(2026, 10, 6), date(2026, 10, 7)
    svg = render_svg({start: 12, end: 0}, start=start, end=end, full=96)
    rects = {el.attrib["data-date"]: el for el in _rects(svg)}
    assert list(rects) == ["2026-10-06", "2026-10-07"]
    assert rects["2026-10-06"].attrib["fill"] == SCALE[0]
    assert rects["2026-10-06"].attrib["data-count"] == "12"
    assert rects["2026-10-07"].attrib["fill"] == EMPTY
    assert "12 snapshots" in svg
    assert "Oct" in svg
    assert "96 fills a square" in svg


def test_bulk_loaded_day_is_an_empty_box() -> None:
    day = date(2026, 7, 6)
    svg = render_svg({day: None}, start=day, end=day)
    rect = _rects(svg)[0]
    assert rect.attrib["fill"] == "#ffffff"
    assert rect.attrib["stroke"] == "#d0d7de"
    assert "data-count" not in rect.attrib
    assert "not counted" in svg
    assert "Bulk-loaded days are blank." in svg
    assert "0 snapshots" in svg


def test_month_labels_start_at_the_first_drawn_day() -> None:
    start, end = date(2026, 7, 2), date(2026, 8, 31)
    svg = render_svg({}, start=start, end=end)
    root = ElementTree.fromstring(svg)
    labels = [el.text for el in root.iter(f"{SVG}text") if el.attrib.get("class") == "label"]
    assert "Jun" not in labels
    assert "Jul" in labels
    assert "Aug" in labels
