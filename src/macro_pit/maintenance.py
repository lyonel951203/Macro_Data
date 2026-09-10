from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import get_connection


@dataclass(frozen=True)
class CompactResult:
    source_rows: int
    target_rows: int
    removed_unchanged_rows: int


@dataclass(frozen=True)
class RebuildResult:
    source_rows: int
    copied_rows: int
    excluded_rows: int


def compact_database(source_path: str | Path, target_path: str | Path) -> CompactResult:
    """Build a new database containing only first values and real changes.

    The source is attached read-only. The function never modifies, deletes or
    replaces the source database.
    """
    source = Path(source_path).resolve()
    target = Path(target_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)

    conn = get_connection(target)
    try:
        escaped_source = str(source).replace("'", "''")
        conn.execute(f"ATTACH '{escaped_source}' AS source_db (READ_ONLY)")
        source_rows = int(conn.execute("SELECT count(*) FROM source_db.observation_vintage").fetchone()[0])
        conn.execute(
            """
            INSERT INTO observation_vintage
            WITH ordered AS (
                SELECT *,
                       lag(value) OVER w AS previous_value,
                       lag(pit_grade) OVER w AS previous_grade,
                       lag(unit) OVER w AS previous_unit,
                       lag(frequency) OVER w AS previous_frequency,
                       row_number() OVER w AS source_order
                FROM source_db.observation_vintage
                WINDOW w AS (
                    PARTITION BY source, canonical_series_id, period
                    ORDER BY available_at, vintage_no, retrieved_at
                )
            ), changes AS (
                SELECT * FROM ordered
                WHERE source_order = 1
                   OR abs(value - previous_value) > 1e-12
                   OR pit_grade <> previous_grade
                   OR unit <> previous_unit
                   OR frequency <> previous_frequency
            ), renumbered AS (
                SELECT *,
                       row_number() OVER w2 - 1 AS new_vintage_no,
                       lag(value) OVER w2 AS previous_kept_value
                FROM changes
                WINDOW w2 AS (
                    PARTITION BY source, canonical_series_id, period
                    ORDER BY available_at, vintage_no, retrieved_at
                )
            )
            SELECT country, source, canonical_series_id, source_series_id,
                   series_name, frequency, unit, seasonal_adjustment, period,
                   period_start, period_end, value, release_at,
                   release_date_source, first_seen_at, available_at,
                   new_vintage_no,
                   CASE
                       WHEN new_vintage_no = 0 THEN 'initial'
                       WHEN abs(value - previous_kept_value) <= 1e-12 THEN 'metadata_update'
                       ELSE 'revision'
                   END,
                   CASE
                       WHEN new_vintage_no = 0 THEN NULL
                       ELSE value - previous_kept_value
                   END,
                   pit_grade, source_url, raw_file, raw_sha256, retrieved_at,
                   parser_version
            FROM renumbered
            ORDER BY source, canonical_series_id, period, new_vintage_no
            """
        )
        source_tables = {row[0] for row in conn.execute("SHOW TABLES FROM source_db").fetchall()}
        if "crawl_log" in source_tables:
            conn.execute("INSERT INTO crawl_log SELECT * FROM source_db.crawl_log")
        if "validation_result" in source_tables:
            conn.execute("INSERT INTO validation_result SELECT * FROM source_db.validation_result")
        target_rows = int(conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0])
        conn.execute("CHECKPOINT")
        conn.execute("DETACH source_db")
        return CompactResult(source_rows, target_rows, source_rows - target_rows)
    finally:
        conn.close()


def rebuild_excluding_sources(
    source_path: str | Path,
    target_path: str | Path,
    excluded_sources: set[str],
) -> RebuildResult:
    """Copy a database while omitting sources that must be reparsed from raw."""
    source = Path(source_path).resolve()
    target = Path(target_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    excluded = {value.upper() for value in excluded_sources}
    if not excluded:
        raise ValueError("excluded_sources cannot be empty")

    conn = get_connection(target)
    try:
        escaped_source = str(source).replace("'", "''")
        conn.execute(f"ATTACH '{escaped_source}' AS source_db (READ_ONLY)")
        source_rows = int(conn.execute("SELECT count(*) FROM source_db.observation_vintage").fetchone()[0])
        placeholders = ", ".join("?" for _ in excluded)
        conn.execute(
            f"INSERT INTO observation_vintage SELECT * FROM source_db.observation_vintage WHERE upper(source) NOT IN ({placeholders})",
            sorted(excluded),
        )
        source_tables = {row[0] for row in conn.execute("SHOW TABLES FROM source_db").fetchall()}
        if "crawl_log" in source_tables:
            conn.execute("INSERT INTO crawl_log SELECT * FROM source_db.crawl_log")
        if "validation_result" in source_tables:
            conn.execute("INSERT INTO validation_result SELECT * FROM source_db.validation_result")
        copied_rows = int(conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0])
        conn.execute("CHECKPOINT")
        conn.execute("DETACH source_db")
        return RebuildResult(source_rows, copied_rows, source_rows - copied_rows)
    finally:
        conn.close()
