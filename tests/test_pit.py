import pytest
import duckdb
import polars as pl
import os
from datetime import datetime

from macro_pit.db import get_connection, insert_observations, fetch_all
from macro_pit.pit import get_snapshot
from macro_pit.snapshot import build_monthly_wide_snapshot

@pytest.fixture
def test_db():
    # Use in-memory db for testing
    conn = get_connection(":memory:")
    yield conn
    conn.close()

def test_pit_basic(test_db):
    # Setup some synthetic data
    data = {
        "country": ["CN", "CN"],
        "source": ["NBS", "NBS"],
        "canonical_series_id": ["CN_CPI_YOY", "CN_CPI_YOY"],
        "source_series_id": ["A010101", "A010101"],
        "series_name": ["CPI YOY", "CPI YOY"],
        "frequency": ["M", "M"],
        "unit": ["pct", "pct"],
        "seasonal_adjustment": ["NSA", "NSA"],
        "period": ["2020-01", "2020-01"],
        "period_start": [datetime(2020, 1, 1), datetime(2020, 1, 1)],
        "period_end": [datetime(2020, 1, 31), datetime(2020, 1, 31)],
        "value": [5.4, 5.3],
        "release_at": [datetime(2020, 2, 10, 9, 30), datetime(2020, 3, 10, 9, 30)],
        "release_date_source": ["official", "official"],
        "first_seen_at": [datetime(2020, 2, 10, 9, 35), datetime(2020, 3, 10, 9, 35)],
        "available_at": [datetime(2020, 2, 10, 9, 30), datetime(2020, 3, 10, 9, 30)],
        "vintage_no": [0, 1],
        "revision_type": ["initial", "revision"],
        "pit_grade": ["A", "A"],
        "source_url": ["http", "http"],
        "raw_file": ["file1", "file2"],
        "raw_sha256": ["hash1", "hash2"],
        "retrieved_at": [datetime(2020, 2, 10, 9, 35), datetime(2020, 3, 10, 9, 35)],
        "parser_version": ["v1", "v1"]
    }
    df = pl.DataFrame(data)
    stats = insert_observations(test_db, df)
    assert stats.inserted == 2
    assert stats.revisions == 1
    
    # Query before release
    snap1 = get_snapshot(test_db, as_of="2020-02-09 23:59:59")
    assert len(snap1) == 0
    
    # Query after initial release
    snap2 = get_snapshot(test_db, as_of="2020-02-29 23:59:59")
    assert len(snap2) == 1
    assert snap2["value"][0] == 5.4
    
    # Query after revision
    snap3 = get_snapshot(test_db, as_of="2020-03-31 23:59:59")
    assert len(snap3) == 1
    assert snap3["value"][0] == 5.3
    assert snap3["revision_delta"][0] == pytest.approx(-0.1)
    
def test_same_day_boundary(test_db):
    data = {
        "country": ["CN"],
        "source": ["PBOC"],
        "canonical_series_id": ["CN_M2_YOY"],
        "source_series_id": ["M2"],
        "series_name": ["M2 YOY"],
        "frequency": ["M"],
        "unit": ["pct"],
        "seasonal_adjustment": ["NSA"],
        "period": ["2025-01"],
        "period_start": [datetime(2025, 1, 1)],
        "period_end": [datetime(2025, 1, 31)],
        "value": [8.5],
        "release_at": [datetime(2025, 2, 14, 16, 30)],
        "release_date_source": ["official"],
        "first_seen_at": [datetime(2025, 2, 14, 16, 35)],
        "available_at": [datetime(2025, 2, 14, 16, 30)],
        "vintage_no": [0],
        "revision_type": ["initial"],
        "pit_grade": ["A"],
        "source_url": ["http"],
        "raw_file": ["file1"],
        "raw_sha256": ["hash1"],
        "retrieved_at": [datetime(2025, 2, 14, 16, 35)],
        "parser_version": ["v1"]
    }
    df = pl.DataFrame(data)
    insert_observations(test_db, df)
    
    # 15:00 should not see it
    snap1 = get_snapshot(test_db, as_of="2025-02-14 15:00:00")
    assert len(snap1) == 0
    
    # 17:00 should see it
    snap2 = get_snapshot(test_db, as_of="2025-02-14 17:00:00")
    assert len(snap2) == 1
    assert snap2["value"][0] == 8.5


def test_monthly_wide_snapshot_uses_latest_period_available_at_each_month_end(test_db, tmp_path):
    data = {
        "country": ["CN", "CN", "CN"],
        "source": ["NBS", "NBS", "NBS"],
        "canonical_series_id": ["CN_CPI_YOY", "CN_CPI_YOY", "CN_PPI_YOY"],
        "source_series_id": ["CPI", "CPI", "PPI"],
        "series_name": ["CPI YOY", "CPI YOY", "PPI YOY"],
        "frequency": ["M", "M", "M"],
        "unit": ["pct_yoy", "pct_yoy", "pct_yoy"],
        "seasonal_adjustment": ["NSA", "NSA", "NSA"],
        "period": ["2020-01", "2020-02", "2020-01"],
        "period_start": [datetime(2020, 1, 1), datetime(2020, 2, 1), datetime(2020, 1, 1)],
        "period_end": [datetime(2020, 1, 31), datetime(2020, 2, 29), datetime(2020, 1, 31)],
        "value": [1.0, 2.0, 3.0],
        "release_at": [datetime(2020, 2, 10), datetime(2020, 3, 10), None],
        "release_date_source": ["official", "official", "first_seen_only"],
        "first_seen_at": [datetime(2020, 2, 10), datetime(2020, 3, 10), datetime(2020, 2, 1)],
        "available_at": [datetime(2020, 2, 10), datetime(2020, 3, 10), datetime(2020, 2, 1)],
        "vintage_no": [0, 0, 0],
        "revision_type": ["initial", "initial", "initial"],
        "pit_grade": ["A", "A", "D"],
        "source_url": ["http", "http", "http"],
        "raw_file": ["file1", "file2", "file3"],
        "raw_sha256": ["hash1", "hash2", "hash3"],
        "retrieved_at": [datetime(2020, 2, 10), datetime(2020, 3, 10), datetime(2020, 2, 1)],
        "parser_version": ["v1", "v1", "v1"],
    }
    insert_observations(test_db, pl.DataFrame(data))

    paths = build_monthly_wide_snapshot(
        test_db,
        tmp_path / "cn_panel",
        "2010-01-31",
        "2020-03-31",
        country="CN",
        pit_mode="strict",
    )

    values = pl.read_parquet(paths["values_parquet"])
    periods = pl.read_parquet(paths["periods_parquet"])
    assert values.columns == ["as_of_month_end", "CN_CPI_YOY"]
    assert values.height == 123
    assert values.get_column("CN_CPI_YOY").tail(3).to_list() == [None, 1.0, 2.0]
    assert periods.get_column("CN_CPI_YOY").tail(3).to_list() == [None, "2020-01", "2020-02"]
    assert paths["values_csv"].is_file()
    assert paths["metadata_csv"].is_file()
