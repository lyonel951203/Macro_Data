"""Contract tests for the panel-level PIT_work export mode.

The work mode is a research view layered on top of evidence grades: the
freshest visible period wins per series; for the same period, official A/B
evidence beats an ordinary PIT_D terminal value, while a later documented
Wind revision becomes visible on its recorded revision date. Record-level
grades must never be altered, and strict mode output must stay identical.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from pathlib import Path

import polars as pl

from macro_pit.db import get_connection, insert_observations
from macro_pit.pit import get_snapshot
from macro_pit.snapshot import build_monthly_wide_snapshot


CN = timezone(timedelta(hours=8))


def _base_row(**over):
    row = {
        "country": "CN",
        "source": "NBS",
        "canonical_series_id": "CN_X",
        "source_series_id": "x1",
        "series_name": "X",
        "frequency": "M",
        "unit": "pct_yoy",
        "period": "2020-01",
        "period_start": "2020-01-01",
        "period_end": "2020-01-31",
        "value": 1.0,
        "release_at": datetime(2020, 2, 11, 10, 0, tzinfo=CN),
        "first_seen_at": datetime(2020, 2, 11, 10, 0, tzinfo=CN),
        "available_at": datetime(2020, 2, 11, 10, 0, tzinfo=CN),
        "pit_grade": "A",
        "source_url": "http://example.gov/x",
        "raw_file": "raw/x.html",
        "raw_sha256": "abc123",
        "retrieved_at": datetime(2020, 2, 11, 12, 0, tzinfo=CN),
        "parser_version": "t1",
    }
    row.update(over)
    return row


def _wind_row(series, period, period_end, value):
    return _base_row(
        source="WIND",
        canonical_series_id=series,
        period=period,
        period_end=period_end,
        value=value,
        release_at=None,
        pit_grade="D",
        first_seen_at=datetime(2026, 9, 8, 14, 10, tzinfo=CN),
        available_at=datetime(2026, 9, 8, 14, 10, tzinfo=CN),
        raw_sha256="N/A",
    )


def _wind_revision_row(series, period, period_end, value, revision_at):
    row = _wind_row(series, period, period_end, value)
    row.update(
        available_at=revision_at,
        release_date_source="wind_revision_snapshot_20250118",
    )
    return row


def _write_sidecar(path: Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    buf.write("canonical_series_id,source,period,period_end,value,"
              "estimated_release_date,estimated_available_at\n")
    for r in rows:
        buf.write(
            f"{r['series']},WIND,{r['period']},{r['period_end']},{r['value']},"
            f"{r['est_release']},{r['est_available']}\n"
        )
    path.write_text(buf.getvalue(), encoding="utf-8")


def _build_db(tmp_path: Path):
    db_path = tmp_path / "t.duckdb"
    conn = get_connection(db_path)
    # Series with A coverage starting 2020-01; WIND D history from 2019-01.
    insert_observations(conn, [_base_row()])
    insert_observations(conn, [
        _wind_row("CN_X", "2019-12", "2019-12-31", 9.9),
        _wind_row("CN_Y", "2020-01", "2020-01-31", 5.0),
    ])
    conn.close()
    return db_path


def _sidecar(tmp_path: Path) -> Path:
    sidecar = tmp_path / "est.csv"
    _write_sidecar(sidecar, [
        {"series": "CN_X", "period": "2019-12", "period_end": "2019-12-31",
         "value": 9.9, "est_release": "2020-01-12",
         "est_available": "2020-01-13T00:00:00+08:00"},
        {"series": "CN_Y", "period": "2020-01", "period_end": "2020-01-31",
         "value": 5.0, "est_release": "2020-02-12",
         "est_available": "2020-02-13T00:00:00+08:00"},
    ])
    return sidecar


def test_work_prefers_ab_and_labels_provenance(tmp_path):
    db_path = _build_db(tmp_path)
    sidecar = _sidecar(tmp_path)
    paths = build_monthly_wide_snapshot(
        __import__("macro_pit.db", fromlist=["get_connection"]).get_connection(db_path, read_only=True),
        tmp_path / "work",
        "2020-01-31",
        "2020-02-29",
        pit_mode="work",
        estimated_availability_path=sidecar,
    )
    values = pl.read_csv(paths["values_csv"])
    prov = pl.read_csv(paths["provenance_csv"])
    # 2020-01-31 cutoff: A record for CN_X not yet released (Feb 11); the WIND
    # 2019-12 estimate became available Jan 13, so it fills the cell.
    row_jan = values.row(0, named=True)
    prov_jan = prov.row(0, named=True)
    assert row_jan["CN_X"] == 9.9
    assert prov_jan["CN_X"] == "work_wind"
    # CN_Y has no A/B coverage. Work mode still includes it once its delayed
    # WIND observation becomes visible; it is blank before that date.
    assert "CN_Y" in values.columns
    assert row_jan["CN_Y"] is None
    row_feb = values.row(1, named=True)
    prov_feb = prov.row(1, named=True)
    # Once the A record is visible (Feb cutoff), it beats the WIND estimate.
    assert row_feb["CN_X"] == 1.0
    assert prov_feb["CN_X"] == "work_A"
    assert row_feb["CN_Y"] == 5.0
    assert prov_feb["CN_Y"] == "work_wind"
    metadata = pl.read_csv(paths["metadata_csv"])
    y_meta = metadata.filter(
        pl.col("canonical_series_id") == "CN_Y"
    ).row(0, named=True)
    assert y_meta["series_name"] == "X"
    assert y_meta["frequency"] == "M"
    assert y_meta["pit_grade"] == "D"


def test_work_prefers_fresher_wind_over_stale_ab(tmp_path):
    """A fresher WIND estimate must replace a stale A value (the CPI case:
    sparse official evidence must not pin the panel to an old period)."""
    db_path = tmp_path / "t2.duckdb"
    conn = get_connection(db_path)
    insert_observations(conn, [_base_row(
        canonical_series_id="CN_Z",
        period="2019-12", period_end="2019-12-31", value=1.0,
        release_at=datetime(2020, 1, 12, 10, 0, tzinfo=CN),
        first_seen_at=datetime(2020, 1, 12, 10, 0, tzinfo=CN),
        available_at=datetime(2020, 1, 12, 10, 0, tzinfo=CN),
    )])
    insert_observations(conn, [_wind_row("CN_Z", "2020-01", "2020-01-31", 7.7)])
    conn.close()
    sidecar = tmp_path / "est2.csv"
    _write_sidecar(sidecar, [
        {"series": "CN_Z", "period": "2020-01", "period_end": "2020-01-31",
         "value": 7.7, "est_release": "2020-02-12",
         "est_available": "2020-02-13T00:00:00+08:00"},
    ])
    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    paths = build_monthly_wide_snapshot(
        conn, tmp_path / "work2", "2020-01-31", "2020-02-29",
        pit_mode="work", estimated_availability_path=sidecar,
    )
    conn.close()
    values = pl.read_csv(paths["values_csv"])
    prov = pl.read_csv(paths["provenance_csv"])
    # Jan cutoff: only the A record (period 2019-12) is visible.
    assert values.row(0, named=True)["CN_Z"] == 1.0
    assert prov.row(0, named=True)["CN_Z"] == "work_A"
    # Feb cutoff: the WIND estimate for the fresher 2020-01 period wins.
    assert values.row(1, named=True)["CN_Z"] == 7.7
    assert prov.row(1, named=True)["CN_Z"] == "work_wind"


def test_work_applies_documented_wind_revision_only_after_revision_date(tmp_path):
    db_path = tmp_path / "revision.duckdb"
    conn = get_connection(db_path)
    original = _base_row(
        canonical_series_id="CN_GDP_YOY",
        period="2022-Q2",
        period_start="2022-04-01",
        period_end="2022-06-30",
        frequency="Q",
        value=0.4,
        release_at=datetime(2022, 7, 15, 10, 0, tzinfo=CN),
        first_seen_at=datetime(2022, 7, 15, 10, 0, tzinfo=CN),
        available_at=datetime(2022, 7, 15, 10, 0, tzinfo=CN),
    )
    revision_at = datetime(2025, 1, 18, 0, 0, tzinfo=CN)
    revision = _wind_revision_row(
        "CN_GDP_YOY", "2022-Q2", "2022-06-30", 0.8, revision_at
    )
    revision["period_start"] = "2022-04-01"
    revision["frequency"] = "Q"
    insert_observations(conn, [original, revision])
    conn.close()

    sidecar = tmp_path / "revision_est.csv"
    _write_sidecar(sidecar, [{
        "series": "CN_GDP_YOY", "period": "2022-Q2",
        "period_end": "2022-06-30", "value": 0.8,
        "est_release": "2022-07-18",
        "est_available": "2022-07-19T00:00:00+08:00",
    }])
    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    before = build_monthly_wide_snapshot(
        conn, tmp_path / "before", "2024-12-31", "2024-12-31",
        pit_mode="work", estimated_availability_path=sidecar,
    )
    after = build_monthly_wide_snapshot(
        conn, tmp_path / "after", "2025-01-31", "2025-01-31",
        pit_mode="work", estimated_availability_path=sidecar,
    )
    conn.close()

    before_values = pl.read_csv(before["values_csv"])
    before_prov = pl.read_csv(before["provenance_csv"])
    after_values = pl.read_csv(after["values_csv"])
    after_prov = pl.read_csv(after["provenance_csv"])
    assert before_values["CN_GDP_YOY"][0] == 0.4
    assert before_prov["CN_GDP_YOY"][0] == "work_A"
    assert after_values["CN_GDP_YOY"][0] == 0.8
    assert after_prov["CN_GDP_YOY"][0] == "work_wind_revision"


def test_work_never_alters_strict_mode(tmp_path):
    db_path = _build_db(tmp_path)
    sidecar = _sidecar(tmp_path)
    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    strict = get_snapshot(conn, "2020-02-29 23:59:59+08:00", country="CN", pit_mode="strict")
    build_monthly_wide_snapshot(
        conn, tmp_path / "work", "2020-01-31", "2020-02-29",
        pit_mode="work", estimated_availability_path=sidecar,
    )
    conn.close()
    conn2 = duckdb.connect(str(db_path), read_only=True)
    strict_after = get_snapshot(conn2, "2020-02-29 23:59:59+08:00", country="CN", pit_mode="strict")
    conn2.close()
    assert strict.select(["canonical_series_id", "period", "value"]).rows() == \
        strict_after.select(["canonical_series_id", "period", "value"]).rows()
    # Strict snapshot never contains WIND D rows.
    assert set(strict_after["source"].to_list()) == {"NBS"}


def test_work_requires_sidecar(tmp_path):
    db_path = _build_db(tmp_path)
    import duckdb
    import pytest

    conn = duckdb.connect(str(db_path), read_only=True)
    with pytest.raises(ValueError):
        build_monthly_wide_snapshot(
            conn, tmp_path / "work", "2020-01-31", "2020-02-29",
            pit_mode="work", estimated_availability_path=tmp_path / "missing.csv",
        )
    conn.close()
