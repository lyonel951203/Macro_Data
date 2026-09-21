"""Archive and ingest the January 2014 reproduction of SAFE December data.

The SAFE article has disappeared from the current official news archive, but
People's Daily retained the complete release and attributes it to SAFE.  The
reproduction is therefore PIT_B.  Its page timestamp is kept as ``release_at``
and availability is conservatively delayed to the next Shanghai calendar day.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from macro_pit.db import get_connection, insert_observations, record_crawl_events
from macro_pit.http import PoliteHttpClient
from macro_pit.sources.cn_common import html_text


ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = ROOT / "reports/v2/gap_backfill_batches_20260921"
# The legacy host presents a mismatched TLS certificate in 2026. Its public
# HTTP endpoint remains available and is used only after a robots.txt check.
URL = "http://finance.people.com.cn/money/n/2014/0124/c42877-24217093.html"
TZ = ZoneInfo("Asia/Shanghai")
RELEASE_AT = datetime(2014, 1, 24, 10, 31, tzinfo=TZ)
AVAILABLE_AT = datetime(2014, 1, 25, 0, 0, tzinfo=TZ)

# Values are the release's displayed USD amounts divided by ten so the stored
# unit is billions of US dollars.  They intentionally differ from later SAFE
# time-series workbooks for several fields; preserving that difference is the
# purpose of point-in-time storage.
VALUES = [
    (
        "CN_BANK_FX_SETTLEMENT_USD",
        "BANK_FX_SETTLEMENT_USD",
        "银行结汇",
        186.8,
        "银行结汇11422亿元人民币（等值1868亿美元）",
    ),
    (
        "CN_BANK_FX_SALES_USD",
        "BANK_FX_SALES_USD",
        "银行售汇",
        155.7,
        "售汇9525亿元人民币（等值1557亿美元）",
    ),
    (
        "CN_BANK_FX_NET_SETTLEMENT_USD",
        "BANK_FX_NET_SETTLEMENT_USD",
        "银行结售汇差额",
        31.0,
        "结售汇顺差1897亿元人民币（等值310亿美元）",
    ),
    (
        "CN_CROSS_BORDER_RECEIPTS_USD",
        "CROSS_BORDER_RECEIPTS_USD",
        "涉外收入",
        311.3,
        "涉外收入19041亿元人民币（等值3113亿美元）",
    ),
    (
        "CN_CROSS_BORDER_PAYMENTS_USD",
        "CROSS_BORDER_PAYMENTS_USD",
        "对外付款",
        303.0,
        "对外付款18532亿元人民币（等值3030亿美元）",
    ),
    (
        "CN_CROSS_BORDER_NET_RECEIPTS_USD",
        "CROSS_BORDER_NET_RECEIPTS_USD",
        "涉外收付款差额",
        8.3,
        "涉外收付款顺差508亿元人民币（等值83亿美元）",
    ),
]


def fetch_artifact(db_path: Path):
    policy = {
        "concurrency": 1,
        "user_agent": "macro-pit-research/0.1 (read-only; single-threaded)",
        "connect_timeout_seconds": 15,
        "read_timeout_seconds": 45,
        "respect_robots_txt": True,
        "stop_on_robots_error": True,
        "min_interval_seconds": 20,
        "jitter_seconds": 5,
        "max_requests_per_run": 5,
        "max_requests_per_day": 10,
        "max_consecutive_failures": 3,
        "max_retries": 2,
        "retry_backoff_seconds": 30,
        "block_statuses": [401, 403, 407, 429],
    }
    with PoliteHttpClient(
        source="SAFE_REPRINT",
        policy=policy,
        allow_network=True,
    ) as client:
        try:
            result = client.fetch(URL)
        finally:
            with get_connection(db_path) as conn:
                record_crawl_events(
                    conn,
                    client.events,
                    parser_version="safe_dec2013_people_reprint_v1",
                )
    return result.artifact, result.content


def build_records(artifact, content: bytes) -> list[dict]:
    _, text = html_text(content)
    if "2014年01月24日10:31" not in text.replace(" ", ""):
        raise ValueError("reprint timestamp missing or changed")
    if "国家外汇管理局统计数据显示" not in text:
        raise ValueError("SAFE attribution missing from reprint")
    compact = text.replace(" ", "")
    for *_, evidence in VALUES:
        if evidence not in compact:
            raise ValueError(f"reprint evidence missing: {evidence}")

    records = []
    for canonical, source_id, name, value, _ in VALUES:
        records.append(
            {
                "country": "CN",
                "source": "SAFE",
                "canonical_series_id": canonical,
                "source_series_id": source_id,
                "series_name": name,
                "frequency": "M",
                "unit": "bn_usd",
                "seasonal_adjustment": "NSA",
                "period": "2013-12",
                "period_start": date(2013, 12, 1),
                "period_end": date(2013, 12, 31),
                "value": value,
                "release_at": RELEASE_AT,
                "release_date_source": (
                    "media_reprint_timestamp_conservative_next_day"
                ),
                "first_seen_at": artifact.retrieved_at,
                "available_at": AVAILABLE_AT,
                "pit_grade": "B",
                "source_url": URL,
                "raw_file": artifact.path,
                "raw_sha256": artifact.sha256,
                "retrieved_at": artifact.retrieved_at,
                "parser_version": "safe_dec2013_people_reprint_v1",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db-path", type=Path, default=ROOT / "macro_pit_v2.duckdb"
    )
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    artifact, content = fetch_artifact(args.db_path)
    records = build_records(artifact, content)

    fields = [
        "canonical_series_id",
        "period",
        "value",
        "source",
        "pit_grade",
        "release_at",
        "available_at",
        "release_date_source",
        "source_url",
        "raw_file",
        "raw_sha256",
    ]
    output_csv = REPORT_DIR / "safe_dec2013_reprint.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in records)

    summary = {
        "status": "STAGED",
        "rows": len(records),
        "pit_grade": "B",
        "release_at": RELEASE_AT.isoformat(),
        "available_at": AVAILABLE_AT.isoformat(),
        "source_url": URL,
        "raw_file": artifact.path,
        "raw_sha256": artifact.sha256,
        "reason": "complete SAFE release preserved by a timestamped media reproduction",
    }
    if args.ingest:
        with get_connection(args.db_path) as conn:
            before = conn.execute(
                "SELECT count(*) FROM observation_vintage"
            ).fetchone()[0]
            result = insert_observations(conn, records)
            after = conn.execute(
                "SELECT count(*) FROM observation_vintage"
            ).fetchone()[0]
        summary.update(
            {
                "status": "INGESTED",
                "inserted": result.inserted,
                "revisions": result.revisions,
                "unchanged": result.unchanged,
                "db_before": before,
                "db_after": after,
            }
        )

    output_json = REPORT_DIR / "safe_dec2013_reprint_summary.json"
    output_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
