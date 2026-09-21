"""Promote three April 2010 PMI cells from Wind fallback to official PIT_B.

The China Federation of Logistics & Purchasing was the original joint
publisher.  Its page gives a calendar date but no publication time, so these
rows use PIT_B and become available at 00:00 on the following Shanghai day.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from macro_pit.db import get_connection, insert_observations


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/cflp/2026/09/21/d9dd5c4456a7173bd273ad068a8e1b614362e09a7f3516e7e5641fb3d2ce3e02.html"
REPORT_DIR = ROOT / "reports/v2/gap_backfill_batches_20260921"
URL = "http://old.chinawuliu.com.cn/office/30/176/8125.shtml"
TZ = ZoneInfo("Asia/Shanghai")
VALUES = [
    ("CN_PMI_MANUFACTURING", "PMI_MANUFACTURING", "制造业采购经理指数", 55.7, "中国制造业采购经理指数（PMI）为55.7%"),
    ("CN_PMI_PRODUCTION", "PMI_PRODUCTION", "制造业PMI生产指数", 59.1, "本月生产指数59.1%"),
    ("CN_PMI_NEW_ORDERS", "PMI_NEW_ORDERS", "制造业PMI新订单指数", 59.3, "本月新订单指数59.3%"),
]


def build_records(conn) -> list[dict]:
    raw_bytes = RAW.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest != RAW.stem:
        raise ValueError("CFLP raw filename/hash mismatch")
    text = raw_bytes.decode("utf-8")
    if "日期： 2010-05-01" not in text:
        raise ValueError("CFLP publication date changed or missing")
    for *_, evidence in VALUES:
        if evidence not in text:
            raise ValueError(f"CFLP evidence missing: {evidence}")
    retrieved = conn.execute(
        "SELECT completed_at FROM crawl_log WHERE raw_sha256=? AND success=true ORDER BY completed_at LIMIT 1",
        [digest],
    ).fetchone()
    if retrieved is None:
        raise ValueError("missing CFLP crawl log")
    release = datetime.combine(date(2010, 5, 1), time.min, tzinfo=TZ)
    available = release + timedelta(days=1)
    records = []
    for canonical, source_id, name, value, _ in VALUES:
        records.append({
            "country": "CN",
            "source": "CFLP",
            "canonical_series_id": canonical,
            "source_series_id": source_id,
            "series_name": name,
            "frequency": "M",
            "unit": "index",
            "seasonal_adjustment": "SA",
            "period": "2010-04",
            "period_start": date(2010, 4, 1),
            "period_end": date(2010, 4, 30),
            "value": value,
            "release_at": release,
            "release_date_source": "official_page_date_only",
            "first_seen_at": retrieved[0],
            "available_at": available,
            "pit_grade": "B",
            "source_url": URL,
            "raw_file": str(RAW.relative_to(ROOT)).replace("\\", "/"),
            "raw_sha256": digest,
            "retrieved_at": retrieved[0],
            "parser_version": "cflp_official_pmi_gap_v1",
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=ROOT / "macro_pit_v2.duckdb")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection(args.db_path, read_only=True) as conn:
        records = build_records(conn)
        existing = conn.execute(
            """SELECT canonical_series_id, source, pit_grade, value
               FROM observation_vintage
               WHERE country='CN' AND period='2010-04'
                 AND canonical_series_id IN ('CN_PMI_MANUFACTURING','CN_PMI_PRODUCTION','CN_PMI_NEW_ORDERS')
                 AND pit_grade IN ('A','B')"""
        ).fetchall()
    if existing:
        raise ValueError(f"official A/B already exists for CFLP targets: {existing}")

    fields = ["canonical_series_id", "period", "value", "source", "pit_grade", "release_at", "available_at", "source_url", "raw_file"]
    with (REPORT_DIR / "cflp_pmi_apr2010.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in records)

    summary = {"status": "STAGED", "rows": len(records), "pit_grade": "B", "reason": "official date-only original manuscript"}
    if args.ingest:
        with get_connection(args.db_path) as conn:
            before = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            result = insert_observations(conn, records)
            after = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
        if result.inserted != len(records):
            raise ValueError(f"unexpected CFLP insert result: {result}")
        summary.update({"status": "INGESTED", "inserted": result.inserted, "db_before": before, "db_after": after})
    (REPORT_DIR / "cflp_pmi_apr2010_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
