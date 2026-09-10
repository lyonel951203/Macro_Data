from __future__ import annotations

from macro_pit.db import get_connection, insert_observations
from macro_pit.maintenance import compact_database, rebuild_excluding_sources


def row(release: str, raw_hash: str):
    return {
        "country": "FR",
        "source": "OECD",
        "canonical_series_id": "FR_CPI",
        "source_series_id": "CP|IX",
        "series_name": "CPI",
        "frequency": "M",
        "unit": "index",
        "seasonal_adjustment": "UNKNOWN",
        "period": "2025-01",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "value": 100.0,
        "release_at": release,
        "release_date_source": "oecd_edition_period_end",
        "first_seen_at": "2026-09-01 00:00:00+00:00",
        "available_at": release,
        "pit_grade": "B",
        "source_url": "https://sdmx.oecd.org/query",
        "raw_file": "raw.csv",
        "raw_sha256": raw_hash,
        "retrieved_at": "2026-09-01 00:00:00+00:00",
        "parser_version": "test",
    }


def test_compact_database_removes_unchanged_editions_without_touching_source(tmp_path):
    source_path = tmp_path / "source.duckdb"
    target_path = tmp_path / "target.duckdb"
    conn = get_connection(source_path)
    insert_observations(
        conn,
        [
            row("2025-02-28 00:00:00+00:00", "a" * 64),
            row("2025-03-31 00:00:00+00:00", "b" * 64),
        ],
    )
    conn.close()
    result = compact_database(source_path, target_path)
    assert result.source_rows == 2
    assert result.target_rows == 1
    assert result.removed_unchanged_rows == 1
    assert source_path.is_file()


def test_rebuild_can_exclude_a_source_for_clean_raw_reparse(tmp_path):
    source_path = tmp_path / "source.duckdb"
    target_path = tmp_path / "target.duckdb"
    conn = get_connection(source_path)
    insert_observations(conn, [row("2025-02-28 00:00:00+00:00", "a" * 64)])
    conn.close()
    result = rebuild_excluding_sources(source_path, target_path, {"OECD"})
    assert result.source_rows == 1
    assert result.copied_rows == 0
    assert result.excluded_rows == 1
