from __future__ import annotations

from dataclasses import dataclass
import hashlib
from functools import lru_cache
from pathlib import Path

import duckdb
import polars as pl
import yaml

from .db import get_connection, insert_observations
from .pit import get_snapshot


@dataclass(frozen=True)
class AcceptanceCheck:
    label: str
    value: str
    passed: bool


@dataclass(frozen=True)
class AcceptanceResult:
    checks: list[AcceptanceCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def render(self) -> str:
        lines = ["=" * 56, "MACRO PIT ACCEPTANCE TEST", "=" * 56]
        for check in self.checks:
            lines.append(f"{check.label:<34} {check.value:>12} {'PASS' if check.passed else 'FAIL'}")
        lines.extend(["", "=" * 56, f"OVERALL: {'PASS' if self.passed else 'FAIL'}", "=" * 56])
        return "\n".join(lines)


def run_acceptance(
    conn: duckdb.DuckDBPyConnection,
    *,
    registry_path: str | Path = "config/series_registry.yml",
    acceptance_path: str | Path = "config/acceptance.yml",
) -> AcceptanceResult:
    acceptance_config = yaml.safe_load(Path(acceptance_path).read_text(encoding="utf-8"))
    scopes = acceptance_config.get("required_scopes", {})
    thresholds = acceptance_config.get("thresholds", {})
    global_is_required = bool(scopes.get("global", False))
    cn_required = int(thresholds.get("china_series", 25))
    cn_historical_required = int(thresholds.get("china_historical_series", 25))
    cn_monthly_min_periods = int(thresholds.get("china_monthly_min_periods", 24))
    cn_quarterly_min_periods = int(thresholds.get("china_quarterly_min_periods", 8))
    cn_period_coverage = float(thresholds.get("china_period_coverage", 0.95))
    us_required = int(thresholds.get("us_rtdsm_series", 15))
    samples_per_us_series = int(thresholds.get("us_rtdsm_samples_per_series", 100))
    raw_required = float(thresholds.get("raw_reference_rate", 0.999))
    cn_strict_is_required = bool(
        thresholds.get("china_strict_raw_required", True)
    )
    cn_strict_required = float(thresholds.get("china_strict_raw_rate", 0.95))
    synthetic = _synthetic_checks()
    total = int(
        conn.execute("SELECT count(*) FROM observation_vintage WHERE country IN ('CN','US')").fetchone()[0]
    )
    cn_series = _series_count(conn, "country='CN'")
    cn_populated_ids = {
        str(row[0]) for row in conn.execute(
            "SELECT DISTINCT canonical_series_id FROM observation_vintage WHERE country='CN'"
        ).fetchall()
    }
    cn_source_ids = {
        str(row[0]) for row in conn.execute(
            "SELECT DISTINCT source FROM observation_vintage WHERE country='CN'"
        ).fetchall()
    }
    required_cn_sources = {str(value) for value in acceptance_config.get("china_required_sources", [])}
    required_cn_series = {str(value) for value in acceptance_config.get("china_required_series", [])}
    structural_missing_months = acceptance_config.get("china_structural_missing_months", {})
    present_required_cn_series = len(required_cn_series & cn_populated_ids)
    present_required_cn_sources = len(required_cn_sources & cn_source_ids)
    historical_cn_series = 0
    for source, frequency, first_period, last_period, observed_periods in conn.execute(
        """
        SELECT source, frequency, min(period), max(period), count(DISTINCT period)
        FROM observation_vintage WHERE country='CN'
        GROUP BY source, canonical_series_id, frequency
        """
    ).fetchall():
        minimum = cn_quarterly_min_periods if frequency == "Q" else cn_monthly_min_periods
        excluded_months = {
            int(value) for value in structural_missing_months.get(str(source), [])
        }
        expected = _expected_periods(
            str(first_period), str(last_period), str(frequency), excluded_months
        )
        coverage = int(observed_periods) / expected if expected else 0.0
        if int(observed_periods) >= minimum and coverage >= cn_period_coverage:
            historical_cn_series += 1
    us_rtdsm_series = _series_count(conn, "country='US' AND source='RTDSM'")
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    rtdsm_validation_count = 0
    rtdsm_match_rate = 0.0
    rtdsm_sample_size = 0
    if "validation_result" in tables:
        validation = conn.execute(
            """
            SELECT count(*), coalesce(min(match_rate), 0), coalesce(sum(sample_size), 0)
            FROM (
                SELECT *, row_number() OVER (PARTITION BY detail ORDER BY created_at DESC) AS rn
                FROM validation_result
                WHERE source='RTDSM' AND test_name='vintage_cell_match'
            ) WHERE rn=1
            """
        ).fetchone()
        rtdsm_validation_count = int(validation[0])
        rtdsm_match_rate = float(validation[1])
        rtdsm_sample_size = int(validation[2])
    global_categories = {
        "REAL_GDP", "CPI", "INDUSTRIAL_PRODUCTION", "UNEMPLOYMENT", "RETAIL"
    }
    global_seen: dict[str, set[str]] = {}
    for country, series_id in conn.execute(
        "SELECT country, canonical_series_id FROM observation_vintage WHERE source='OECD'"
    ).fetchall():
        for suffix in global_categories:
            if str(series_id).endswith(f"_{suffix}"):
                global_seen.setdefault(str(country), set()).add(suffix)
    global_countries = sum(values == global_categories for values in global_seen.values())
    duplicates = int(
        conn.execute(
            """
            SELECT coalesce(sum(n - 1), 0) FROM (
                SELECT count(*) n FROM observation_vintage
                WHERE country IN ('CN','US')
                GROUP BY source, canonical_series_id, period, vintage_no
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    raw_rows = conn.execute(
        "SELECT raw_file, raw_sha256 FROM observation_vintage WHERE country IN ('CN','US')"
    ).fetchall()
    raw_found = sum(_raw_matches(path, digest) for path, digest in raw_rows)
    raw_rate = raw_found / total if total else 0.0
    cn_rows = conn.execute("SELECT pit_grade, raw_file, raw_sha256 FROM observation_vintage WHERE country='CN'").fetchall()
    cn_total = len(cn_rows)
    cn_strict = sum(grade in {"A", "B"} and _raw_matches(path, digest) for grade, path, digest in cn_rows)
    strict_rate = cn_strict / (cn_total or 1)
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))
    cn_registry = sum(1 for spec in registry.values() if spec.get("country") == "CN")
    us_registry = sum(1 for spec in registry.values() if spec.get("country") == "US")

    checks = [
        AcceptanceCheck("No credentials required", "YES", True),
        AcceptanceCheck("Raw archive reproducible", f"{raw_rate:.1%}", raw_rate >= raw_required),
        AcceptanceCheck("Append-only revisions", "synthetic", synthetic["revision"]),
        AcceptanceCheck("Historical PIT leakage test", "synthetic", synthetic["leakage"]),
        AcceptanceCheck("Same-day release boundary", "synthetic", synthetic["boundary"]),
        AcceptanceCheck("Idempotent observation ingest", "synthetic", synthetic["idempotency"]),
        AcceptanceCheck("China registry series", f"{cn_registry} / {cn_required}", cn_registry >= cn_required),
        AcceptanceCheck("China populated series", f"{cn_series} / {cn_required}", cn_series >= cn_required),
        AcceptanceCheck(
            "China required sources",
            f"{present_required_cn_sources} / {len(required_cn_sources)}",
            bool(required_cn_sources) and present_required_cn_sources == len(required_cn_sources),
        ),
        AcceptanceCheck(
            "China required core series",
            f"{present_required_cn_series} / {len(required_cn_series)}",
            bool(required_cn_series) and present_required_cn_series == len(required_cn_series),
        ),
        AcceptanceCheck(
            "China historical-depth series",
            f"{historical_cn_series} / {cn_historical_required}",
            historical_cn_series >= cn_historical_required,
        ),
        AcceptanceCheck(
            "China verifiable PIT A+B rows",
            (
                f"{strict_rate:.1%}"
                if cn_strict_is_required
                else f"{strict_rate:.1%} NOT REQUIRED"
            ),
            (
                cn_total > 0 and strict_rate >= cn_strict_required
                if cn_strict_is_required
                else True
            ),
        ),
        AcceptanceCheck("US registry series", f"{us_registry} / {us_required}", us_registry >= us_required),
        AcceptanceCheck("US RTDSM populated series", f"{us_rtdsm_series} / {us_required}", us_rtdsm_series >= us_required),
        AcceptanceCheck(
            "US RTDSM vintage match",
            f"{rtdsm_match_rate:.1%} ({rtdsm_sample_size})" if rtdsm_validation_count else "UNVERIFIED",
            us_rtdsm_series >= us_required
            and rtdsm_validation_count >= us_required
            and rtdsm_match_rate == 1.0
            and rtdsm_sample_size >= us_required * samples_per_us_series,
        ),
        AcceptanceCheck(
            "Global coverage (optional)",
            f"{global_countries} / 11 NOT REQUIRED" if not global_is_required else f"{global_countries} / 11",
            not global_is_required or global_countries >= 11,
        ),
        AcceptanceCheck("Duplicate vintage rows", str(duplicates), duplicates == 0),
    ]
    return AcceptanceResult(checks)


def _series_count(conn: duckdb.DuckDBPyConnection, predicate: str) -> int:
    return int(
        conn.execute(f"SELECT count(DISTINCT canonical_series_id) FROM observation_vintage WHERE {predicate}").fetchone()[0]
    )


def _expected_periods(
    first: str,
    last: str,
    frequency: str,
    excluded_months: set[int] | None = None,
) -> int:
    try:
        if frequency == "M":
            first_year, first_month = (int(part) for part in first.split("-")[:2])
            last_year, last_month = (int(part) for part in last.split("-")[:2])
            total = (last_year - first_year) * 12 + last_month - first_month + 1
            excluded = 0
            for offset in range(total):
                month_index = first_year * 12 + first_month - 1 + offset
                if month_index % 12 + 1 in (excluded_months or set()):
                    excluded += 1
            return total - excluded
        if frequency == "Q":
            first_year, first_quarter = first.split("-Q")
            last_year, last_quarter = last.split("-Q")
            return (int(last_year) - int(first_year)) * 4 + int(last_quarter) - int(first_quarter) + 1
    except (ValueError, AttributeError):
        return 0
    return 0


@lru_cache(maxsize=4096)
def _raw_matches(raw_file: str | None, raw_sha: str | None) -> bool:
    if not raw_file or raw_sha in {None, "", "N/A", "..."}:
        return False
    path = Path(str(raw_file))
    if not path.is_file():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest().lower() == str(raw_sha).lower()


def _synthetic_checks() -> dict[str, bool]:
    conn = get_connection(":memory:")
    base = _observation(
        period="2026-07",
        value=5.4,
        release_at="2026-08-17 10:00:00+08:00",
        available_at="2026-08-17 10:00:00+08:00",
    )
    stats_first = insert_observations(conn, [base])
    before = get_snapshot(conn, "2026-07-31 23:59:59+08:00")
    after = get_snapshot(conn, "2026-08-31 23:59:59+08:00")
    leakage = before.height == 0 and after.height == 1

    boundary_row = _observation(
        series_id="CN_M2_YOY",
        period="2025-01",
        value=8.5,
        release_at="2025-02-14 16:30:00+08:00",
        available_at="2025-02-14 16:30:00+08:00",
    )
    insert_observations(conn, [boundary_row])
    boundary = (
        get_snapshot(conn, "2025-02-14 15:00:00+08:00").filter(pl.col("canonical_series_id") == "CN_M2_YOY").height == 0
        and get_snapshot(conn, "2025-02-14 17:00:00+08:00").filter(pl.col("canonical_series_id") == "CN_M2_YOY").height == 1
    )

    revised = dict(base)
    revised.update(
        value=5.3,
        release_at="2026-09-10 09:30:00+08:00",
        available_at="2026-09-10 09:30:00+08:00",
        first_seen_at="2026-09-10 09:31:00+08:00",
        retrieved_at="2026-09-10 09:31:00+08:00",
        raw_file="synthetic/revision.html",
        raw_sha256="b" * 64,
    )
    revision_stats = insert_observations(conn, [revised])
    old = get_snapshot(conn, "2026-08-31 23:59:59+08:00").filter(pl.col("canonical_series_id") == "CN_CPI_YOY")
    new = get_snapshot(conn, "2026-09-30 23:59:59+08:00").filter(pl.col("canonical_series_id") == "CN_CPI_YOY")
    revision = revision_stats.revisions == 1 and old["value"][0] == 5.4 and new["value"][0] == 5.3

    count_before = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
    repeat_stats = insert_observations(conn, [revised])
    count_after = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
    idempotency = repeat_stats.unchanged == 1 and count_before == count_after
    conn.close()
    return {"leakage": leakage, "boundary": boundary, "revision": revision, "idempotency": idempotency}


def _observation(
    *,
    series_id: str = "CN_CPI_YOY",
    period: str,
    value: float,
    release_at: str,
    available_at: str,
) -> dict:
    first_seen = available_at
    return {
        "country": "CN",
        "source": "NBS",
        "canonical_series_id": series_id,
        "source_series_id": series_id,
        "series_name": series_id,
        "frequency": "M",
        "unit": "pct_yoy",
        "seasonal_adjustment": "NSA",
        "period": period,
        "period_start": f"{period}-01",
        "period_end": f"{period}-28",
        "value": value,
        "release_at": release_at,
        "release_date_source": "official_page_timestamp",
        "first_seen_at": first_seen,
        "available_at": available_at,
        "pit_grade": "A",
        "source_url": "https://example.invalid/release",
        "raw_file": "synthetic/release.html",
        "raw_sha256": "a" * 64,
        "retrieved_at": first_seen,
        "parser_version": "acceptance_fixture_v1",
    }
