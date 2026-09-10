from __future__ import annotations

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
