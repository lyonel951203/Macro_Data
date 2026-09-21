from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import json

import polars as pl

from macro_pit.asof_wide import build_as_of_wide, export_as_of_wide
from macro_pit.db import get_connection, insert_observations


CN_TZ = timezone(timedelta(hours=8))


def _row(
    *, country="CN", source="NBS", field="CN_X", period="2020-06",
    period_start="2020-06-01", period_end="2020-06-30", value=1.0,
    grade="A", available=datetime(2020, 7, 10, 10, tzinfo=CN_TZ),
    frequency="M", release_date_source="official", sha="x",
):
    is_d = grade == "D"
    return {
        "country": country,
        "source": source,
        "canonical_series_id": field,
        "source_series_id": field,
        "series_name": field,
        "frequency": frequency,
        "unit": "pct",
        "seasonal_adjustment": "NSA",
        "period": period,
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "release_at": None if is_d else available,
        "release_date_source": release_date_source,
        "first_seen_at": available if not is_d else datetime(2026, 9, 1, tzinfo=CN_TZ),
        "available_at": available,
        "pit_grade": grade,
        "source_url": "https://example.test/" + sha,
        "raw_file": "raw/" + sha,
        "raw_sha256": sha,
        "retrieved_at": available if not is_d else datetime(2026, 9, 1, tzinfo=CN_TZ),
        "parser_version": "test",
    }


def _sidecar(path: Path) -> Path:
    path.write_text(
        "canonical_series_id,source,period,period_end,value,estimated_release_date,estimated_available_at\n"
        "CN_X,WIND,2020-06,2020-06-30,8.0,2020-07-01,2020-07-01T00:00:00+08:00\n"
        "CN_Y,WIND,2020-06,2020-06-30,20.0,2020-07-04,2020-07-05T00:00:00+08:00\n"
        "CN_FX_RESERVE_USD,SAFE,2020-05,2020-05-31,340.0,2020-06-07,2020-06-08T00:00:00+08:00\n"
        "CN_FX_RESERVE_USD,SAFE,2020-06,2020-06-30,341.0,2020-07-07,2020-07-08T00:00:00+08:00\n",
        encoding="utf-8",
    )
    return path


def test_fixed_t_wide_uses_a_then_b_then_wind_and_never_forward_fills(tmp_path):
    conn = get_connection(":memory:")
    insert_observations(conn, [
        _row(field="CN_X", source="WIND", value=8.0, grade="D",
             available=datetime(2026, 9, 1, tzinfo=CN_TZ), sha="x_wind"),
        _row(field="CN_X", source="PBOC", value=9.0, grade="B",
             available=datetime(2020, 7, 5, tzinfo=CN_TZ), sha="x_b"),
        _row(field="CN_X", source="NBS", value=10.0, grade="A",
             available=datetime(2020, 7, 20, tzinfo=CN_TZ), sha="x_a1"),
        _row(field="CN_X", source="NBS", value=11.0, grade="A",
             available=datetime(2020, 8, 5, tzinfo=CN_TZ), sha="x_a2"),
        _row(field="CN_X", source="WIND", value=12.0, grade="D",
             available=datetime(2020, 8, 10, tzinfo=CN_TZ),
             release_date_source="wind_revision_snapshot_20200810", sha="x_wr"),
        _row(field="CN_Y", source="WIND", value=20.0, grade="D",
             available=datetime(2026, 9, 1, tzinfo=CN_TZ), sha="y_wind"),
        _row(field="CN_Y", source="WIND", value=22.0, grade="D",
             available=datetime(2020, 8, 10, tzinfo=CN_TZ),
             release_date_source="wind_revision_snapshot_20200810", sha="y_wr"),
        _row(field="CN_W", source="PBOC", value=5.0, grade="B",
             available=datetime(2020, 7, 5, tzinfo=CN_TZ), sha="w_b"),
        _row(field="CN_W", source="NBS", value=6.0, grade="A",
             available=datetime(2020, 8, 1, tzinfo=CN_TZ), sha="w_a"),
        _row(field="CN_Z", value=30.0, grade="A",
             available=datetime(2020, 7, 31, 18, tzinfo=CN_TZ), sha="z"),
        _row(field="CN_Q", period="2020-Q2", period_start="2020-04-01",
             period_end="2020-06-30", value=40.0, grade="A", frequency="Q",
             available=datetime(2020, 7, 15, tzinfo=CN_TZ), sha="q"),
        _row(field="CN_JULY", period="2020-07", period_start="2020-07-01",
             period_end="2020-07-31", value=50.0, grade="A",
             available=datetime(2020, 8, 5, tzinfo=CN_TZ), sha="july"),
    ])
    sidecar = _sidecar(tmp_path / "estimated.csv")

    before_official = build_as_of_wide(
        conn, "2020-07-02", "CN", start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )
    before_row = before_official.values.filter(
        pl.col("month_end") == pl.date(2020, 6, 30)
    ).row(0, named=True)
    assert before_row["CN_X"] is None  # any A/B record makes ordinary Wind gap-ineligible

    july = build_as_of_wide(
        conn, "2020-07-31", "CN", start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )
    june = july.values.filter(pl.col("month_end") == pl.date(2020, 6, 30)).row(0, named=True)
    july_row = july.values.filter(pl.col("month_end") == pl.date(2020, 7, 31)).row(0, named=True)
    june_origin = july.provenance.filter(pl.col("month_end") == pl.date(2020, 6, 30)).row(0, named=True)
    assert june["CN_X"] == 10.0
    assert june_origin["CN_X"] == "PIT_A"
    assert june["CN_W"] == 5.0
    assert june_origin["CN_W"] == "PIT_B"
    assert june["CN_Y"] == 20.0
    assert june_origin["CN_Y"] == "WIND"
    assert june["CN_Z"] == 30.0  # date-only T includes the whole Shanghai day
    assert june["CN_Q"] == 40.0  # quarterly data lands on the quarter-end month
    assert july_row["CN_X"] is None  # no forward fill from June
    assert july_row["CN_JULY"] is None  # July observation is not released by T

    august = build_as_of_wide(
        conn, "2020-08-31", "CN", start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )
    june_aug = august.values.filter(pl.col("month_end") == pl.date(2020, 6, 30)).row(0, named=True)
    origin_aug = august.provenance.filter(pl.col("month_end") == pl.date(2020, 6, 30)).row(0, named=True)
    july_aug = august.values.filter(pl.col("month_end") == pl.date(2020, 7, 31)).row(0, named=True)
    assert june_aug["CN_X"] == 12.0  # dated Wind revision overrides the older A after Aug 10
    assert origin_aug["CN_X"] == "WIND_REVISION"
    assert june_aug["CN_W"] == 6.0   # A becomes visible after July T
    assert june_aug["CN_Y"] == 22.0
    assert origin_aug["CN_Y"] == "WIND_REVISION"
    assert july_aug["CN_JULY"] == 50.0

    quarterly = build_as_of_wide(
        conn, "2020-07-31", "CN", start_date="2020-06-01", frequency="q",
        estimated_availability_path=sidecar,
    )
    assert quarterly.frequency == "Q"
    assert quarterly.index_column == "quarter_end"
    assert quarterly.values["quarter_end"].to_list() == [
        date(2020, 6, 30),
        date(2020, 9, 30),
    ]
    q2 = quarterly.values.row(0, named=True)
    q3 = quarterly.values.row(1, named=True)
    assert q2["CN_X"] == 10.0
    assert q2["CN_Q"] == 40.0
    assert q3["CN_X"] is None
    assert q3["CN_JULY"] is None
    assert set(quarterly.selected_long["period_end"].dt.month().to_list()) <= {3, 6, 9, 12}
    conn.close()


def test_safe_fx_reserve_estimate_starts_on_virtual_date_and_never_precedes_ab(tmp_path):
    conn = get_connection(":memory:")
    insert_observations(conn, [
        _row(
            field="CN_FX_RESERVE_USD", source="SAFE", period="2020-05",
            period_start="2020-05-01", period_end="2020-05-31",
            value=340.0, grade="D", available=datetime(2026, 9, 1, tzinfo=CN_TZ),
            sha="fx_may_d",
        ),
        _row(
            field="CN_FX_RESERVE_USD", source="SAFE", period="2020-05",
            period_start="2020-05-01", period_end="2020-05-31",
            value=342.0, grade="B", available=datetime(2020, 6, 15, tzinfo=CN_TZ),
            sha="fx_may_b",
        ),
        _row(
            field="CN_FX_RESERVE_USD", source="SAFE", period="2020-06",
            period_start="2020-06-01", period_end="2020-06-30",
            value=341.0, grade="D", available=datetime(2026, 9, 1, tzinfo=CN_TZ),
            sha="fx_june_d",
        ),
    ])
    sidecar = _sidecar(tmp_path / "estimated.csv")

    before = build_as_of_wide(
        conn, "2020-07-07T23:59:59+08:00", "CN", start_date="2020-05-01",
        estimated_availability_path=sidecar,
    )
    before_june = before.values.filter(
        pl.col("month_end") == pl.date(2020, 6, 30)
    ).row(0, named=True)
    assert before_june["CN_FX_RESERVE_USD"] is None

    after = build_as_of_wide(
        conn, "2020-07-08T00:00:00+08:00", "CN", start_date="2020-05-01",
        estimated_availability_path=sidecar,
    )
    may = after.values.filter(
        pl.col("month_end") == pl.date(2020, 5, 31)
    ).row(0, named=True)
    june = after.values.filter(
        pl.col("month_end") == pl.date(2020, 6, 30)
    ).row(0, named=True)
    origins = after.provenance.filter(
        pl.col("month_end").is_in([date(2020, 5, 31), date(2020, 6, 30)])
    )["CN_FX_RESERVE_USD"].to_list()
    assert may["CN_FX_RESERVE_USD"] == 342.0
    assert june["CN_FX_RESERVE_USD"] == 341.0
    assert origins == ["PIT_B", "SAFE_ESTIMATED_D"]
    conn.close()


def test_scope_cn_us_glb_and_export_companions(tmp_path):
    conn = get_connection(":memory:")
    insert_observations(conn, [
        _row(country="CN", field="CN_X", sha="cn"),
        _row(country="US", source="RTDSM", field="US_X", grade="B", sha="us"),
        _row(country="DEU", source="OECD", field="DE_X", grade="B", sha="de"),
    ])
    sidecar = _sidecar(tmp_path / "estimated.csv")
    cn = build_as_of_wide(conn, "2020-07-31", "CN", start_date="2020-06-01", estimated_availability_path=sidecar)
    us = build_as_of_wide(conn, "2020-07-31", "US", start_date="2020-06-01")
    glb = build_as_of_wide(conn, "2020-07-31", "GLB", start_date="2020-06-01")
    assert cn.values.columns == ["month_end", "CN_X"]
    assert us.values.columns == ["month_end", "US_X"]
    assert glb.values.columns == ["month_end", "DE_X"]
    paths = export_as_of_wide(glb, tmp_path / "glb")
    assert all(path.is_file() for path in paths.values())
    assert pl.read_csv(paths["values_csv"]).columns == ["month_end", "DE_X"]
    receipt = json.loads(paths["query_json"].read_text(encoding="utf-8"))
    assert receipt["frequency"] == "M"
    assert receipt["index_column"] == "month_end"
    conn.close()


def test_cn_official_web_revision_becomes_visible_only_when_observed(tmp_path):
    conn = get_connection(":memory:")
    base_at = datetime(2020, 7, 10, 10, tzinfo=CN_TZ)
    revised_at = datetime(2020, 8, 15, 9, tzinfo=CN_TZ)
    replacement_at = datetime(2020, 9, 1, 10, tzinfo=CN_TZ)
    base = _row(
        source="CUSTOMS", field="CN_EXPORT_USD", value=100.0,
        available=base_at, sha="customs_base",
    )
    revision = _row(
        source="CUSTOMS", field="CN_EXPORT_USD", value=101.0, grade="D",
        available=revised_at,
        release_date_source="official_web_revision_first_seen",
        sha="customs_revision",
    )
    revision.update(
        first_seen_at=revised_at,
        retrieved_at=revised_at,
        source_url=base["source_url"],
    )
    later_official = _row(
        source="CUSTOMS", field="CN_EXPORT_USD", value=102.0,
        available=replacement_at, sha="customs_later",
    )
    insert_observations(conn, [base, revision, later_official])
    sidecar = _sidecar(tmp_path / "estimated.csv")

    before = build_as_of_wide(
        conn, "2020-08-14", "CN", start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )
    revised = build_as_of_wide(
        conn, "2020-08-31", "CN", start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )
    replaced = build_as_of_wide(
        conn, "2020-09-30", "CN", start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )
    assert before.values["CN_EXPORT_USD"].drop_nulls().to_list() == [100.0]
    assert revised.values["CN_EXPORT_USD"].drop_nulls().to_list() == [101.0]
    assert revised.provenance["CN_EXPORT_USD"].drop_nulls().to_list() == [
        "OBSERVED_WEB_REVISION"
    ]
    assert replaced.values["CN_EXPORT_USD"].drop_nulls().to_list() == [102.0]
    assert replaced.provenance["CN_EXPORT_USD"].drop_nulls().to_list() == ["PIT_A"]
    conn.close()
