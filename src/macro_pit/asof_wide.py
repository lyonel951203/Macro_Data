from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time
import json
from pathlib import Path
import re
from typing import Any

import duckdb
import polars as pl

from .snapshot import DEFAULT_ESTIMATED_AVAILABILITY
from .timeutils import SHANGHAI, ensure_aware


SCOPES = ("CN", "US", "GLB")
FREQUENCIES = ("M", "Q")
_SCOPE_SQL = {
    "CN": "country = 'CN'",
    "US": "country = 'US'",
    "GLB": "country NOT IN ('CN', 'US')",
}
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class AsOfWideResult:
    values: pl.DataFrame
    periods: pl.DataFrame
    provenance: pl.DataFrame
    metadata: pl.DataFrame
    selected_long: pl.DataFrame
    as_of_utc: datetime
    as_of_local: datetime
    scope: str
    frequency: str
    index_column: str
    input_mode: str = "database"
    input_reference: str | None = None


def normalize_as_of(value: str | datetime) -> datetime:
    """Normalize T to UTC; a date-only T means Shanghai end-of-day."""
    if isinstance(value, str) and _DATE_ONLY.fullmatch(value.strip()):
        local_date = date.fromisoformat(value.strip())
        value = datetime.combine(local_date, time.max, tzinfo=SHANGHAI)
    return ensure_aware(value)


def build_as_of_wide(
    conn: duckdb.DuckDBPyConnection,
    as_of: str | datetime,
    scope: str,
    *,
    start_date: str = "2005-01-01",
    frequency: str = "M",
    estimated_availability_path: str | Path = DEFAULT_ESTIMATED_AVAILABILITY,
    estimated_rules_path: str | Path = "config/estimated_availability_rules_v1.csv",
) -> AsOfWideResult:
    """Build a fixed-T historical wide table without forward filling.

    For each field and source period, the base value visible by T is selected
    in the explicit order PIT_A, PIT_B, Wind. Within a tier the latest visible
    vintage wins. A documented Wind revision is then applied as a dated event:
    it replaces an older base after its revision date, while a still-later A/B
    vintage can supersede that revision.

    Frequency M returns natural month ends through T's calendar month.
    Frequency Q returns natural quarter ends through T's calendar quarter.
    Monthly observations in a Q table appear only for quarter-end months; no
    averaging, summing, or forward filling is performed. Missing/unreleased
    periods remain null.
    """
    scope = scope.upper()
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(SCOPES)}")
    frequency = frequency.upper()
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of: {', '.join(FREQUENCIES)}")
    start = date.fromisoformat(start_date)
    as_of_utc = normalize_as_of(as_of)
    as_of_local = as_of_utc.astimezone(SHANGHAI)
    output_month = (
        as_of_local.month
        if frequency == "M"
        else ((as_of_local.month - 1) // 3 + 1) * 3
    )
    output_end = date(
        as_of_local.year,
        output_month,
        calendar.monthrange(as_of_local.year, output_month)[1],
    )
    if start > output_end:
        raise ValueError("start_date must not be after T's calendar month")

    scope_sql = _SCOPE_SQL[scope]
    metadata = conn.execute(
        f"""
        SELECT canonical_series_id,
               min(country) AS country,
               string_agg(DISTINCT source, '+' ORDER BY source) AS sources,
               arg_max(series_name, retrieved_at) AS series_name,
               arg_max(frequency, retrieved_at) AS frequency,
               arg_max(unit, retrieved_at) AS unit,
               arg_max(seasonal_adjustment, retrieved_at) AS seasonal_adjustment
        FROM observation_vintage
        WHERE {scope_sql}
        GROUP BY canonical_series_id
        ORDER BY canonical_series_id
        """
    ).pl()
    if metadata.is_empty():
        raise ValueError(f"no fields are registered for scope {scope}")

    wind_base_union = ""
    wind_revision_union = ""
    estimated_d_base_union = ""
    fallback_d_base_union = ""
    documented_revision_union = ""
    parameters: list[Any] = [as_of_utc, start, output_end]
    if scope == "CN":
        sidecar = Path(estimated_availability_path)
        if not sidecar.is_file():
            raise ValueError(
                "CN query requires the Wind estimated-availability sidecar: "
                f"{sidecar}"
            )
        safe_path = str(sidecar.resolve()).replace("'", "''")
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW asof_estimated_availability AS
            SELECT canonical_series_id, source, period,
                   CAST(period_end AS DATE) AS period_end, value,
                   CAST(estimated_available_at AS TIMESTAMPTZ) AS available_at
            FROM read_csv_auto('{safe_path}', header=true)
            WHERE source = 'WIND'
            """
        )
        wind_base_union = """
            UNION ALL
            SELECT m.country, e.canonical_series_id, m.series_name, 'WIND' AS source,
                   m.frequency, m.unit, e.period, e.period_end, e.value,
                   'WIND' AS selection_origin, e.available_at, 0 AS vintage_no,
                   1 AS source_priority, 'D' AS pit_grade,
                   'estimated_availability_sidecar' AS release_date_source
            FROM asof_estimated_availability e
            JOIN (
                SELECT country, canonical_series_id, series_name, frequency, unit
                FROM observation_vintage
                WHERE country = 'CN' AND source = 'WIND'
                QUALIFY row_number() OVER (
                    PARTITION BY canonical_series_id
                    ORDER BY retrieved_at DESC, vintage_no DESC
                ) = 1
            ) m USING (canonical_series_id)
            WHERE e.available_at <= ?
              AND e.period_end BETWEEN ? AND ?
        """
        wind_revision_union = """
            UNION ALL
            SELECT country, canonical_series_id, series_name, source,
                   frequency, unit, period, period_end, value,
                   'WIND_REVISION' AS selection_origin, available_at, vintage_no,
                   1 AS source_priority, pit_grade, release_date_source
            FROM observation_vintage
            WHERE country = 'CN' AND source = 'WIND' AND pit_grade = 'D'
              AND release_date_source LIKE 'wind_revision_snapshot_%'
              AND available_at <= ?
              AND period_end BETWEEN ? AND ?
        """
        fallback_d_base_union = """
            UNION ALL
            SELECT country, canonical_series_id, series_name, source,
                   frequency, unit, period, period_end, value,
                   CASE source
                       WHEN 'EASTMONEY_MACRO' THEN 'EASTMONEY_D'
                       ELSE 'SINA_D'
                   END AS selection_origin,
                   available_at, vintage_no,
                   CASE source WHEN 'EASTMONEY_MACRO' THEN 0 ELSE -1 END
                       AS source_priority,
                   pit_grade, release_date_source
            FROM observation_vintage
            WHERE country = 'CN'
              AND source IN ('EASTMONEY_MACRO', 'SINA_MACRO')
              AND pit_grade = 'D'
              AND release_date_source =
                  'third_party_current_history_first_seen_only'
              AND available_at <= ?
              AND period_end BETWEEN ? AND ?
        """
        parameters.extend([
            as_of_utc, start, output_end,
            as_of_utc, start, output_end,
            as_of_utc, start, output_end,
        ])
    elif scope == "GLB":
        rules = Path(estimated_rules_path)
        if not rules.is_file():
            raise ValueError(
                "GLB query requires estimated-availability rules: "
                f"{rules}"
            )
        safe_rules = str(rules.resolve()).replace("'", "''")
        conn.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW asof_estimated_rules AS
            SELECT canonical_series_id,
                   CAST(lag_days AS INTEGER) AS lag_days,
                   CAST(eligible AS BOOLEAN) AS eligible
            FROM read_csv_auto('{safe_rules}', header=true)
            """
        )
        estimated_d_base_union = """
            UNION ALL
            SELECT country, canonical_series_id, series_name, source,
                   frequency, unit, period, period_end, value,
                   'ESTIMATED_D' AS selection_origin,
                   estimated_available_at AS available_at, vintage_no,
                   1 AS source_priority, pit_grade, release_date_source
            FROM (
                SELECT v.*,
                       CAST(
                           CAST(
                               v.period_end + r.lag_days + 1 AS VARCHAR
                           ) || ' 00:00:00+08:00'
                           AS TIMESTAMPTZ
                       ) AS estimated_available_at
                FROM observation_vintage v
                JOIN asof_estimated_rules r USING (canonical_series_id)
                WHERE v.country = 'GLB'
                  AND v.source = 'IMF'
                  AND v.pit_grade = 'D'
                  AND r.eligible
                  AND v.release_date_source LIKE
                      'imf_current_history_snapshot_%'
                QUALIFY row_number() OVER (
                    PARTITION BY v.canonical_series_id, v.period
                    ORDER BY v.vintage_no DESC, v.retrieved_at DESC
                ) = 1
            ) estimated
            WHERE estimated_available_at <= ?
              AND period_end BETWEEN ? AND ?
        """
        documented_revision_union = """
            UNION ALL
            SELECT country, canonical_series_id, series_name, source,
                   frequency, unit, period, period_end, value,
                   'OBSERVED_WEB_REVISION' AS selection_origin,
                   available_at, vintage_no, 1 AS source_priority,
                   pit_grade, release_date_source
            FROM observation_vintage
            WHERE country = 'GLB' AND source = 'IMF'
              AND pit_grade = 'D'
              AND release_date_source =
                  'official_web_revision_first_seen'
              AND available_at <= ?
              AND period_end BETWEEN ? AND ?
        """
        parameters.extend([
            as_of_utc, start, output_end,
            as_of_utc, start, output_end,
        ])

    selected = conn.execute(
        f"""
        WITH base_candidates AS (
            SELECT country, canonical_series_id, series_name, source,
                   frequency, unit, period, period_end, value,
                   'PIT_' || pit_grade AS selection_origin,
                   available_at, vintage_no,
                   CASE pit_grade WHEN 'A' THEN 3 ELSE 2 END AS source_priority,
                   pit_grade, release_date_source
            FROM observation_vintage
            WHERE {scope_sql}
              AND pit_grade IN ('A', 'B')
              AND available_at <= ?
              AND period_end BETWEEN ? AND ?
            {wind_base_union}
            {fallback_d_base_union}
            {estimated_d_base_union}
        ),
        base AS (
            SELECT * FROM base_candidates
            QUALIFY row_number() OVER (
                PARTITION BY country, canonical_series_id, period
                ORDER BY source_priority DESC, available_at DESC, vintage_no DESC
            ) = 1
        ),
        final_candidates AS (
            SELECT * FROM base
            {wind_revision_union}
            {documented_revision_union}
        )
        SELECT * EXCLUDE (source_priority)
        FROM final_candidates
        QUALIFY row_number() OVER (
            PARTITION BY country, canonical_series_id, period
            ORDER BY available_at DESC, source_priority DESC, vintage_no DESC
        ) = 1
        ORDER BY country, canonical_series_id, period_end
        """,
        parameters,
    ).pl()

    index_ends = _period_ends(start, output_end, frequency)
    index_column = "month_end" if frequency == "M" else "quarter_end"
    selected = selected.filter(pl.col("period_end").is_in(index_ends))
    fields = metadata.get_column("canonical_series_id").to_list()
    chosen = {
        (row["period_end"], row["canonical_series_id"]): row
        for row in selected.iter_rows(named=True)
    }
    values = pl.DataFrame([
        pl.Series(index_column, index_ends, dtype=pl.Date),
        *[
            pl.Series(
                field,
                [
                    round(chosen[(period_end, field)]["value"], 10)
                    if (period_end, field) in chosen else None
                    for period_end in index_ends
                ],
                dtype=pl.Float64,
            )
            for field in fields
        ],
    ])
    periods = pl.DataFrame([
        pl.Series(index_column, index_ends, dtype=pl.Date),
        *[
            pl.Series(
                field,
                [
                    chosen[(period_end, field)]["period"]
                    if (period_end, field) in chosen else None
                    for period_end in index_ends
                ],
                dtype=pl.String,
            )
            for field in fields
        ],
    ])
    provenance = pl.DataFrame([
        pl.Series(index_column, index_ends, dtype=pl.Date),
        *[
            pl.Series(
                field,
                [
                    chosen[(period_end, field)]["selection_origin"]
                    if (period_end, field) in chosen else None
                    for period_end in index_ends
                ],
                dtype=pl.String,
            )
            for field in fields
        ],
    ])
    return AsOfWideResult(
        values=values,
        periods=periods,
        provenance=provenance,
        metadata=metadata,
        selected_long=selected,
        as_of_utc=as_of_utc,
        as_of_local=as_of_local,
        scope=scope,
        frequency=frequency,
        index_column=index_column,
    )


def build_as_of_wide_from_long(
    long_parquet: str | Path,
    as_of: str | datetime,
    scope: str,
    *,
    start_date: str = "2005-01-01",
    frequency: str = "M",
) -> AsOfWideResult:
    """Rebuild a fixed-T wide table from an effective-event long parquet."""
    scope = scope.upper()
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(SCOPES)}")
    frequency = frequency.upper()
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of: {', '.join(FREQUENCIES)}")

    parquet_path = Path(long_parquet)
    if not parquet_path.is_file():
        raise ValueError(f"long parquet does not exist: {parquet_path}")
    start = date.fromisoformat(start_date)
    as_of_utc = normalize_as_of(as_of)
    as_of_local = as_of_utc.astimezone(SHANGHAI)
    output_month = (
        as_of_local.month
        if frequency == "M"
        else ((as_of_local.month - 1) // 3 + 1) * 3
    )
    output_end = date(
        as_of_local.year,
        output_month,
        calendar.monthrange(as_of_local.year, output_month)[1],
    )
    if start > output_end:
        raise ValueError("start_date must not be after the output period")

    safe_path = str(parquet_path.resolve()).replace("'", "''")
    scope_sql = _SCOPE_SQL[scope]
    conn = duckdb.connect(":memory:")
    try:
        metadata = conn.execute(
            f"""
            SELECT canonical_series_id,
                   min(country) AS country,
                   string_agg(DISTINCT source, '+' ORDER BY source) AS sources,
                   arg_max(series_name, valid_from) AS series_name,
                   arg_max(source_frequency, valid_from) AS frequency,
                   arg_max(unit, valid_from) AS unit,
                   arg_max(seasonal_adjustment, valid_from) AS seasonal_adjustment
            FROM read_parquet('{safe_path}')
            WHERE {scope_sql}
            GROUP BY canonical_series_id
            ORDER BY canonical_series_id
            """
        ).pl()
        selected = conn.execute(
            f"""
            SELECT *, valid_from AS available_at
            FROM read_parquet('{safe_path}')
            WHERE {scope_sql}
              AND period_end BETWEEN ? AND ?
              AND valid_from <= ?
              AND (valid_to IS NULL OR ? < valid_to)
            ORDER BY country, canonical_series_id, period_end
            """,
            [start, output_end, as_of_utc, as_of_utc],
        ).pl()
    finally:
        conn.close()

    if metadata.is_empty():
        raise ValueError(
            f"long parquet has no fields for scope {scope}: {parquet_path}"
        )
    duplicates = (
        selected.group_by(["country", "canonical_series_id", "period"])
        .len()
        .filter(pl.col("len") > 1)
    )
    if not duplicates.is_empty():
        raise ValueError(
            "long parquet contains overlapping effective intervals for "
            f"{duplicates.height} field-period keys"
        )

    index_ends = _period_ends(start, output_end, frequency)
    index_column = "month_end" if frequency == "M" else "quarter_end"
    selected = selected.filter(pl.col("period_end").is_in(index_ends))
    fields = metadata.get_column("canonical_series_id").to_list()
    chosen = {
        (row["period_end"], row["canonical_series_id"]): row
        for row in selected.iter_rows(named=True)
    }
    values = pl.DataFrame([
        pl.Series(index_column, index_ends, dtype=pl.Date),
        *[
            pl.Series(
                field,
                [
                    round(chosen[(period_end, field)]["value"], 10)
                    if (period_end, field) in chosen else None
                    for period_end in index_ends
                ],
                dtype=pl.Float64,
            )
            for field in fields
        ],
    ])
    periods = pl.DataFrame([
        pl.Series(index_column, index_ends, dtype=pl.Date),
        *[
            pl.Series(
                field,
                [
                    chosen[(period_end, field)]["period"]
                    if (period_end, field) in chosen else None
                    for period_end in index_ends
                ],
                dtype=pl.String,
            )
            for field in fields
        ],
    ])
    provenance = pl.DataFrame([
        pl.Series(index_column, index_ends, dtype=pl.Date),
        *[
            pl.Series(
                field,
                [
                    chosen[(period_end, field)]["selection_origin"]
                    if (period_end, field) in chosen else None
                    for period_end in index_ends
                ],
                dtype=pl.String,
            )
            for field in fields
        ],
    ])
    return AsOfWideResult(
        values=values,
        periods=periods,
        provenance=provenance,
        metadata=metadata,
        selected_long=selected,
        as_of_utc=as_of_utc,
        as_of_local=as_of_local,
        scope=scope,
        frequency=frequency,
        index_column=index_column,
        input_mode="long_parquet",
        input_reference=str(parquet_path.resolve()),
    )


def export_as_of_wide(
    result: AsOfWideResult,
    output_prefix: str | Path,
) -> dict[str, Path]:
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {
        "values_csv": prefix.with_name(prefix.name + "_values.csv"),
        "values_parquet": prefix.with_name(prefix.name + "_values.parquet"),
        "periods_csv": prefix.with_name(prefix.name + "_periods.csv"),
        "provenance_csv": prefix.with_name(prefix.name + "_provenance.csv"),
        "metadata_csv": prefix.with_name(prefix.name + "_metadata.csv"),
        "selected_long_csv": prefix.with_name(prefix.name + "_selected_long.csv"),
        "query_json": prefix.with_name(prefix.name + "_query.json"),
    }
    result.values.write_csv(paths["values_csv"])
    result.values.write_parquet(paths["values_parquet"])
    result.periods.write_csv(paths["periods_csv"])
    result.provenance.write_csv(paths["provenance_csv"])
    result.metadata.write_csv(paths["metadata_csv"])
    result.selected_long.write_csv(paths["selected_long_csv"])
    payload = {
        "scope": result.scope,
        "input_mode": result.input_mode,
        "input_reference": result.input_reference,
        "as_of_local": result.as_of_local.isoformat(),
        "as_of_utc": result.as_of_utc.isoformat(),
        "frequency": result.frequency,
        "index_column": result.index_column,
        "start_period_end": str(result.values[result.index_column][0]),
        "end_period_end": str(result.values[result.index_column][-1]),
        "rows": result.values.height,
        "fields": result.values.width - 1,
        "selection_priority": ["PIT_A", "PIT_B", "WIND", "EASTMONEY_D", "SINA_D"],
        "within_tier": "latest version with availability <= T",
        "forward_fill": False,
        "wind_revision_rule": "dated revision event overrides an older base after its documented date; a later A/B vintage can supersede it",
    }
    paths["query_json"].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths


def default_output_prefix(
    scope: str,
    as_of: str | datetime,
    frequency: str = "M",
) -> Path:
    local = normalize_as_of(as_of).astimezone(SHANGHAI)
    stamp = local.strftime("%Y-%m-%d_%H%M%S")
    suffix = "" if frequency.upper() == "M" else f"_{frequency.lower()}"
    return Path("data") / "queries" / f"{scope.lower()}_asof_{stamp}{suffix}"


def _period_ends(start: date, end: date, frequency: str) -> list[date]:
    month_ends = _month_ends(start, end)
    if frequency == "M":
        return month_ends
    return [value for value in month_ends if value.month in (3, 6, 9, 12)]


def _month_ends(start: date, end: date) -> list[date]:
    current = date(start.year, start.month, 1)
    result: list[date] = []
    while current <= end:
        month_end = date(
            current.year,
            current.month,
            calendar.monthrange(current.year, current.month)[1],
        )
        if month_end >= start:
            result.append(month_end)
        current = date(
            current.year + (current.month == 12),
            current.month % 12 + 1,
            1,
        )
    return result
