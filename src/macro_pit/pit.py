from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
import polars as pl

from .timeutils import ensure_aware


PIT_MODES = {
    "strict": ("A", "B"),
    "loose": ("A", "B", "C"),
    "observed": ("A", "B", "C", "D"),
}


def get_snapshot(
    conn: duckdb.DuckDBPyConnection,
    as_of: str,
    country: Optional[str] = None,
    pit_mode: str = "strict",
) -> pl.DataFrame:
    """Return the latest legally available vintage at ``as_of``.

    A timezone-free timestamp is interpreted as Asia/Shanghai for backward
    compatibility. New callers should always provide an explicit offset.
    """
    if pit_mode not in PIT_MODES:
        raise ValueError(f"pit_mode must be one of: {', '.join(PIT_MODES)}")

    allowed_grades = PIT_MODES[pit_mode]
    placeholders = ", ".join("?" for _ in allowed_grades)
    query = f"""
        SELECT *
        FROM observation_vintage
        WHERE available_at <= ?
          AND pit_grade IN ({placeholders})
    """
    parameters: list[object] = [ensure_aware(as_of), *allowed_grades]
    if country:
        query += " AND country = ?"
        parameters.append(country.upper())
    query += """
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY country, canonical_series_id, period
            ORDER BY available_at DESC, vintage_no DESC
        ) = 1
        ORDER BY country, canonical_series_id, period
    """
    return conn.execute(query, parameters).pl()


def get_work_snapshot(
    conn: duckdb.DuckDBPyConnection,
    as_of: str,
    estimated_availability_path: str | Path,
    country: Optional[str] = None,
) -> pl.DataFrame:
    """Return the latest value that would be visible at ``as_of`` per series.

    The latest visible source period wins. Within one period, A/B is preferred
    to an ordinary Wind/SAFE terminal snapshot, whose historical availability
    is estimated in the sidecar. A documented Wind revision or an official page
    revision first observed by the daily crawler is a real later vintage: the
    original A/B value is used before its revision date and the
    revised value afterwards. A still-later official vintage can supersede it.

    Every row carries ``work_origin``: ``work_A`` / ``work_B`` /
    ``work_wind`` / ``work_wind_revision`` / ``work_web_revision`` /
    ``work_safe_d``. Record-level
    evidence grades are never altered. Ordinary D rows use the sidecar;
    documented revisions use their database ``available_at``.

    This is a research view (availability_method=estimated for ordinary D
    records), not strict PIT.
    """
    as_of_ts = ensure_aware(as_of)
    safe_path = str(estimated_availability_path).replace("'", "''")
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW estimated_availability AS
        SELECT canonical_series_id, source, period,
               CAST(period_end AS DATE) AS period_end,
               value,
               CAST(estimated_available_at AS TIMESTAMPTZ) AS estimated_available_at
        FROM read_csv_auto('{safe_path}', header = true)
        """
    )
    query = """
        WITH ab AS (
            SELECT canonical_series_id, series_name, source, frequency, unit,
                   seasonal_adjustment, period, period_end, value, pit_grade,
                   available_at, vintage_no
            FROM observation_vintage
            WHERE pit_grade IN ('A', 'B')
              AND available_at <= ?
            {country_filter}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY canonical_series_id, period
                ORDER BY available_at DESC, vintage_no DESC
            ) = 1
        ),
        documented_revision AS (
            SELECT canonical_series_id, series_name, source, frequency, unit,
                   seasonal_adjustment, period, period_end, value, pit_grade,
                   available_at, vintage_no
            FROM observation_vintage
            WHERE pit_grade = 'D'
              AND (
                    (source = 'WIND'
                     AND release_date_source LIKE 'wind_revision_snapshot_%')
                 OR release_date_source = 'official_web_revision_first_seen'
              )
              AND available_at <= ?
            {revision_country_filter}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY canonical_series_id, period
                ORDER BY available_at DESC, vintage_no DESC
            ) = 1
        ),
        est AS (
            SELECT e.*, v.series_name, v.frequency, v.unit,
                   v.seasonal_adjustment
            FROM estimated_availability e
            LEFT JOIN observation_vintage v
              ON v.canonical_series_id = e.canonical_series_id
             AND v.source = e.source
             AND v.period = e.period
            WHERE e.estimated_available_at <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM ab
                  WHERE ab.canonical_series_id = e.canonical_series_id
                    AND ab.period = e.period
              )
              AND NOT EXISTS (
                  SELECT 1 FROM documented_revision r
                  WHERE r.canonical_series_id = e.canonical_series_id
                    AND r.period = e.period
              )
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY e.canonical_series_id, e.source, e.period,
                             e.period_end, e.value
                ORDER BY v.available_at DESC, v.vintage_no DESC
            ) = 1
        ),
        cand AS (
            SELECT canonical_series_id, series_name, source, frequency, unit,
                   seasonal_adjustment, period, period_end, value,
                   'work_' || pit_grade AS work_origin,
                   available_at, vintage_no,
                   CASE pit_grade WHEN 'A' THEN 3 ELSE 2 END AS source_priority
            FROM ab
            UNION ALL
            SELECT canonical_series_id, series_name, source, frequency, unit,
                   seasonal_adjustment, period, period_end, value,
                   CASE WHEN source = 'WIND'
                        THEN 'work_wind_revision'
                        ELSE 'work_web_revision' END AS work_origin,
                   available_at, vintage_no, 1 AS source_priority
            FROM documented_revision
            UNION ALL
            SELECT e.canonical_series_id,
                   COALESCE(e.series_name, e.canonical_series_id) AS series_name,
                   e.source, e.frequency, e.unit,
                   e.seasonal_adjustment, e.period, e.period_end, e.value,
                   CASE WHEN e.source = 'WIND' THEN 'work_wind' ELSE 'work_safe_d' END,
                   e.estimated_available_at AS available_at,
                   0 AS vintage_no, 0 AS source_priority
            FROM est e
        )
        SELECT * EXCLUDE (source_priority) FROM cand
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY canonical_series_id
            ORDER BY period_end DESC, available_at DESC,
                     source_priority DESC, vintage_no DESC
        ) = 1
        ORDER BY canonical_series_id
    """
    country_filter = ""
    revision_country_filter = ""
    parameters: list[object] = [as_of_ts]
    if country:
        country_filter = "AND country = ?"
        parameters.append(country.upper())
    parameters.append(as_of_ts)
    if country:
        revision_country_filter = "AND country = ?"
        parameters.append(country.upper())
    parameters.append(as_of_ts)
    return conn.execute(
        query.format(
            country_filter=country_filter,
            revision_country_filter=revision_country_filter,
        ),
        parameters,
    ).pl()
