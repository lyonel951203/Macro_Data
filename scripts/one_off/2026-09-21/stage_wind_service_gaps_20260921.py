"""Stage safe non-January/February gaps in the service production index."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
RAW_FILES = [
    ROOT / "reports/v2/wind_midgap_20260921/wind_cli_service_2017_2021.json",
    ROOT / "reports/v2/wind_midgap_20260921/wind_cli_service_2022_2026.json",
]
OUTPUT = ROOT / "data/manual_import/wind_mcp/batch13_service_production_safe_gaps.json"
REPORT_DIR = ROOT / "reports/v2/wind_midgap_20260921/service_production"
CANONICAL = "CN_SERVICE_PRODUCTION_YOY"
WIND_CODE = "M5767203"
EXPECTED_META = {
    "code": WIND_CODE,
    "name": "中国:服务业生产指数:当月同比",
    "unit": "%",
    "source": "国家统计局",
    "updateDate": "20260915",
    "beginDate": "20161231",
    "endDate": "20260831",
    "freq": "月",
}


def load_wind() -> tuple[dict, list[tuple[str, float]], dict[str, str]]:
    by_day: dict[str, float] = {}
    hashes: dict[str, str] = {}
    meta = None
    for path in RAW_FILES:
        raw = path.read_bytes()
        hashes[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(raw).hexdigest()
        envelope = json.loads(raw.decode("utf-8-sig"))
        if envelope.get("isError") or envelope.get("ok") is False:
            raise ValueError(f"Wind CLI returned an error: {path.name}")
        blocks = json.loads(envelope["content"][0]["text"])["metrics"]
        if len(blocks) != 1:
            raise ValueError(f"expected one Wind block: {path.name}")
        block = blocks[0]
        if block["meta"] != EXPECTED_META:
            raise ValueError(f"Wind metadata changed: {block['meta']}")
        meta = block["meta"]
        if len(block["date"]) != len(block["value"]):
            raise ValueError(f"date/value mismatch: {path.name}")
        for day, value in zip(block["date"], block["value"]):
            if day in by_day:
                raise ValueError(f"duplicate Wind date across windows: {day}")
            by_day[day] = float(value)
    return meta, sorted(by_day.items()), hashes


def main() -> None:
    meta, wind_rows, hashes = load_wind()
    conn = duckdb.connect(str(ROOT / "macro_pit_v2.duckdb"), read_only=True)
    official_rows = conn.execute(
        """SELECT period, value
           FROM observation_vintage
           WHERE country='CN' AND canonical_series_id=? AND source<>'WIND'
           QUALIFY row_number() OVER (PARTITION BY period ORDER BY vintage_no DESC)=1
           ORDER BY period""",
        [CANONICAL],
    ).fetchall()
    wind_existing_rows = conn.execute(
        """SELECT period, value, pit_grade
           FROM observation_vintage
           WHERE country='CN' AND canonical_series_id=? AND source='WIND'
           ORDER BY period, vintage_no""",
        [CANONICAL],
    ).fetchall()
    conn.close()
    official = {period: float(value) for period, value in official_rows}
    wind_existing = {period: (float(value), grade) for period, value, grade in wind_existing_rows}

    overlaps = []
    selected = []
    held = []
    for day, value in wind_rows:
        period = f"{day[:4]}-{day[4:6]}"
        if period in official:
            diff = official[period] - value
            overlaps.append((period, official[period], value, diff))
            if abs(diff) > 1e-9:
                raise ValueError(f"latest official/Wind mismatch: {period} {diff}")
        elif day[4:6] in {"01", "02"}:
            held.append((day, value, "January/February is absent or 1-2-month combined; not a single-month observation"))
        else:
            if period in wind_existing:
                old_value, grade = wind_existing[period]
                if grade != "D" or abs(old_value - value) > 1e-9:
                    raise ValueError(f"unexpected existing Wind target: {period} {old_value}/{grade}")
            selected.append((day, value))

    if len(overlaps) != 57 or len(selected) != 39 or len(held) != 3:
        raise ValueError(
            f"reviewed counts changed: overlap={len(overlaps)} selected={len(selected)} held={len(held)}"
        )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "official_overlap.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["period", "latest_official_value", "wind_value", "difference"])
        writer.writerows(overlaps)
    with (REPORT_DIR / "held_january_february.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["wind_date", "wind_value", "reason"])
        writer.writerows(held)

    pulled_at = max(datetime.fromtimestamp(path.stat().st_mtime).astimezone() for path in RAW_FILES).isoformat()
    payload = {
        "pulled_at": pulled_at,
        "channel": "wind-mcp:economic_data.query_economic_indicator_data",
        "source_url": "wind-mcp://economic_data/query_economic_indicator_data",
        "request": {
            "question": WIND_CODE,
            "windows": ["2017-01-01/2021-12-31", "2022-01-01/2026-08-31"],
        },
        "upstream_raw_sha256": hashes,
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
        raise ValueError("existing batch 13 differs; refusing to rewrite immutable source")
    OUTPUT.write_text(serialized, encoding="utf-8")
    print(f"wind={len(wind_rows)} overlap={len(overlaps)} selected={len(selected)} held={len(held)}")


if __name__ == "__main__":
    main()
