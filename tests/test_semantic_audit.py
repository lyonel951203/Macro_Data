from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from macro_pit.db import get_connection, insert_observations
import macro_pit.semantic_audit as audit


CN = timezone(timedelta(hours=8))


def _row(raw: Path, retrieved: datetime) -> dict:
    return {
        "country": "CN",
        "source": "NBS",
        "canonical_series_id": "CN_PPI_YOY",
        "source_series_id": "PPI_YOY",
        "series_name": "PPI同比",
        "frequency": "M",
        "unit": "pct_yoy",
        "seasonal_adjustment": "NSA",
        "period": "2026-08",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "value": 3.8,
        "release_at": retrieved,
        "release_date_source": "official_page_timestamp",
        "first_seen_at": retrieved,
        "available_at": retrieved,
        "pit_grade": "A",
        "source_url": "https://www.stats.gov.cn/release.html",
        "raw_file": str(raw),
        "raw_sha256": "a" * 64,
        "retrieved_at": retrieved,
        "parser_version": "test",
    }


def _daily(start: datetime, finish: datetime) -> dict:
    return {
        "run_id": "20260918T220000",
        "started_at": start.isoformat(),
        "finished_at": finish.isoformat(),
        "sources": [{
            "source": "NBS", "errors": [], "index_errors": [],
            "candidate_warnings": [],
        }],
    }


def _settings(report_dir: Path) -> dict:
    return {
        "enabled": True,
        "report_dir": str(report_dir),
        "model": "deepseek-flash",
        "max_candidates": 24,
        "max_excerpt_chars": 800,
    }


def test_no_change_skips_api_and_writes_report(tmp_path, monkeypatch):
    db = tmp_path / "empty.duckdb"
    conn = get_connection(db)
    conn.close()
    monkeypatch.setattr(
        audit, "call_deepseek",
        lambda **kwargs: pytest.fail("API should not be called"),
    )
    now = datetime(2026, 9, 18, 22, 0, tzinfo=CN)
    result = audit.run_semantic_audit(
        db_path=db,
        daily_report=_daily(now, now + timedelta(minutes=1)),
        settings=_settings(tmp_path / "reports"),
        root=tmp_path,
    )
    assert result["status"] == "SKIPPED_NO_CHANGES"
    assert result["api_called"] is False
    assert Path(result["report_md"]).is_file()


def test_change_without_key_is_durable_skip(tmp_path, monkeypatch):
    raw = tmp_path / "release.html"
    raw.write_text("<p>2026年8月PPI同比上涨3.8%</p>", encoding="utf-8")
    at = datetime(2026, 9, 18, 22, 1, tzinfo=CN)
    db = tmp_path / "one.duckdb"
    conn = get_connection(db)
    insert_observations(conn, [_row(raw, at)])
    conn.close()
    monkeypatch.setattr(audit, "_load_key", lambda settings: (None, "test"))
    result = audit.run_semantic_audit(
        db_path=db,
        daily_report=_daily(at - timedelta(minutes=1),
                            at + timedelta(minutes=1)),
        settings=_settings(tmp_path / "reports"),
        root=tmp_path,
    )
    assert result["status"] == "SKIPPED_NO_KEY"
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["value"] == 3.8


def test_mocked_deepseek_response_is_validated(tmp_path, monkeypatch):
    raw = tmp_path / "release.html"
    raw.write_text("<p>2026年8月PPI同比上涨3.8%</p>", encoding="utf-8")
    at = datetime(2026, 9, 18, 22, 1, tzinfo=CN)
    db = tmp_path / "one.duckdb"
    conn = get_connection(db)
    insert_observations(conn, [_row(raw, at)])
    conn.close()
    monkeypatch.setattr(audit, "_load_key", lambda settings: ("secret", "test"))

    def fake_call(*, api_key, settings, prompt):
        assert api_key == "secret"
        assert "raw_file" not in prompt["candidates"][0]
        assert prompt["evidence"][0]["excerpt"].endswith("3.8%")
        cid = prompt["candidates"][0]["candidate_id"]
        return {
            "overall": "PASS",
            "summary": "记录与证据一致",
            "items": [{
                "candidate_id": cid,
                "verdict": "PASS",
                "confidence": 0.99,
                "reason": "PPI同比和数值均一致",
                "evidence_quote": "PPI同比上涨3.8%",
                "expected_value": 3.8,
            }],
            "operational_findings": [],
        }, {"model": "deepseek-flash", "usage": {"total_tokens": 100}}

    monkeypatch.setattr(audit, "call_deepseek", fake_call)
    result = audit.run_semantic_audit(
        db_path=db,
        daily_report=_daily(at - timedelta(minutes=1),
                            at + timedelta(minutes=1)),
        settings=_settings(tmp_path / "reports"),
        root=tmp_path,
    )
    assert result["status"] == "PASS"
    assert result["api_called"] is True
    assert result["items"][0]["expected_value"] == 3.8


def test_unknown_candidate_id_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        audit._validate({
            "overall": "PASS",
            "items": [{
                "candidate_id": "invented",
                "verdict": "PASS",
                "confidence": 1,
            }],
        }, {"real"})


def test_api_destination_is_pinned():
    with pytest.raises(ValueError, match="only be sent"):
        audit.call_deepseek(
            api_key="secret",
            settings={"base_url": "https://example.com", "api_attempts": 1},
            prompt={},
        )
