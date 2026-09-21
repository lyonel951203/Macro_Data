from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import json
import os
import time

import httpx
import pytest

import scripts.run_daily_web_update as daily_runner
import macro_pit.pipeline as pipeline_module

from datetime import datetime, timedelta, timezone

from macro_pit.index_discovery import CandidateUrl
from macro_pit.db import get_connection, insert_observations
from macro_pit.errors import CrawlSafetyError, DataContractError
from macro_pit.pipeline import _guard_nbs_revision_anomalies, _mark_same_url_revisions
from macro_pit.pit import get_snapshot, get_work_snapshot

from scripts.run_daily_web_update import (
    DEFAULT_CONFIG,
    _carry_pending_candidates,
    _ensure_retry_schedule,
    _overall_status,
    _recent_start_period,
    _record_candidate_failure,
    dry_run_plan,
    load_config,
    run_source,
    select_candidates,
    RunLock,

)


CN = timezone(timedelta(hours=8))


def _candidate(number: int) -> CandidateUrl:
    return CandidateUrl(
        source="NBS",
        title=f"release {number}",
        url=f"https://www.stats.gov.cn/release/{number}.html",
        period=f"2026-{number:02d}",
        kind="statistics_release",
        index_raw_file="raw/index.html",
    )


def test_default_china_plan_has_official_sources_and_no_wind():
    config = load_config(DEFAULT_CONFIG)
    sources = [name for name, item in config["sources"].items() if item["enabled"]]
    plan = dry_run_plan(config, sources)
    assert plan["wind_included"] is False
    assert sources == [
        "NBS", "PBOC", "PBOC_MIRROR", "CUSTOMS", "MOF", "SAFE",
        "EASTMONEY_MACRO", "SINA_MACRO", "OECD",
    ]
    web = [
        item for item in plan["sources"]
        if item["source"] in {"NBS", "PBOC", "PBOC_MIRROR", "CUSTOMS", "MOF", "SAFE"}
    ]
    oecd = next(item for item in plan["sources"] if item["source"] == "OECD")
    assert all(item["index_urls"] for item in web)
    fallbacks = [
        item for item in plan["sources"]
        if item["source"] in {"EASTMONEY_MACRO", "SINA_MACRO"}
    ]
    assert len(fallbacks) == 2
    assert all(item["latest_periods"] == 3 for item in fallbacks)
    assert all(
        item["mode"] == "third_party_current_history_first_seen_fallback"
        for item in fallbacks
    )
    assert oecd["mode"] == "official_sdmx_recent_periods"
    assert oecd["recent_lookback_months"] == 18
    assert [Path(path).name for path in oecd["job_manifests"]] == ["oecd_china_core.yml"]
    mof = next(item for item in plan["sources"] if item["source"] == "MOF")
    assert mof["mode"] == "official_web_index"
    assert mof["bootstrap_existing_as_baseline"] is True
    assert all("gks.mof.gov.cn" in url for url in mof["index_urls"])
    mirror = next(
        item for item in plan["sources"] if item["source"] == "PBOC_MIRROR"
    )
    assert mirror["mode"] == "government_reprint_indexes"
    assert mirror["independent_indexes"] is True
    assert mirror["independent_candidates"] is True
    assert len(mirror["index_urls"]) == 3


def test_global_plan_has_oecd_rtdsm_chinabond_and_imf():
    config = load_config(Path(DEFAULT_CONFIG).with_name("daily_global_update.yml"))
    sources = [name for name, item in config["sources"].items() if item["enabled"]]
    plan = dry_run_plan(config, sources)
    assert plan["wind_included"] is False
    assert sources == ["OECD", "RTDSM", "CHINABOND", "USTREASURY", "IMF"]
    oecd = next(item for item in plan["sources"] if item["source"] == "OECD")
    rtdsm = next(item for item in plan["sources"] if item["source"] == "RTDSM")
    imf = next(item for item in plan["sources"] if item["source"] == "IMF")
    treasury = next(
        item for item in plan["sources"]
        if item["source"] == "USTREASURY"
    )
    chinabond = next(
        item for item in plan["sources"] if item["source"] == "CHINABOND"
    )
    assert {Path(path).name for path in oecd["job_manifests"]} == {
        "oecd_core_part1.yml", "oecd_core_part2.yml"
    }
    assert oecd["mode"] == "official_sdmx_recent_periods"
    assert oecd["recent_lookback_months"] == 18
    assert [Path(path).name for path in rtdsm["job_manifests"]] == ["rtdsm_core.yml"]
    assert rtdsm["mode"] == "official_rtdsm_conditional_files"
    assert chinabond["mode"] == "official_daily_curves_to_closed_month_end"
    assert chinabond["history_start"] == "2006-03-01"
    assert treasury["mode"] == "official_daily_curves_to_closed_month_end"
    assert treasury["history_start"] == "2005-01-01"
    assert treasury["daily_lookback_days"] == 75
    assert imf["mode"] == "official_current_history_with_estimated_visibility"
    assert config["lock_path"].replace("\\", "/").endswith("data/daily_web_update/run.lock")


def test_bootstrap_baseline_skips_old_urls_but_rechecks_latest():
    candidates = [_candidate(3), _candidate(2), _candidate(1)]
    known = {
        item.url: {"baseline_ignored_at": "2026-09-16T12:00:00+08:00"}
        for item in candidates
    }
    selected = select_candidates(
        candidates,
        known,
        recheck_latest=1,
        max_candidates=10,
    )
    assert [item.url for item in selected] == [candidates[0].url]


def test_candidate_selection_retries_pending_and_rechecks_latest():
    candidates = [_candidate(3), _candidate(2), _candidate(1)]
    known = {
        candidates[0].url: {"last_success_at": "2026-09-15T19:30:00+08:00"},
        candidates[1].url: {"last_error": "parser changed"},
        candidates[2].url: {"last_success_at": "2026-09-15T19:30:00+08:00"},
    }
    selected = select_candidates(
        candidates,
        known,
        recheck_latest=1,
        max_candidates=10,
    )
    assert [item.url for item in selected] == [
        candidates[1].url,
        candidates[0].url,
    ]


def test_candidate_selection_obeys_run_cap():
    candidates = [_candidate(3), _candidate(2), _candidate(1)]
    selected = select_candidates(
        candidates,
        {},
        recheck_latest=3,
        max_candidates=2,
    )
    assert [item.url for item in selected] == [
        candidates[0].url,
        candidates[1].url,
    ]


def test_failed_candidate_is_carried_after_leaving_current_index():
    old = _candidate(1)
    current = [_candidate(3)]
    known = {
        old.url: {
            "title": old.title,
            "period": old.period,
            "kind": old.kind,
            "index_raw_file": old.index_raw_file,
            "last_error": "parser changed",
        }
    }
    combined = _carry_pending_candidates("NBS", current, known)
    assert [item.url for item in combined] == [current[0].url, old.url]


def test_same_url_revision_is_not_backdated(tmp_path):
    db_path = tmp_path / "daily_revision.duckdb"
    conn = get_connection(db_path)
    released_at = datetime(2020, 2, 10, 10, 0, tzinfo=CN)
    observed_at = datetime(2021, 1, 15, 9, 0, tzinfo=CN)
    base = {
        "country": "CN",
        "source": "NBS",
        "canonical_series_id": "CN_X",
        "source_series_id": "X",
        "series_name": "X",
        "frequency": "M",
        "unit": "pct_yoy",
        "seasonal_adjustment": "NSA",
        "period": "2020-01",
        "period_start": "2020-01-01",
        "period_end": "2020-01-31",
        "value": 1.0,
        "release_at": released_at,
        "first_seen_at": released_at,
        "available_at": released_at,
        "release_date_source": "official_page_timestamp",
        "pit_grade": "A",
        "source_url": "https://www.stats.gov.cn/release/x.html",
        "raw_file": "raw/original.html",
        "raw_sha256": "original",
        "retrieved_at": released_at,
        "parser_version": "test",
    }
    insert_observations(conn, [base])
    changed = dict(base)
    changed.update(
        value=2.0,
        first_seen_at=observed_at,
        retrieved_at=observed_at,
        raw_file="raw/revised.html",
        raw_sha256="revised",
    )
    adjusted = _mark_same_url_revisions(conn, [changed])
    assert adjusted[0]["pit_grade"] == "D"
    assert adjusted[0]["release_at"] is None
    assert adjusted[0]["available_at"] == observed_at
    assert adjusted[0]["release_date_source"] == "official_web_revision_first_seen"
    insert_observations(conn, adjusted)

    sidecar = tmp_path / "estimated.csv"
    sidecar.write_text(
        "canonical_series_id,source,period,period_end,value,"
        "estimated_release_date,estimated_available_at\n"
        "CN_X,WIND,2020-01,2020-01-31,99,2020-02-10,"
        "2020-02-11T00:00:00+08:00\n",
        encoding="utf-8",
    )
    before = get_work_snapshot(
        conn, "2021-01-14T23:59:59+08:00", sidecar, country="CN"
    )
    after = get_work_snapshot(
        conn, "2021-01-15T23:59:59+08:00", sidecar, country="CN"
    )
    strict = get_snapshot(
        conn, "2021-01-15T23:59:59+08:00", country="CN", pit_mode="strict"
    )
    conn.close()
    assert before.filter(before["canonical_series_id"] == "CN_X")["value"][0] == 1.0
    selected = after.filter(after["canonical_series_id"] == "CN_X")
    assert selected["value"][0] == 2.0
    assert selected["work_origin"][0] == "work_web_revision"
    assert strict.filter(strict["canonical_series_id"] == "CN_X")["value"][0] == 1.0


def test_run_lock_waits_before_timing_out(tmp_path):
    lock_path = tmp_path / "shared.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="already running"):
        with RunLock(lock_path, wait_seconds=1, poll_seconds=1):
            pass
    assert time.monotonic() - started >= 0.9



def test_daily_light_and_weekly_revision_configs_are_separate():
    daily = load_config(DEFAULT_CONFIG)
    weekly = load_config(Path(DEFAULT_CONFIG).with_name("weekly_web_revision.yml"))
    assert daily["run_mode"] == "daily_light"
    assert weekly["run_mode"] == "weekly_revision"
    assert daily["sources"]["NBS"]["recheck_latest"] == 1
    assert weekly["sources"]["NBS"]["recheck_latest"] == 3
    assert daily["sources"]["PBOC"]["policy_probe"] is False
    assert weekly["sources"]["PBOC"]["policy_probe"] is True
    assert daily["semantic_audit"]["model"] == "deepseek-flash"
    assert weekly["semantic_audit"]["model"] == "deepseek-flash"
    assert daily["email_notification"]["recipient"] == "718711226@qq.com"
    assert weekly["email_notification"]["recipient"] == "718711226@qq.com"


def test_failed_candidate_uses_one_three_seven_day_backoff():
    candidate = _candidate(1)
    now = datetime(2026, 9, 17, 10, 0, tzinfo=CN)
    entry = {}
    _record_candidate_failure(
        entry, "ValueError: parser changed", now,
        retry_backoff_days=[1, 3, 7], not_found_cooldown_days=30,
    )
    assert entry["failure_count"] == 1
    assert entry["next_retry_at"] == (now + timedelta(days=1)).isoformat()
    assert select_candidates(
        [candidate], {candidate.url: entry}, recheck_latest=1,
        max_candidates=10, now=now + timedelta(hours=23),
    ) == []
    assert select_candidates(
        [candidate], {candidate.url: entry}, recheck_latest=1,
        max_candidates=10, now=now + timedelta(days=1),
    ) == [candidate]
    _record_candidate_failure(
        entry, "ValueError: parser changed", now + timedelta(days=1),
        retry_backoff_days=[1, 3, 7], not_found_cooldown_days=30,
    )
    assert entry["next_retry_at"] == (now + timedelta(days=4)).isoformat()


def test_404_uses_thirty_day_cooldown():
    now = datetime(2026, 9, 17, 10, 0, tzinfo=CN)
    entry = {}
    _record_candidate_failure(
        entry, "HTTPStatusError: 404 Not Found", now,
        retry_backoff_days=[1, 3, 7], not_found_cooldown_days=30,
    )
    assert entry["error_kind"] == "HTTP_404"
    assert entry["next_retry_at"] == (now + timedelta(days=30)).isoformat()


def test_pbo_c_daily_skip_is_neutral_policy_status(tmp_path):
    state = {"last_policy_probe_at": "2026-09-14T02:00:00+08:00"}
    receipt = run_source(
        "PBOC", {"policy_blocked": True, "policy_probe": False}, state,
        db_path=tmp_path / "unused.duckdb", allow_network=False,
        logs_dir=tmp_path,
    )
    assert receipt["status"] == "BLOCKED_POLICY"
    assert receipt["selected"] == 0
    assert _overall_status([receipt]) == "SUCCESS"


def test_customs_unverifiable_tls_is_explicit_neutral_transport_block(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise CrawlSafetyError("cannot verify robots.txt for https://english.customs.gov.cn")

    monkeypatch.setattr(daily_runner, "fetch_and_discover_indexes", blocked)
    state = {}
    receipt = run_source(
        "CUSTOMS",
        {
            "transport_soft_block": True,
            "index_manifests": [],
            "retry_backoff_days": [1, 3, 7],
            "not_found_cooldown_days": 30,
        },
        state,
        db_path=tmp_path / "customs_probe.duckdb",
        allow_network=True,
        logs_dir=tmp_path,
    )
    assert receipt["status"] == "BLOCKED_TRANSPORT"
    assert "cannot verify robots.txt" in receipt["transport_note"]
    assert receipt["errors"] == []
    assert state["transport_status"] == "BLOCKED_TRANSPORT"
    assert _overall_status([receipt]) == "SUCCESS"


def test_recent_start_period_is_month_aligned():
    now = datetime(2026, 9, 17, 10, 0, tzinfo=CN)
    assert _recent_start_period(18, now) == "2025-03"
    assert _recent_start_period(0, now) is None


def test_weekly_pboc_probe_is_neutral_when_robots_disallows(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise CrawlSafetyError("robots.txt disallows this URL: http://www.pbc.gov.cn/x")

    monkeypatch.setattr(daily_runner, "fetch_and_discover_indexes", blocked)
    state = {}
    receipt = run_source(
        "PBOC",
        {
            "policy_blocked": True,
            "policy_probe": True,
            "index_manifests": [],
            "retry_backoff_days": [1, 3, 7],
            "not_found_cooldown_days": 30,
        },
        state,
        db_path=tmp_path / "probe.duckdb",
        allow_network=True,
        logs_dir=tmp_path,
    )
    assert receipt["status"] == "BLOCKED_POLICY"
    assert state["policy_status"] == "BLOCKED_POLICY"
    assert _overall_status([receipt]) == "SUCCESS"


def test_oecd_light_mode_skips_parsing_unchanged_cached_response(tmp_path, monkeypatch):
    manifest = tmp_path / "oecd.yml"
    manifest.write_text(
        """jobs:
  - url: https://sdmx.oecd.org/public/rest/data/test?dimensionAtObservation=AllDimensions
    series:
      - {ref_area: USA, country: US, frequency: M, measure: CP, unit_measure: IX, canonical_id: US_TEST, name: Test, unit: index}
""",
        encoding="utf-8",
    )

    class FakeOECDSource:
        parser_version = "fake"
        policy = {"allowed_hosts": ["sdmx.oecd.org"], "max_requests_per_run": 10}

        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(events=[])

        def fetch(self, url, **kwargs):
            assert "startPeriod=2025-03" in url
            return SimpleNamespace(from_cache=True)

        def parse_csv(self, *args, **kwargs):
            raise AssertionError("unchanged cached OECD response must not be parsed")

        def close(self):
            pass

    monkeypatch.setattr(pipeline_module, "OECDSource", FakeOECDSource)
    conn = get_connection(tmp_path / "light.duckdb")
    result = pipeline_module.ingest_oecd_manifest(
        conn,
        manifest_path=manifest,
        allow_network=True,
        refresh=True,
        start_period="2025-03",
        skip_unchanged_fetch=True,
        logs_dir=tmp_path,
    )
    conn.close()
    assert result.http_success == 1
    assert result.raw_downloaded == 0
    assert result.new_observations == 0


def test_legacy_failure_state_gets_retry_schedule():
    attempted = datetime(2026, 9, 17, 8, 0, tzinfo=CN)
    entry = {
        "last_attempt_at": attempted.isoformat(),
        "last_error": "HTTPStatusError: 404 Not Found",
    }
    _ensure_retry_schedule(
        entry,
        {"retry_backoff_days": [1, 3, 7], "not_found_cooldown_days": 30},
        datetime(2026, 9, 17, 22, 0, tzinfo=CN),
    )
    assert entry["failure_count"] == 1
    assert entry["next_retry_at"] == (attempted + timedelta(days=30)).isoformat()

def test_redundant_pboc_mirror_failure_is_warning_when_period_is_covered(
    tmp_path, monkeypatch
):
    index_manifest = tmp_path / "indexes.txt"
    index_manifest.write_text("https://jrj.sh.gov.cn/SCGK194/index.html\n", encoding="utf-8")
    candidates = [
        CandidateUrl(
            source="PBOC_MIRROR",
            title="2026年8月金融统计数据报告",
            url="https://jrj.sh.gov.cn/SCGK194/20260915/a.html",
            period="2026-08",
            kind="financial_statistics_government_reprint",
            index_raw_file="raw/sh.html",
        ),
        CandidateUrl(
            source="PBOC_MIRROR",
            title="2026年8月金融统计数据报告",
            url="https://jrb.qingdao.gov.cn/jrdt/202609/b.shtml",
            period="2026-08",
            kind="financial_statistics_government_reprint",
            index_raw_file="raw/qd.html",
        ),
    ]

    monkeypatch.setattr(
        daily_runner,
        "fetch_and_discover_indexes",
        lambda *args, **kwargs: (candidates, ["raw/index.html"]),
    )

    def fake_ingest(*args, urls, **kwargs):
        if "qingdao" in urls[0]:
            raise CrawlSafetyError("cannot verify robots.txt")
        return SimpleNamespace(
            new_observations=10,
            revisions=0,
            metadata_updates=0,
            unchanged=0,
            parse_errors=0,
            http_success=1,
            raw_downloaded=1,
            runtime_seconds=1.0,
            errors=[],
            status="SUCCESS",
        )

    monkeypatch.setattr(daily_runner, "ingest_url_manifest", fake_ingest)
    state = {}
    receipt = run_source(
        "PBOC_MIRROR",
        {
            "index_manifests": [str(index_manifest)],
            "recheck_latest": 2,
            "max_candidates_per_run": 2,
            "retry_backoff_days": [1, 3, 7],
            "not_found_cooldown_days": 30,
            "independent_candidates": True,
        },
        state,
        db_path=tmp_path / "test.duckdb",
        allow_network=True,
        logs_dir=tmp_path,
    )
    assert receipt["status"] == "SUCCESS"
    assert receipt["new_observations"] == 10
    assert receipt["errors"] == []
    assert len(receipt["candidate_warnings"]) == 1

def test_fallback_daily_budget_exhaustion_is_neutral_deferred(tmp_path, monkeypatch):
    def exhausted(*args, **kwargs):
        raise CrawlSafetyError("SINA_MACRO daily request budget exhausted (20)")

    monkeypatch.setattr(daily_runner, "ingest_cn_fallback", exhausted)
    receipt = run_source(
        "SINA_MACRO",
        {"latest_periods": 3},
        {},
        db_path=tmp_path / "budget.duckdb",
        allow_network=True,
        logs_dir=tmp_path,
    )
    assert receipt["status"] == "DEFERRED_BUDGET"
    assert receipt["errors"] == []
    assert "daily request budget exhausted" in receipt["deferred_reason"]
    assert _overall_status([receipt]) == "SUCCESS"


def test_nbs_secondary_page_conflict_is_rejected(tmp_path):
    db_path = tmp_path / "nbs_guard.duckdb"
    conn = get_connection(db_path)
    at = datetime(2026, 9, 15, 10, 0, tzinfo=CN)
    base = {
        "country": "CN",
        "source": "NBS",
        "canonical_series_id": "CN_PPI_YOY",
        "source_series_id": "PPI_YOY",
        "series_name": "PPI",
        "frequency": "M",
        "unit": "pct_yoy",
        "seasonal_adjustment": "NSA",
        "period": "2026-08",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "value": 3.8,
        "release_at": at,
        "first_seen_at": at,
        "available_at": at,
        "release_date_source": "official_page_timestamp",
        "pit_grade": "A",
        "source_url": "https://www.stats.gov.cn/sj/zxfb/202609/primary.html",
        "raw_file": "raw/primary.html",
        "raw_sha256": "primary",
        "retrieved_at": at,
        "parser_version": "test",
    }
    insert_observations(conn, [base])
    conflicting = dict(base)
    conflicting.update(
        value=2.0,
        source_url="https://www.stats.gov.cn/sj/zxfbhjd/202609/q-and-a.html",
        raw_file="raw/q-and-a.html",
        raw_sha256="q-and-a",
    )
    with pytest.raises(DataContractError, match="secondary NBS page conflicts"):
        _guard_nbs_revision_anomalies(conn, [conflicting])
    conn.close()

def test_fallback_pipeline_budget_exhaustion_writes_deferred_log(tmp_path, monkeypatch):
    class FakeClient:
        events = []

    class FakeSinaSource:
        parser_version = "fake_sina"
        policy = {
            "allowed_hosts": ["quotes.sina.cn"],
            "max_requests_per_run": 10,
        }

        def __init__(self, *args, **kwargs):
            self.client = FakeClient()

        def jobs(self):
            return [("industrial", "https://quotes.sina.cn/mac/test")]

        def fetch(self, *args, **kwargs):
            raise CrawlSafetyError("SINA_MACRO daily request budget exhausted (20)")

        def close(self):
            pass

    monkeypatch.setitem(
        pipeline_module.FALLBACK_SOURCE_CLASSES, "SINA_MACRO", FakeSinaSource
    )
    conn = get_connection(tmp_path / "pipeline_budget.duckdb")
    result = pipeline_module.ingest_cn_fallback(
        conn,
        source_name="SINA_MACRO",
        latest_periods=3,
        allow_network=True,
        refresh=True,
        logs_dir=tmp_path,
    )
    conn.close()
    assert result.status == "DEFERRED_BUDGET"
    assert result.parse_errors == 0
    daily_log = json.loads(
        (tmp_path / f"update_{datetime.now(CN):%Y%m%d}.json").read_text(
            encoding="utf-8"
        )
    )
    assert daily_log["status"] == "SUCCESS"
    assert daily_log["sources"]["SINA_MACRO"]["status"] == "DEFERRED_BUDGET"


@pytest.mark.parametrize(
    ("body", "start_period", "allow_no_recent", "expected_status", "expected_no_records"),
    [
        ("NoRecordsFound", "2025-03", True, "SUCCESS", 1),
        ("NoRecordsFound", "2025-03", False, "FAILED", 0),
        ("NotFound", "2025-03", True, "FAILED", 0),
        ("NoRecordsFound", None, True, "FAILED", 0),
    ],
)
def test_oecd_recent_no_records_is_not_a_query_failure(
    tmp_path, monkeypatch, body, start_period, allow_no_recent,
    expected_status, expected_no_records
):
    manifest = tmp_path / "oecd_no_records.yml"
    manifest.write_text(
        "jobs:\n  - url: https://sdmx.oecd.org/public/rest/data/test\n"
        f"    allow_no_recent_records: {str(allow_no_recent).lower()}\n"
        "    series:\n"
        "      - {ref_area: IND, frequency: Q, measure: B1GQ_Q, "
        "unit_measure: XDC, canonical_id: IN_REAL_GDP, name: Real GDP, unit: national_currency}\n",
        encoding="utf-8",
    )

    class FakeOECDSource:
        parser_version = "fake"
        policy = {"allowed_hosts": ["sdmx.oecd.org"], "max_requests_per_run": 10}

        def __init__(self, *args, **kwargs):
            self.client = SimpleNamespace(events=[])

        def fetch(self, url, **kwargs):
            request = httpx.Request("GET", url)
            response = httpx.Response(404, text=body, request=request)
            raise httpx.HTTPStatusError("404", request=request, response=response)

        def close(self):
            pass

    monkeypatch.setattr(pipeline_module, "OECDSource", FakeOECDSource)
    conn = get_connection(tmp_path / "no_records.duckdb")
    try:
        result = pipeline_module.ingest_oecd_manifest(
            conn, manifest_path=manifest, allow_network=True, refresh=True,
            start_period=start_period, logs_dir=tmp_path,
        )
    finally:
        conn.close()
    assert result.status == expected_status
    assert result.no_recent_records == expected_no_records
    assert result.parse_errors == (0 if expected_no_records else 1)
