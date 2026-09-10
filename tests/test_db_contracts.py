from __future__ import annotations

from datetime import date

import pytest
import duckdb

from macro_pit.db import get_connection, insert_observations
from macro_pit.errors import DataContractError
from macro_pit.pit import get_snapshot
from macro_pit.timeutils import conservative_date_only_available


def observation(**overrides):
    row = {
        "country": "CN",
        "source": "NBS",
        "canonical_series_id": "CN_CPI_YOY",
        "source_series_id": "A010101",
        "series_name": "CPI同比",
        "frequency": "M",
        "unit": "pct_yoy",
        "seasonal_adjustment": "NSA",
        "period": "2025-01",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "value": 1.2,
        "release_at": "2025-02-10 09:30:00+08:00",
        "release_date_source": "official_page_timestamp",
        "first_seen_at": "2025-02-10 09:31:00+08:00",
        "available_at": "2025-02-10 09:30:00+08:00",
        "pit_grade": "A",
        "source_url": "https://www.stats.gov.cn/release",
        "raw_file": "data/raw/nbs/test.html",
        "raw_sha256": "a" * 64,
        "retrieved_at": "2025-02-10 09:31:00+08:00",
        "parser_version": "test_v1",
    }
    row.update(overrides)
    return row


def test_insert_is_idempotent_and_preserves_revision():
    conn = get_connection(":memory:")
    first = observation()
    assert insert_observations(conn, [first]).inserted == 1
    repeated = insert_observations(conn, [first])
    assert repeated.unchanged == 1
    assert conn.execute("select count(*) from observation_vintage").fetchone()[0] == 1

    revised = observation(
        value=1.1,
        release_at="2025-03-10 09:30:00+08:00",
        available_at="2025-03-10 09:30:00+08:00",
        first_seen_at="2025-03-10 09:31:00+08:00",
        retrieved_at="2025-03-10 09:31:00+08:00",
        raw_sha256="b" * 64,
    )
    stats = insert_observations(conn, [revised])
    assert stats.revisions == 1
    rows = conn.execute(
        "select value, vintage_no, revision_type, revision_delta from observation_vintage order by vintage_no"
    ).fetchall()
    assert rows == [(1.2, 0, "initial", None), (1.1, 1, "revision", pytest.approx(-0.1))]


def test_pit_a_requires_real_raw_hash():
    conn = get_connection(":memory:")
    with pytest.raises(DataContractError, match="raw_sha256"):
        insert_observations(conn, [observation(raw_sha256="N/A")])


def test_pit_b_date_only_boundary():
    conn = get_connection(":memory:")
    available = conservative_date_only_available(date(2025, 2, 14))
    row = observation(
        pit_grade="B",
        release_at="2025-02-14 00:00:00+08:00",
        release_date_source="official_page_date",
        available_at=available,
        first_seen_at="2025-02-20 10:00:00+08:00",
        retrieved_at="2025-02-20 10:00:00+08:00",
    )
    insert_observations(conn, [row])
    assert get_snapshot(conn, "2025-02-14 23:59:59+08:00").height == 0
    assert get_snapshot(conn, "2025-02-15 00:00:00+08:00").height == 1


def test_loose_excludes_first_seen_only_grade_d():
    conn = get_connection(":memory:")
    row = observation(
        pit_grade="D",
        release_at=None,
        release_date_source="first_seen_only",
        first_seen_at="2025-09-01 10:00:00+08:00",
        available_at="2025-09-01 10:00:00+08:00",
        retrieved_at="2025-09-01 10:00:00+08:00",
    )
    insert_observations(conn, [row])
    assert get_snapshot(conn, "2025-09-02 00:00:00+08:00", pit_mode="strict").height == 0
    assert get_snapshot(conn, "2025-09-02 00:00:00+08:00", pit_mode="loose").height == 0
    assert get_snapshot(conn, "2025-09-02 00:00:00+08:00", pit_mode="observed").height == 1

    later_same_value = dict(row)
    later_same_value.update(
        first_seen_at="2025-09-03 10:00:00+08:00",
        available_at="2025-09-03 10:00:00+08:00",
        retrieved_at="2025-09-03 10:00:00+08:00",
        raw_sha256="c" * 64,
    )
    assert insert_observations(conn, [later_same_value]).unchanged == 1


def test_invalid_pit_mode_and_parameterized_country():
    conn = get_connection(":memory:")
    insert_observations(conn, [observation()])
    with pytest.raises(ValueError):
        get_snapshot(conn, "2025-03-01 00:00:00+08:00", pit_mode="anything")
    assert get_snapshot(conn, "2025-03-01 00:00:00+08:00", country="CN' OR 1=1 --").height == 0


def test_populated_legacy_naive_database_is_refused(tmp_path):
    path = tmp_path / "legacy.duckdb"
    legacy = duckdb.connect(str(path))
    legacy.execute(
        """
        create table observation_vintage (
            release_at timestamp, first_seen_at timestamp,
            available_at timestamp, retrieved_at timestamp
        )
        """
    )
    legacy.execute("insert into observation_vintage values (current_timestamp, current_timestamp, current_timestamp, current_timestamp)")
    legacy.close()
    with pytest.raises(DataContractError, match="timezone-naive"):
        get_connection(path)
