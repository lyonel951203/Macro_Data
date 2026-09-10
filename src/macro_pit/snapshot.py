from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import polars as pl

from .pit import get_snapshot
from .timeutils import SHANGHAI


def build_monthly_wide_snapshot(
    conn: duckdb.DuckDBPyConnection,
    output_prefix: str | Path,
    start_date: str,
    end_date: str,
    *,
    country: str = "CN",
    pit_mode: str = "strict",
) -> dict[str, Path]:
    """Build month-end PIT panels with one row per as-of date and one column per series.

    The values panel holds the latest legally available observation value at
    each month end. The periods panel records which source period supplied each
    value, so forward-filled monthly/quarterly information remains explicit.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    month_ends = _month_ends(start, end)
    if not month_ends:
        raise ValueError("date range contains no natural month end")

    final_as_of = f"{month_ends[-1].isoformat()} 23:59:59+08:00"
    final_snapshot = get_snapshot(conn, final_as_of, country=country, pit_mode=pit_mode)
    if final_snapshot.is_empty():
        raise ValueError("no PIT observations are available by end_date")
    final_latest = _latest_series_rows(final_snapshot)
    series_ids = sorted(final_latest.get_column("canonical_series_id").to_list())

    metadata = (
        final_latest.select(
            "canonical_series_id",
            "series_name",
            "source",
            "frequency",
            "unit",
            "seasonal_adjustment",
            "pit_grade",
        )
        .sort("canonical_series_id")
    )
    value_rows: list[dict] = []
    period_rows: list[dict] = []
    for month_end in month_ends:
        as_of = f"{month_end.isoformat()} 23:59:59+08:00"
        snapshot = get_snapshot(conn, as_of, country=country, pit_mode=pit_mode)
        latest = _latest_series_rows(snapshot)
        values = {
            row["canonical_series_id"]: row["value"]
            for row in latest.select("canonical_series_id", "value").iter_rows(named=True)
        }
        periods = {
            row["canonical_series_id"]: row["period"]
            for row in latest.select("canonical_series_id", "period").iter_rows(named=True)
        }
        value_rows.append({"as_of_month_end": month_end, **{key: values.get(key) for key in series_ids}})
        period_rows.append({"as_of_month_end": month_end, **{key: periods.get(key) for key in series_ids}})

    # Long PIT panels can legitimately start with more than Polars' default
    # inference window of all-null rows. Inspect the complete row set so later
    # values/period strings establish the correct column types.
    values_frame = pl.DataFrame(value_rows, infer_schema_length=None)
    periods_frame = pl.DataFrame(period_rows, infer_schema_length=None)
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {
        "values_parquet": prefix.with_name(prefix.name + "_values.parquet"),
        "values_csv": prefix.with_name(prefix.name + "_values.csv"),
        "periods_parquet": prefix.with_name(prefix.name + "_periods.parquet"),
        "metadata_csv": prefix.with_name(prefix.name + "_metadata.csv"),
    }
    values_frame.write_parquet(paths["values_parquet"])
    values_frame.write_csv(paths["values_csv"])
    periods_frame.write_parquet(paths["periods_parquet"])
    metadata.write_csv(paths["metadata_csv"])
    return paths


def build_monthly_snapshots(
    conn: duckdb.DuckDBPyConnection,
    output_dir: str | Path = "data/snapshots",
    start_date: str = "2020-01-31",
    end_date: str | None = None,
    *,
    country: str | None = None,
    pit_mode: str = "strict",
) -> list[Path]:
    """Dynamically build month-end PIT parquet snapshots from vintages."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(start_date)
    if end_date:
        end = date.fromisoformat(end_date)
    else:
        today = datetime.now(SHANGHAI).date()
        end = today.replace(day=1) - timedelta(days=1)

    current = date(start.year, start.month, 1)
    paths: list[Path] = []
    while current <= end:
        month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        if month_end >= start and month_end <= end:
            as_of = f"{month_end.isoformat()} 23:59:59+08:00"
            frame = get_snapshot(conn, as_of, country=country, pit_mode=pit_mode)
            target = output / f"{month_end.isoformat()}.parquet"
            frame.write_parquet(target)
            paths.append(target)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return paths


def _latest_series_rows(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return (
        frame.sort(
            ["canonical_series_id", "period_end", "available_at", "vintage_no"]
        )
        .unique(subset=["canonical_series_id"], keep="last")
        .sort("canonical_series_id")
    )


def _month_ends(start: date, end: date) -> list[date]:
    current = date(start.year, start.month, 1)
    result: list[date] = []
    while current <= end:
        month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        if start <= month_end <= end:
            result.append(month_end)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return result
