from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import polars as pl

from .pit import get_snapshot, get_work_snapshot
from .timeutils import SHANGHAI


DEFAULT_ESTIMATED_AVAILABILITY = (
    "reports/v2/pit_work_step2_estimated_availability/estimated_available_v1.csv"
)


def build_monthly_wide_snapshot(
    conn: duckdb.DuckDBPyConnection,
    output_prefix: str | Path,
    start_date: str,
    end_date: str,
    *,
    country: str = "CN",
    pit_mode: str = "strict",
    estimated_availability_path: str | Path = DEFAULT_ESTIMATED_AVAILABILITY,
) -> dict[str, Path]:
    """Build month-end PIT panels with one row per as-of date and one column per series.

    The values panel holds the latest legally available observation value at
    each month end. The periods panel records which source period supplied each
    value, so forward-filled monthly/quarterly information remains explicit.

    ``pit_mode="work"`` selects the latest source period visible at each
    cutoff from A/B records and PIT_D terminal values with calibrated estimated
    availability. A documented Wind or observed official-page revision becomes
    a later vintage on its recorded/first-observed date. The work series set
    contains every A/B/Wind/SAFE
    field visible at the final cutoff; a companion panel labels every cell ``work_A`` /
    ``work_B`` / ``work_wind`` / ``work_wind_revision`` /
    ``work_web_revision`` / ``work_safe_d`` /
    blank. Record-level grades are never modified.
    """
    if pit_mode != "work":
        estimated_availability_path = None  # unused in evidence-based modes
    elif not Path(estimated_availability_path).is_file():
        raise ValueError(
            f"work mode requires an estimated-availability sidecar file: "
            f"{estimated_availability_path}"
        )

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    month_ends = _month_ends(start, end)
    if not month_ends:
        raise ValueError("date range contains no natural month end")

    final_as_of = f"{month_ends[-1].isoformat()} 23:59:59+08:00"
    if pit_mode == "work":
        final_snapshot = get_work_snapshot(
            conn, final_as_of, estimated_availability_path, country=country
        )
    else:
        final_snapshot = get_snapshot(
            conn, final_as_of, country=country, pit_mode=pit_mode
        )
    if final_snapshot.is_empty():
        raise ValueError("no PIT observations are available by end_date")
    final_latest = (
        final_snapshot.sort("canonical_series_id")
        if pit_mode == "work"
        else _latest_series_rows(final_snapshot)
    )
    series_ids = sorted(final_latest.get_column("canonical_series_id").to_list())

    metadata_columns = [
        "canonical_series_id",
        "series_name",
        "source",
        "frequency",
        "unit",
        "seasonal_adjustment",
    ]
    if pit_mode == "work":
        metadata = (
            final_latest.select(*metadata_columns, "work_origin")
            .with_columns(
                pl.when(pl.col("work_origin") == "work_A")
                .then(pl.lit("A"))
                .when(pl.col("work_origin") == "work_B")
                .then(pl.lit("B"))
                .otherwise(pl.lit("D"))
                .alias("pit_grade")
            )
            .drop("work_origin")
            .sort("canonical_series_id")
        )
    else:
        metadata = final_latest.select(
            *metadata_columns, "pit_grade"
        ).sort("canonical_series_id")
    value_rows: list[dict] = []
    period_rows: list[dict] = []
    origin_rows: list[dict] = []
    for month_end in month_ends:
        as_of = f"{month_end.isoformat()} 23:59:59+08:00"
        if pit_mode == "work":
            snapshot = get_work_snapshot(
                conn, as_of, estimated_availability_path, country=country
            )
        else:
            snapshot = get_snapshot(conn, as_of, country=country, pit_mode=pit_mode)
        if pit_mode == "work":
            # Work snapshots already return one latest row per series.
            latest = snapshot.sort("canonical_series_id")
        else:
            latest = _latest_series_rows(snapshot)
        rows = {
            row["canonical_series_id"]: row
            for row in latest.iter_rows(named=True)
        }
        value_rows.append(
            {"as_of_month_end": month_end,
             # Round binary float noise (e.g. 2809*0.0001 -> 0.28090000000000004)
             # at the presentation layer; 1e-10 is far below macro precision.
             **{key: round(rows[key]["value"], 10) if key in rows else None
                for key in series_ids}}
        )
        period_rows.append(
            {"as_of_month_end": month_end,
             **{key: rows[key]["period"] if key in rows else None for key in series_ids}}
        )
        if pit_mode == "work":
            origin_rows.append(
                {"as_of_month_end": month_end,
                 **{key: rows[key]["work_origin"] if key in rows else None for key in series_ids}}
            )

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
    if pit_mode == "work":
        provenance_frame = pl.DataFrame(origin_rows, infer_schema_length=None)
        paths["provenance_csv"] = prefix.with_name(prefix.name + "_provenance.csv")
        paths["provenance_parquet"] = prefix.with_name(prefix.name + "_provenance.parquet")
        provenance_frame.write_csv(paths["provenance_csv"])
        provenance_frame.write_parquet(paths["provenance_parquet"])
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
