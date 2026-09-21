"""Validate and ingest the dated Wind M1 historical revision workbook.

The Wind history-revision sheet contains both the value visible before the
revision and the revised value. The former is written to a derived baseline
override used by the estimated-availability sidecar. The latter is appended
to DuckDB as a dated PIT_D revision event effective 2025-02-14.

Usage:
  py -3.11 scripts/tools/ingest_m1_revision_snapshot.py
  py -3.11 scripts/tools/ingest_m1_revision_snapshot.py --ingest
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from macro_pit.db import get_connection, insert_observations


RAW_ROOT = Path("E:/Macro_Data/data/raw/wind")
OUT_DIR = Path("E:/Macro_Data/reports/v2/history/wind/wind_m1_revision_20250214")
OVERRIDES_PATH = Path("E:/Macro_Data/data/derived/wind_pre_revision_overrides.csv")
PARSER_VERSION = "wind-m1-revision-xlsx-intake/1"
CANONICAL = "CN_M1_YOY"
SOURCE_SERIES_ID = "M0001383"
CN_TZ = timezone(timedelta(hours=8))


def find_workbook() -> Path:
    matches = sorted(RAW_ROOT.rglob("*M1*20250214.xlsx"))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one M1 20250214 workbook, found: {matches}"
        )
    return matches[0]


def load_revision(
    path: Path, first_seen: datetime
) -> tuple[list[dict], list[dict]]:
    head = pd.read_excel(path, sheet_name=0, header=None, nrows=3)
    source_series_id = str(head.iloc[1, 1]).strip()
    revision_date = pd.Timestamp(head.iloc[2, 1]).date()
    if source_series_id != SOURCE_SERIES_ID:
        raise ValueError(f"unexpected series id: {source_series_id}")
    if revision_date.isoformat() != "2025-02-14":
        raise ValueError(f"unexpected revision date: {revision_date}")

    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    available_at = datetime(
        revision_date.year,
        revision_date.month,
        revision_date.day,
        tzinfo=CN_TZ,
    )
    df = pd.read_excel(path, sheet_name=0, header=None, skiprows=5)
    observations: list[dict] = []
    overrides: list[dict] = []
    for row in df.itertuples(index=False, name=None):
        if len(row) < 5 or pd.isna(row[1]) or pd.isna(row[4]):
            continue
        period_end = pd.Timestamp(row[1]).date()
        current_value = float(row[2])
        previous_value = float(row[3])
        revised_value = float(row[4])
        if abs(current_value - revised_value) > 1e-12:
            raise ValueError(
                f"current/revised mismatch for {period_end}: "
                f"{current_value} != {revised_value}"
            )
        if abs(previous_value - revised_value) <= 1e-12:
            raise ValueError(f"unchanged row was marked revised: {period_end}")
        period = period_end.strftime("%Y-%m")
        observations.append({
            "country": "CN",
            "source": "WIND",
            "canonical_series_id": CANONICAL,
            "source_series_id": SOURCE_SERIES_ID,
            "series_name": "中国:M1:同比",
            "frequency": "M",
            "unit": "pct_yoy",
            "seasonal_adjustment": None,
            "period": period,
            "period_start": period_end.replace(day=1),
            "period_end": period_end,
            "value": revised_value,
            "release_at": None,
            "release_date_source": "wind_revision_snapshot_20250214",
            "first_seen_at": first_seen,
            "available_at": available_at,
            "revision_type": "revision",
            "revision_delta": revised_value - previous_value,
            "pit_grade": "D",
            "source_url": "wind-terminal://edb/history-revision",
            "raw_file": str(path),
            "raw_sha256": sha256,
            "retrieved_at": first_seen,
            "parser_version": PARSER_VERSION,
        })
        overrides.append({
            "canonical_series_id": CANONICAL,
            "source": "WIND",
            "period": period,
            "period_end": period_end.isoformat(),
            "pre_revision_value": previous_value,
            "revised_value": revised_value,
            "revision_at": available_at.isoformat(),
            "raw_file": str(path),
            "raw_sha256": sha256,
            "parser_version": PARSER_VERSION,
        })

    periods = sorted(row["period"] for row in overrides)
    expected = [f"2024-{month:02d}" for month in range(1, 13)]
    if periods != expected:
        raise ValueError(f"expected all 12 months of 2024, got: {periods}")
    return observations, overrides


def write_overrides(rows: list[dict]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows)
    if OVERRIDES_PATH.is_file():
        old = pd.read_csv(OVERRIDES_PATH)
        keys = {
            tuple(x)
            for x in new[
                ["canonical_series_id", "source", "period"]
            ].values
        }
        old_keys = old[
            ["canonical_series_id", "source", "period"]
        ].apply(tuple, axis=1)
        old = old[~old_keys.isin(keys)]
        new = pd.concat([old, new], ignore_index=True)
    new = new.sort_values(["canonical_series_id", "source", "period"])
    new.to_csv(OVERRIDES_PATH, index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="macro_pit_v2.duckdb")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    first_seen = datetime.now().astimezone()
    path = find_workbook()
    records, overrides = load_revision(path, first_seen)
    pd.DataFrame(overrides).to_csv(
        OUT_DIR / "review.csv", index=False, encoding="utf-8-sig"
    )

    with get_connection(":memory:") as conn:
        # Cover the real edge case: the dated event has the same revised
        # value as an already imported later terminal series.
        terminal = dict(records[0])
        terminal.update(
            release_date_source=None,
            first_seen_at=first_seen,
            available_at=first_seen,
            revision_type=None,
            revision_delta=None,
            raw_file="synthetic/terminal.xlsx",
            raw_sha256="terminal",
            parser_version="synthetic-terminal/1",
        )
        insert_observations(conn, [terminal])
        first = insert_observations(conn, [records[0]])
        replay = insert_observations(conn, [records[0]])
        assert first.inserted == 1 and first.revisions == 1
        assert replay.unchanged == 1 and replay.inserted == 0

    summary = {
        "status": "VALIDATED",
        "workbook": str(path),
        "raw_sha256": overrides[0]["raw_sha256"],
        "revision_at": overrides[0]["revision_at"],
        "periods": len(overrides),
        "first_period": min(row["period"] for row in overrides),
        "last_period": max(row["period"] for row in overrides),
        "validation": {
            "series_id": SOURCE_SERIES_ID,
            "all_2024_months": True,
            "current_equals_revised": True,
            "all_revision_deltas_nonzero": True,
            "same_value_terminal_event_preserved": True,
            "replay_idempotent": True,
        },
    }

    if args.ingest:
        with get_connection(args.db_path) as conn:
            result = insert_observations(conn, records)
        write_overrides(overrides)
        summary["status"] = "INGESTED"
        summary["ingestion"] = asdict(result)
        summary["overrides_path"] = str(OVERRIDES_PATH)

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

