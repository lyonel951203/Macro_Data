from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb
import polars as pl

from .errors import DataContractError
from .timeutils import ensure_aware


DB_PATH = os.environ.get("MACRO_PIT_DB_PATH", "macro_pit_v2.duckdb")

OBSERVATION_COLUMNS = [
    "country", "source", "canonical_series_id", "source_series_id",
    "series_name", "frequency", "unit", "seasonal_adjustment", "period",
    "period_start", "period_end", "value", "release_at",
    "release_date_source", "first_seen_at", "available_at", "vintage_no",
    "revision_type", "revision_delta", "pit_grade", "source_url",
    "raw_file", "raw_sha256", "retrieved_at", "parser_version",
]

REQUIRED_INPUT_COLUMNS = {
    "country", "source", "canonical_series_id", "source_series_id",
    "series_name", "frequency", "unit", "period", "period_start",
    "period_end", "value", "first_seen_at", "available_at", "pit_grade",
    "source_url", "raw_file", "raw_sha256", "retrieved_at",
    "parser_version",
}


@dataclass(frozen=True)
class InsertStats:
    inserted: int = 0
    revisions: int = 0
    metadata_updates: int = 0
    unchanged: int = 0


def get_connection(db_path: str | Path = DB_PATH, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        _init_db(conn)
    return conn


def _init_db(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observation_vintage (
            country VARCHAR NOT NULL,
            source VARCHAR NOT NULL,
            canonical_series_id VARCHAR NOT NULL,
            source_series_id VARCHAR NOT NULL,
            series_name VARCHAR NOT NULL,
            frequency VARCHAR NOT NULL,
            unit VARCHAR NOT NULL,
            seasonal_adjustment VARCHAR,
            period VARCHAR NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            value DOUBLE NOT NULL,
            release_at TIMESTAMPTZ,
            release_date_source VARCHAR,
            first_seen_at TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ NOT NULL,
            vintage_no INTEGER NOT NULL,
            revision_type VARCHAR NOT NULL,
            revision_delta DOUBLE,
            pit_grade VARCHAR NOT NULL CHECK (pit_grade IN ('A', 'B', 'C', 'D')),
            source_url VARCHAR NOT NULL,
            raw_file VARCHAR NOT NULL,
            raw_sha256 VARCHAR NOT NULL,
            retrieved_at TIMESTAMPTZ NOT NULL,
            parser_version VARCHAR NOT NULL
        )
        """
    )

    # Never mix repaired timezone-aware rows into a populated prototype table
    # whose timestamps were stored without timezone information.
    described = conn.execute("DESCRIBE observation_vintage").fetchall()
    types = {row[0]: str(row[1]).upper() for row in described}
    naive_fields = [
        field for field in ("release_at", "first_seen_at", "available_at", "retrieved_at")
        if "WITH TIME ZONE" not in types.get(field, "")
    ]
    if naive_fields:
        count = int(conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0])
        if count:
            raise DataContractError(
                "legacy database has populated timezone-naive timestamps; use a new --db-path "
                "and rebuild from verified raw files instead of mixing schemas"
            )
        for field in naive_fields:
            conn.execute(
                f"ALTER TABLE observation_vintage ALTER COLUMN {field} TYPE TIMESTAMPTZ "
                f"USING {field} AT TIME ZONE 'Asia/Shanghai'"
            )

    # Non-destructive migration for empty prototype databases.
    columns = set(types)
    if "revision_delta" not in columns:
        conn.execute("ALTER TABLE observation_vintage ADD COLUMN revision_delta DOUBLE")

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_obs_vintage
        ON observation_vintage (canonical_series_id, period, available_at, vintage_no)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_log (
            crawl_id VARCHAR PRIMARY KEY,
            source VARCHAR NOT NULL,
            url VARCHAR NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            http_status INTEGER,
            success BOOLEAN NOT NULL,
            from_cache BOOLEAN NOT NULL,
            content_type VARCHAR,
            response_bytes BIGINT,
            raw_file VARCHAR,
            raw_sha256 VARCHAR,
            parser_version VARCHAR,
            error_type VARCHAR,
            error_message VARCHAR,
            runtime_seconds DOUBLE NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS validation_result (
            validation_id VARCHAR PRIMARY KEY,
            source VARCHAR NOT NULL,
            test_name VARCHAR NOT NULL,
            sample_size INTEGER NOT NULL,
            matches INTEGER NOT NULL,
            match_rate DOUBLE NOT NULL,
            raw_sha256 VARCHAR,
            created_at TIMESTAMPTZ NOT NULL,
            detail VARCHAR
        )
        """
    )


def _records(df: pl.DataFrame | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(df, pl.DataFrame):
        return df.to_dicts()
    return [dict(row) for row in df]


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(name for name in REQUIRED_INPUT_COLUMNS if name not in row or row[name] is None)
    if missing:
        raise DataContractError(f"missing required observation fields: {', '.join(missing)}")

    grade = str(row["pit_grade"]).upper()
    if grade not in {"A", "B", "C", "D"}:
        raise DataContractError(f"invalid pit_grade: {grade}")
    if grade in {"A", "B", "C"} and not row.get("release_at"):
        raise DataContractError(f"PIT_{grade} requires release_at")
    if grade in {"A", "B"} and str(row.get("raw_sha256", "")).strip() in {"", "N/A", "..."}:
        raise DataContractError(f"PIT_{grade} requires a real raw_sha256")

    value = float(row["value"])
    if not math.isfinite(value):
        raise DataContractError("value must be finite")

    normalized = dict(row)
    normalized["country"] = str(row["country"]).upper()
    normalized["source"] = str(row["source"]).upper()
    normalized["pit_grade"] = grade
    normalized["value"] = value
    normalized["period_start"] = _as_date(row["period_start"])
    normalized["period_end"] = _as_date(row["period_end"])
    normalized["release_at"] = ensure_aware(row["release_at"]) if row.get("release_at") else None
    normalized["first_seen_at"] = ensure_aware(row["first_seen_at"])
    normalized["available_at"] = ensure_aware(row["available_at"])
    normalized["retrieved_at"] = ensure_aware(row["retrieved_at"])
    normalized["seasonal_adjustment"] = row.get("seasonal_adjustment")
    normalized["release_date_source"] = row.get("release_date_source")

    if grade == "D" and normalized["available_at"] < normalized["first_seen_at"]:
        # Documented-version exception: Wind terminal-EDB historical-revision
        # snapshots carry a real version date (修正日期), not a guessed one.
        # Only rows explicitly marked via release_date_source may anchor
        # available_at to that documented date; all other D records keep the
        # archival first_seen convention.
        marker = str(normalized.get("release_date_source") or "")
        if not marker.startswith("wind_revision_snapshot_"):
            raise DataContractError("PIT_D available_at cannot precede first_seen_at")
    if normalized["release_at"] and normalized["available_at"] < normalized["release_at"]:
        raise DataContractError("available_at cannot precede release_at")
    return normalized


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _same_value(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)


def _epoch_microseconds(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp() * 1_000_000)


def _signature_values(
    source: str,
    series_id: str,
    period: str,
    value: float,
    release_epoch: int | None,
    available_epoch: int,
    release_date_source: str | None,
    pit_grade: str,
    unit: str,
    frequency: str,
) -> tuple:
    # Ordinary PIT_D rows are archival snapshots, so retrieval timestamps do
    # not make a new value vintage. A documented Wind revision is different:
    # its dated marker is the evidence for a real historical version event and
    # must remain distinct even when its value equals a later terminal export.
    documented_wind_revision = (
        pit_grade == "D"
        and str(release_date_source or "").startswith("wind_revision_snapshot_")
    )
    temporal = (
        (None, None, None)
        if pit_grade == "D" and not documented_wind_revision
        else (release_epoch, available_epoch, release_date_source)
    )
    return (source, series_id, period, float(value), pit_grade, unit, frequency, *temporal)


def _row_signature(row: dict[str, Any]) -> tuple:
    return _signature_values(
        row["source"], row["canonical_series_id"], row["period"], row["value"],
        _epoch_microseconds(row["release_at"]), _epoch_microseconds(row["available_at"]),
        row.get("release_date_source"), row["pit_grade"], row["unit"], row["frequency"],
    )


def insert_observations(
    conn: duckdb.DuckDBPyConnection,
    df: pl.DataFrame | Iterable[dict[str, Any]],
) -> InsertStats:
    """Append observations while preserving revisions and idempotency.

    Re-running the same normalized release is a no-op. A changed value becomes a
    new vintage; no existing row is ever updated or deleted.
    """
    incoming = [_normalize_record(row) for row in _records(df)]
    incoming.sort(key=lambda row: (row["available_at"], row["canonical_series_id"], row["period"]))
    if not incoming:
        return InsertStats()

    inserted = revisions = metadata_updates = unchanged = 0
    existing_signatures: set[tuple] = set()
    latest_by_period: dict[tuple[str, str, str], tuple] = {}
    for source, series_id in sorted({(row["source"], row["canonical_series_id"]) for row in incoming}):
        history = conn.execute(
            """
            SELECT period, value, epoch_us(release_at), epoch_us(available_at),
                   release_date_source, pit_grade, unit, frequency, vintage_no
            FROM observation_vintage
            WHERE source=? AND canonical_series_id=?
            ORDER BY period, vintage_no, available_at
            """,
            [source, series_id],
        ).fetchall()
        for record in history:
            period, value, release_epoch, available_epoch, release_source, grade, unit, frequency, vintage_no = record
            existing_signatures.add(
                _signature_values(
                    source, series_id, period, value, release_epoch, available_epoch,
                    release_source, grade, unit, frequency,
                )
            )
            latest_by_period[(source, series_id, period)] = (
                value, release_epoch, available_epoch, release_source,
                grade, unit, frequency, vintage_no,
            )
    conn.execute("BEGIN TRANSACTION")
    try:
        for row in incoming:
            signature = _row_signature(row)
            if signature in existing_signatures:
                unchanged += 1
                continue
            key = (row["source"], row["canonical_series_id"], row["period"])
            latest = latest_by_period.get(key)
            marker = str(row.get("release_date_source") or "")
            explicit_documented_revision = (
                row["pit_grade"] == "D"
                and marker.startswith("wind_revision_snapshot_")
                and str(row.get("revision_type") or "").lower() == "revision"
                and row.get("revision_delta") is not None
            )

            if latest is None:
                vintage_no = 0
                revision_type = "initial"
                revision_delta = None
            else:
                vintage_no = int(latest[7]) + 1
                if explicit_documented_revision:
                    revision_type = "revision"
                    revision_delta = float(row["revision_delta"])
                    if not math.isfinite(revision_delta) or _same_value(revision_delta, 0.0):
                        raise DataContractError(
                            "documented Wind revision requires a finite non-zero revision_delta"
                        )
                    revisions += 1
                elif _same_value(latest[0], row["value"]):
                    revision_type = "metadata_update"
                    revision_delta = 0.0
                    metadata_updates += 1
                else:
                    revision_type = "revision"
                    revision_delta = row["value"] - float(latest[0])
                    revisions += 1

            row["vintage_no"] = vintage_no
            row["revision_type"] = revision_type
            row["revision_delta"] = revision_delta
            placeholders = ", ".join("?" for _ in OBSERVATION_COLUMNS)
            conn.execute(
                f"INSERT INTO observation_vintage ({', '.join(OBSERVATION_COLUMNS)}) VALUES ({placeholders})",
                [row.get(column) for column in OBSERVATION_COLUMNS],
            )
            existing_signatures.add(signature)
            latest_by_period[key] = (
                row["value"], _epoch_microseconds(row["release_at"]),
                _epoch_microseconds(row["available_at"]), row.get("release_date_source"),
                row["pit_grade"], row["unit"], row["frequency"], vintage_no,
            )
            inserted += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return InsertStats(
        inserted=inserted,
        revisions=revisions,
        metadata_updates=metadata_updates,
        unchanged=unchanged,
    )


def fetch_all(conn: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return conn.execute(
        "SELECT * FROM observation_vintage ORDER BY canonical_series_id, period, vintage_no"
    ).pl()


def record_crawl_events(
    conn: duckdb.DuckDBPyConnection,
    events: Iterable[Any],
    *,
    parser_version: str | None = None,
) -> int:
    columns = [
        "crawl_id", "source", "url", "requested_at", "completed_at",
        "http_status", "success", "from_cache", "content_type",
        "response_bytes", "raw_file", "raw_sha256", "parser_version",
        "error_type", "error_message", "runtime_seconds",
    ]
    inserted = 0
    for event in events:
        row = asdict(event) if is_dataclass(event) else dict(event)
        row["parser_version"] = row.get("parser_version") or parser_version
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT OR IGNORE INTO crawl_log ({', '.join(columns)}) VALUES ({placeholders})",
            [row.get(column) for column in columns],
        )
        inserted += 1
    return inserted
