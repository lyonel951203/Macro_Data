from __future__ import annotations

import hashlib

import polars as pl

from macro_pit.acceptance import run_acceptance
from macro_pit.audit import run_audit
from macro_pit.db import get_connection, insert_observations
from macro_pit.discovery import run_discovery


def test_discovery_lists_all_china_sources_without_fake_dates(tmp_path):
    parquet, report = run_discovery(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")
    frame = pl.read_parquet(parquet)
    assert {"NBS", "PBOC", "CUSTOMS", "MOF", "SAFE", "RTDSM", "OECD"}.issubset(set(frame["source"]))
    assert frame["earliest_period"].null_count() == frame.height
    assert "UNVERIFIED" in report.read_text(encoding="utf-8")


def test_audit_generates_html_and_coverage_csv(tmp_path):
    raw = tmp_path / "raw.html"
    raw.write_text("official", encoding="utf-8")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    conn = get_connection(":memory:")
    insert_observations(
        conn,
        [
            {
                "country": "CN",
                "source": "NBS",
                "canonical_series_id": "CN_CPI_YOY",
                "source_series_id": "A010101",
                "series_name": "CPI",
                "frequency": "M",
                "unit": "pct_yoy",
                "seasonal_adjustment": "NSA",
                "period": "2025-01",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "value": 0.5,
                "release_at": "2025-02-10 09:30:00+08:00",
                "release_date_source": "official_page_timestamp",
                "first_seen_at": "2025-02-10 09:31:00+08:00",
                "available_at": "2025-02-10 09:30:00+08:00",
                "pit_grade": "A",
                "source_url": "https://www.stats.gov.cn/release",
                "raw_file": raw.as_posix(),
                "raw_sha256": digest,
                "retrieved_at": "2025-02-10 09:31:00+08:00",
                "parser_version": "test_v1",
            }
        ],
    )
    reports = tmp_path / "reports"
    result = run_audit(conn, reports_dir=reports)
    assert (reports / "audit.html").is_file()
    assert (reports / "cn_coverage.csv").is_file()
    assert result.raw_reference_rate == 1.0
    assert result.duplicate_rows == 0


def test_acceptance_exposes_real_data_gaps_but_synthetic_pit_checks_pass():
    conn = get_connection(":memory:")
    result = run_acceptance(conn)
    checks = {check.label: check for check in result.checks}
    assert checks["Append-only revisions"].passed
    assert checks["Historical PIT leakage test"].passed
    assert checks["Same-day release boundary"].passed
    assert checks["Idempotent observation ingest"].passed
    assert checks["Global coverage (optional)"].passed
    assert checks["China verifiable PIT A+B rows"].passed
    assert "NOT REQUIRED" in checks["China verifiable PIT A+B rows"].value
    assert not checks["China populated series"].passed
    assert not result.passed
