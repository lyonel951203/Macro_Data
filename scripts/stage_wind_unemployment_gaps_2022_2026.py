"""Stage the seven remaining surveyed-unemployment gaps from Wind.

The observations remain WIND/PIT_D. Official NBS releases only anchor their
research-sidecar availability timestamps; inferred rows use the same release's
reported month-on-month change to recover the preceding January value.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "reports/v2/wind_midgap_20260921/wind_cli_2022_2026_unemployment.json"
OVERRIDES = ROOT / "config/estimated_availability_overrides_v1.csv"
OUTPUT = ROOT / "data/manual_import/wind_mcp/batch12_unemployment_gaps_2022_2026.json"
CANONICAL = "CN_URBAN_SURVEYED_UNEMPLOYMENT"
WIND_CODE = "M5650805"
DATES = {
    "20220131", "20220430", "20230131", "20240131", "20250131",
    "20251231", "20260131",
}


def main() -> None:
    raw_bytes = RAW.read_bytes()
    raw_hash = hashlib.sha256(raw_bytes).hexdigest()
    envelope = json.loads(raw_bytes.decode("utf-8-sig"))
    if envelope.get("isError") or envelope.get("ok") is False:
        raise ValueError("Wind CLI returned an error")
    metrics = json.loads(envelope["content"][0]["text"])["metrics"]
    source_block = next(block for block in metrics if block["meta"]["code"] == WIND_CODE)
    meta = source_block["meta"]
    expected_meta = {
        "code": WIND_CODE,
        "name": "中国:城镇调查失业率",
        "unit": "%",
        "source": "国家统计局",
        "updateDate": "20260915",
        "beginDate": "20180131",
        "endDate": "20260831",
        "freq": "月",
    }
    if meta != expected_meta:
        raise ValueError(f"Wind metadata differs from reviewed response: {meta}")
    selected = [
        (day, value)
        for day, value in zip(source_block["date"], source_block["value"])
        if day in DATES
    ]
    if {day for day, _ in selected} != DATES or len(selected) != len(DATES):
        raise ValueError("expected exactly seven missing dates")

    periods = {f"{day[:4]}-{day[4:6]}" for day in DATES}
    with OVERRIDES.open(encoding="utf-8-sig", newline="") as handle:
        anchors = {
            row["period"]: row
            for row in csv.DictReader(handle)
            if row["canonical_series_id"] == CANONICAL
            and row["source"] == "WIND"
            and row["period"] in periods
        }
    if set(anchors) != periods:
        raise ValueError("availability anchors do not match selected Wind dates")
    for day, value in selected:
        period = f"{day[:4]}-{day[4:6]}"
        if abs(float(value) - float(anchors[period]["value"])) > 1e-9:
            raise ValueError(f"official/Wind value mismatch: {day}")

    conn = duckdb.connect(str(ROOT / "macro_pit_v2.duckdb"), read_only=True)
    existing = conn.execute(
        """SELECT period, value, pit_grade, source FROM observation_vintage
           WHERE country='CN' AND canonical_series_id=?
             AND period IN (SELECT unnest(?))""",
        [CANONICAL, sorted(periods)],
    ).fetchall()
    conn.close()
    expected_values = {f"{day[:4]}-{day[4:6]}": float(value) for day, value in selected}
    for period, value, grade, source in existing:
        if source != "WIND" or grade != "D" or abs(float(value) - expected_values[period]) > 1e-9:
            raise ValueError(f"unexpected existing target version: {(period, value, grade, source)}")
    if len(existing) not in (0, len(selected)):
        raise ValueError(f"partially ingested batch 12: {existing}")

    pulled_at = datetime.fromtimestamp(RAW.stat().st_mtime).astimezone().isoformat()
    payload = {
        "pulled_at": pulled_at,
        "channel": "wind-mcp:economic_data.query_economic_indicator_data",
        "source_url": "wind-mcp://economic_data/query_economic_indicator_data",
        "request": {
            "question": WIND_CODE,
            "beginDate": "2022-01-01",
            "endDate": "2026-08-31",
        },
        "upstream_raw_file": str(RAW.relative_to(ROOT)).replace("\\", "/"),
        "upstream_raw_sha256": raw_hash,
        "response": {
            "data": [{
                "meta": meta,
                "date": [day for day, _ in selected],
                "value": [value for _, value in selected],
            }]
        },
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") != serialized:
        raise ValueError("existing batch 12 differs; refusing to rewrite immutable source")
    OUTPUT.write_text(serialized, encoding="utf-8")
    print(f"staged={len(selected)} existing={len(existing)} raw_sha256={raw_hash}")


if __name__ == "__main__":
    main()
