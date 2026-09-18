from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from macro_pit.archive import RawArtifact
from macro_pit.asof_wide import build_as_of_wide
from macro_pit.db import get_connection, insert_observations
from macro_pit.pit_long import build_pit_long
from macro_pit.sources.cn_fallback import EastmoneyMacroSource, SinaMacroSource


CN = timezone(timedelta(hours=8))


def _artifact(tmp_path, content: bytes, source: str) -> RawArtifact:
    path = tmp_path / f"{source.lower()}.raw"
    path.write_bytes(content)
    return RawArtifact(
        source=source,
        url=f"https://example.test/{source.lower()}",
        path=path.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        content_type="application/json",
        retrieved_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
        size=len(content),
    )


def test_sina_money_jsonp_maps_latest_periods_to_first_seen_d(tmp_path):
    content = (
        '/* guard */MACROPIT(({config:{all:[]},count:"2",data:'
        '[["2026.8","3568083.60","7.50","1157741.43","4.10",'
        '"148311.98","11.20"],["2026.7","3555077.24","7.70",'
        '"1154623.00","4.00","148202.86","11.60"]]}));'
    ).encode("ascii")
    source = SinaMacroSource(allow_network=False)
    try:
        rows = source.parse_job(
            "money", content, _artifact(tmp_path, content, source.source),
            latest_periods=2,
        )
    finally:
        source.close()
    values = {(row["canonical_series_id"], row["period"]): row["value"] for row in rows}
    assert len(rows) == 6
    assert values[("CN_M2_YOY", "2026-08")] == 7.5
    assert values[("CN_M1_YOY", "2026-08")] == 4.1
    assert values[("CN_M0_YOY", "2026-08")] == 11.2
    assert all(row["pit_grade"] == "D" for row in rows)
    assert all(row["release_at"] is None for row in rows)
    assert all(row["available_at"] == row["first_seen_at"] for row in rows)


def test_eastmoney_pmi_maps_only_reviewed_headlines(tmp_path):
    content = json.dumps({
        "success": True,
        "result": {"data": [
            {"REPORT_DATE": "2026-08-01 00:00:00", "MAKE_INDEX": 49.8, "NMAKE_INDEX": 49.0},
            {"REPORT_DATE": "2026-07-01 00:00:00", "MAKE_INDEX": 49.2, "NMAKE_INDEX": 49.0},
        ]},
    }).encode("utf-8")
    source = EastmoneyMacroSource(allow_network=False)
    try:
        rows = source.parse_job(
            "pmi", content, _artifact(tmp_path, content, source.source),
            latest_periods=1,
        )
    finally:
        source.close()
    values = {row["canonical_series_id"]: row["value"] for row in rows}
    assert values == {
        "CN_PMI_MANUFACTURING": 49.8,
        "CN_PMI_NONMANUFACTURING": 49.0,
    }
    assert all(row["period"] == "2026-08" for row in rows)
    assert all(row["pit_grade"] == "D" for row in rows)


def _row(field: str, source: str, value: float, grade: str, when: datetime, sha: str):
    return {
        "country": "CN",
        "source": source,
        "canonical_series_id": field,
        "source_series_id": field,
        "series_name": field,
        "frequency": "M",
        "unit": "pct_yoy",
        "seasonal_adjustment": "NSA",
        "period": "2026-08",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "value": value,
        "release_at": None if grade == "D" else when,
        "release_date_source": (
            "third_party_current_history_first_seen_only"
            if source in {"SINA_MACRO", "EASTMONEY_MACRO"}
            else "wind_terminal_history"
            if source == "WIND"
            else "official"
        ),
        "first_seen_at": when,
        "available_at": when,
        "pit_grade": grade,
        "source_url": f"https://example.test/{sha}",
        "raw_file": f"raw/{sha}",
        "raw_sha256": sha,
        "retrieved_at": when,
        "parser_version": "test",
    }


def test_fixed_t_and_long_use_approved_fallback_priority(tmp_path):
    conn = get_connection(":memory:")
    first_seen = datetime(2026, 9, 1, 8, 0, tzinfo=CN)
    insert_observations(conn, [
        _row("CN_ONLY_SINA", "SINA_MACRO", 1, "D", first_seen, "s1"),
        _row("CN_BOTH_D", "SINA_MACRO", 1, "D", first_seen, "s2"),
        _row("CN_BOTH_D", "EASTMONEY_MACRO", 2, "D", first_seen, "e2"),
        _row("CN_WITH_B", "EASTMONEY_MACRO", 2, "D", first_seen, "e3"),
        _row("CN_WITH_B", "PBOC", 3, "B", datetime(2026, 9, 5, 8, 0, tzinfo=CN), "b3"),
        _row("CN_WITH_A", "EASTMONEY_MACRO", 2, "D", first_seen, "e4"),
        _row("CN_WITH_A", "NBS", 4, "A", datetime(2026, 9, 6, 8, 0, tzinfo=CN), "a4"),
        _row("CN_WITH_WIND", "EASTMONEY_MACRO", 2, "D", first_seen, "e5"),
        _row("CN_WITH_WIND", "WIND", 3, "D", first_seen, "w5"),
    ])
    sidecar = tmp_path / "estimated.csv"
    sidecar.write_text(
        "canonical_series_id,source,period,period_end,value,estimated_release_date,estimated_available_at\n"
        "CN_WITH_WIND,WIND,2026-08,2026-08-31,3,2026-08-20,2026-08-20T00:00:00+08:00\n",
        encoding="utf-8",
    )
    result = build_as_of_wide(
        conn, "2026-09-30", "CN", start_date="2026-08-01",
        estimated_availability_path=sidecar,
    )
    values = result.values.row(0, named=True)
    provenance = result.provenance.row(0, named=True)
    assert values["CN_ONLY_SINA"] == 1
    assert provenance["CN_ONLY_SINA"] == "SINA_D"
    assert values["CN_BOTH_D"] == 2
    assert provenance["CN_BOTH_D"] == "EASTMONEY_D"
    assert values["CN_WITH_B"] == 3
    assert provenance["CN_WITH_B"] == "PIT_B"
    assert values["CN_WITH_A"] == 4
    assert provenance["CN_WITH_A"] == "PIT_A"
    assert values["CN_WITH_WIND"] == 3
    assert provenance["CN_WITH_WIND"] == "WIND"

    long_result = build_pit_long(
        conn, "CN", start_date="2026-08-01",
        estimated_availability_path=sidecar,
    )
    origins = {
        field: long_result.events.filter(
            long_result.events["canonical_series_id"] == field
        )["selection_origin"].to_list()
        for field in ["CN_ONLY_SINA", "CN_BOTH_D", "CN_WITH_B", "CN_WITH_A", "CN_WITH_WIND"]
    }
    assert origins["CN_ONLY_SINA"] == ["SINA_D"]
    assert origins["CN_BOTH_D"] == ["EASTMONEY_D"]
    assert origins["CN_WITH_B"] == ["EASTMONEY_D", "PIT_B"]
    assert origins["CN_WITH_A"] == ["EASTMONEY_D", "PIT_A"]
    assert origins["CN_WITH_WIND"] == ["WIND"]
    conn.close()
