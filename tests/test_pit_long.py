from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from polars.testing import assert_frame_equal

from macro_pit.asof_wide import build_as_of_wide, build_as_of_wide_from_long
from macro_pit.db import get_connection, insert_observations
from macro_pit.pit_long import build_pit_long, export_pit_long


CN_TZ = timezone(timedelta(hours=8))


def _row(
    *,
    source="NBS",
    field="CN_X",
    period="2020-06",
    period_start="2020-06-01",
    period_end="2020-06-30",
    value=1.0,
    grade="A",
    available=datetime(2020, 7, 10, 10, tzinfo=CN_TZ),
    frequency="M",
    release_date_source="official",
    sha="x",
):
    is_d = grade == "D"
    archived = datetime(2026, 9, 1, tzinfo=CN_TZ)
    return {
        "country": "CN",
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
        "first_seen_at": archived if is_d else available,
        "available_at": available,
        "pit_grade": grade,
        "source_url": "https://example.test/" + sha,
        "raw_file": "raw/" + sha,
        "raw_sha256": sha,
        "retrieved_at": archived if is_d else available,
        "parser_version": "test",
    }


def _sidecar(path: Path) -> Path:
    path.write_text(
        "canonical_series_id,source,period,period_end,value,"
        "estimated_release_date,estimated_available_at\n"
        "CN_X,WIND,2020-06,2020-06-30,8.0,2020-07-01,"
        "2020-07-01T00:00:00+08:00\n",
        encoding="utf-8",
    )
    return path


def test_full_long_export_encodes_effective_intervals_and_both_frequencies(tmp_path):
    conn = get_connection(":memory:")
    insert_observations(
        conn,
        [
            _row(
                source="WIND", value=8.0, grade="D",
                available=datetime(2026, 9, 1, tzinfo=CN_TZ), sha="wind",
            ),
            _row(
                source="PBOC", value=9.0, grade="B",
                available=datetime(2020, 7, 5, tzinfo=CN_TZ), sha="b1",
            ),
            _row(
                source="NBS", value=10.0, grade="A",
                available=datetime(2020, 7, 20, tzinfo=CN_TZ), sha="a1",
            ),
            _row(
                source="PBOC", value=99.0, grade="B",
                available=datetime(2020, 8, 1, tzinfo=CN_TZ), sha="b_late",
            ),
            _row(
                source="NBS", value=11.0, grade="A",
                available=datetime(2020, 8, 5, tzinfo=CN_TZ), sha="a2",
            ),
            _row(
                source="WIND", value=12.0, grade="D",
                available=datetime(2020, 8, 10, tzinfo=CN_TZ),
                release_date_source="wind_revision_snapshot_20200810",
                sha="revision",
            ),
            _row(
                source="NBS", field="CN_Q", period="2020-Q2",
                period_start="2020-04-01", period_end="2020-06-30",
                value=40.0, frequency="Q",
                available=datetime(2020, 7, 15, tzinfo=CN_TZ), sha="q",
            ),
            _row(
                source="OTHER", field="CN_C", value=77.0, grade="C",
                available=datetime(2020, 7, 2, tzinfo=CN_TZ), sha="c",
            ),
            _row(
                source="OTHER", field="CN_D", value=88.0, grade="D",
                available=datetime(2026, 9, 1, tzinfo=CN_TZ), sha="d",
            ),
        ],
    )
    sidecar = _sidecar(tmp_path / "estimated.csv")
    result = build_pit_long(
        conn,
        "CN",
        start_date="2020-06-01",
        estimated_availability_path=sidecar,
    )

    x = result.events.filter(
        result.events["canonical_series_id"] == "CN_X"
    )
    assert x["selection_origin"].to_list() == [
        "WIND",
        "PIT_B",
        "PIT_A",
        "PIT_A",
        "WIND_REVISION",
    ]
    assert x["value"].to_list() == [8.0, 9.0, 10.0, 11.0, 12.0]
    assert x["valid_to"][:-1].to_list() == x["valid_from"][1:].to_list()
    assert x["valid_to"][-1] is None
    assert 99.0 not in x["value"].to_list()
    assert set(result.events["source_frequency"].to_list()) == {"M", "Q"}
    assert set(result.events["canonical_series_id"].to_list()) == {"CN_X", "CN_Q"}

    paths = export_pit_long(result, tmp_path / "cn_long")
    assert all(path.is_file() for path in paths.values())
    receipt = json.loads(paths["export_json"].read_text(encoding="utf-8"))
    assert receipt["requires_as_of_parameter"] is False
    assert receipt["rows"] == result.events.height
    for frequency, index_column in (("M", "month_end"), ("Q", "quarter_end")):
        from_database = build_as_of_wide(
            conn,
            "2020-08-31",
            "CN",
            start_date="2020-06-01",
            frequency=frequency,
            estimated_availability_path=sidecar,
        )
        from_long = build_as_of_wide_from_long(
            paths["long_parquet"],
            "2020-08-31",
            "CN",
            start_date="2020-06-01",
            frequency=frequency,
        )
        columns = [index_column, "CN_Q", "CN_X"]
        assert_frame_equal(from_long.values.select(columns), from_database.values.select(columns))
        assert_frame_equal(from_long.periods.select(columns), from_database.periods.select(columns))
        assert_frame_equal(from_long.provenance.select(columns), from_database.provenance.select(columns))
        assert from_long.input_mode == "long_parquet"
        assert from_long.input_reference == str(paths["long_parquet"].resolve())
    conn.close()
