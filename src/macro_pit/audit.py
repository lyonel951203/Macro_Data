from __future__ import annotations

import csv
import hashlib
import html
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb
import yaml


@dataclass(frozen=True)
class AuditCheck:
    name: str
    value: int | float | str
    status: str
    detail: str


@dataclass(frozen=True)
class AuditResult:
    checks: list[AuditCheck]
    grade_counts: dict[str, int]
    country_series: dict[str, int]
    raw_reference_rate: float
    duplicate_rows: int

    @property
    def passed(self) -> bool:
        return all(check.status != "FAIL" for check in self.checks)


def run_audit(
    conn: duckdb.DuckDBPyConnection,
    *,
    reports_dir: str | Path = "reports",
    registry_path: str | Path = "config/series_registry.yml",
    acceptance_path: str | Path = "config/acceptance.yml",
) -> AuditResult:
    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    if "observation_vintage" not in tables:
        raise RuntimeError("observation_vintage table does not exist")

    total = int(conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0])
    duplicates = int(
        conn.execute(
            """
            SELECT coalesce(sum(n - 1), 0) FROM (
                SELECT count(*) AS n
                FROM observation_vintage
                GROUP BY source, canonical_series_id, period, vintage_no
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    missing_release = int(
        conn.execute(
            "SELECT count(*) FROM observation_vintage WHERE pit_grade IN ('A','B','C') AND release_at IS NULL"
        ).fetchone()[0]
    )
    missing_url = int(
        conn.execute("SELECT count(*) FROM observation_vintage WHERE source_url IS NULL OR trim(source_url) = ''").fetchone()[0]
    )
    invalid_frequency = int(
        conn.execute("SELECT count(*) FROM observation_vintage WHERE frequency NOT IN ('D','W','M','Q','A')").fetchone()[0]
    )
    unit_changes = int(
        conn.execute(
            """
            SELECT count(*) FROM (
                SELECT canonical_series_id FROM observation_vintage
                GROUP BY canonical_series_id HAVING count(DISTINCT unit) > 1
            )
            """
        ).fetchone()[0]
    )
    invalid_values = int(
        conn.execute("SELECT count(*) FROM observation_vintage WHERE NOT isfinite(value)").fetchone()[0]
    )

    raw_rows = conn.execute("SELECT raw_file, raw_sha256 FROM observation_vintage").fetchall()
    valid_raw = sum(_raw_matches(raw_file, raw_sha) for raw_file, raw_sha in raw_rows)
    raw_rate = valid_raw / total if total else 0.0

    schema = {row[0]: row[1] for row in conn.execute("DESCRIBE observation_vintage").fetchall()}
    timestamp_fields = ["release_at", "first_seen_at", "available_at", "retrieved_at"]
    timezone_missing = sum("WITH TIME ZONE" not in str(schema.get(field, "")).upper() for field in timestamp_fields)

    grades = {grade: 0 for grade in "ABCD"}
    for grade, count in conn.execute("SELECT pit_grade, count(*) FROM observation_vintage GROUP BY pit_grade").fetchall():
        grades[str(grade)] = int(count)
    countries = {
        str(country): int(count)
        for country, count in conn.execute(
            "SELECT country, count(DISTINCT canonical_series_id) FROM observation_vintage GROUP BY country"
        ).fetchall()
    }

    parse_failures = http_failures = 0
    if "crawl_log" in tables:
        parse_failures = int(
            conn.execute(
                """
                SELECT count(*) FROM (
                    SELECT error_type,
                           row_number() OVER (PARTITION BY source, url ORDER BY completed_at DESC) AS rn
                    FROM crawl_log
                ) WHERE rn = 1 AND error_type LIKE '%Parser%'
                """
            ).fetchone()[0]
        )
        http_failures = int(
            conn.execute(
                """
                SELECT count(*) FROM (
                    SELECT url, http_status, success,
                           row_number() OVER (PARTITION BY source, url ORDER BY completed_at DESC) AS rn
                    FROM crawl_log
                ) WHERE rn = 1 AND success = false
                  AND NOT (http_status = 404 AND regexp_matches(url, '/robots\\.txt$'))
                """
            ).fetchone()[0]
        )

    revision_count = int(conn.execute("SELECT count(*) FROM observation_vintage WHERE vintage_no > 0").fetchone()[0])
    acceptance_file = Path(acceptance_path)
    acceptance_config = (
        yaml.safe_load(acceptance_file.read_text(encoding="utf-8"))
        if acceptance_file.is_file()
        else {}
    )
    structural_missing_months = acceptance_config.get("china_structural_missing_months", {})
    coverage_rows = _coverage_rows(
        conn,
        registry_path,
        country="CN",
        structural_missing_months=structural_missing_months,
    )
    us_coverage_rows = _coverage_rows(conn, registry_path, country="US")
    global_coverage_rows = _global_coverage_rows(conn)
    missing_period_series = sum(
        1 for row in coverage_rows if row["observed_periods"] and row["coverage"] < 0.95
    )
    checks = [
        _zero("duplicate observations", duplicates),
        _zero("series below 95% internal period coverage", missing_period_series),
        _zero("invalid finite values", invalid_values),
        _zero("unexpected frequency", invalid_frequency),
        _zero("unit changes", unit_changes),
        _zero("release_at missing for PIT A/B/C", missing_release),
        _zero("source_url missing", missing_url),
        AuditCheck("raw reference coverage", f"{raw_rate:.2%}", "PASS" if raw_rate >= 0.999 else "FAIL", f"{valid_raw}/{total} rows resolve to a raw file"),
        _zero("timezone schema missing", timezone_missing),
        AuditCheck("parse failures", parse_failures, "WARN" if parse_failures else "PASS", "see crawl_log"),
        AuditCheck("HTTP failures", http_failures, "WARN" if http_failures else "PASS", "see crawl_log"),
        AuditCheck("revision rows", revision_count, "PASS", "informational; revisions must remain append-only"),
    ]
    result = AuditResult(checks, grades, countries, raw_rate, duplicates)
    _write_coverage_csv(reports / "cn_coverage.csv", coverage_rows)
    _write_coverage_csv(reports / "us_coverage.csv", us_coverage_rows)
    _write_coverage_csv(reports / "global_coverage.csv", global_coverage_rows)
    (reports / "audit.html").write_text(
        _render_audit(result, coverage_rows, global_coverage_rows), encoding="utf-8"
    )
    return result


@lru_cache(maxsize=4096)
def _raw_matches(raw_file: str | None, raw_sha: str | None) -> bool:
    if not raw_file or raw_sha in {None, "", "N/A", "..."}:
        return False
    path = Path(str(raw_file))
    if not path.is_file():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest().lower() == str(raw_sha).lower()


def _zero(name: str, value: int) -> AuditCheck:
    return AuditCheck(name, value, "PASS" if value == 0 else "FAIL", "expected 0")


def _coverage_rows(
    conn: duckdb.DuckDBPyConnection,
    registry_path: str | Path,
    *,
    country: str,
    structural_missing_months: dict[str, list[int]] | None = None,
) -> list[dict[str, Any]]:
    registry_file = Path(registry_path)
    registry = yaml.safe_load(registry_file.read_text(encoding="utf-8")) if registry_file.is_file() else {}
    observed = {
        row[0]: row[1:]
        for row in conn.execute(
            """
            SELECT canonical_series_id, frequency, min(period), max(period), count(DISTINCT period),
                   sum(CASE WHEN pit_grade='A' THEN 1 ELSE 0 END),
                   sum(CASE WHEN pit_grade='B' THEN 1 ELSE 0 END),
                   sum(CASE WHEN pit_grade='C' THEN 1 ELSE 0 END),
                   sum(CASE WHEN pit_grade='D' THEN 1 ELSE 0 END)
            FROM observation_vintage WHERE country=? GROUP BY canonical_series_id, frequency
            """,
            [country],
        ).fetchall()
    }
    rows: list[dict[str, Any]] = []
    for series_id, spec in registry.items():
        if str(spec.get("country", "")).upper() != country.upper():
            continue
        values = observed.get(series_id)
        if values:
            frequency, earliest, latest, periods, pit_a, pit_b, pit_c, pit_d = values
            excluded_months = {
                int(value)
                for value in (structural_missing_months or {}).get(str(spec.get("source")), [])
            }
            expected = _expected_periods(
                str(earliest), str(latest), str(frequency), excluded_months
            )
            coverage = periods / expected if expected else 0.0
        else:
            frequency = spec.get("frequency")
            earliest = latest = None
            periods = pit_a = pit_b = pit_c = pit_d = expected = 0
            coverage = 0.0
        rows.append(
            {
                "canonical_series_id": series_id,
                "source": spec.get("source"),
                "frequency": frequency,
                "earliest_valid_period": earliest,
                "latest_period": latest,
                "observed_periods": periods,
                "expected_periods": expected,
                "coverage": coverage,
                "pit_a_rows": pit_a,
                "pit_b_rows": pit_b,
                "pit_c_rows": pit_c,
                "pit_d_rows": pit_d,
            }
        )
    return rows


def _global_coverage_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    targets = [
        ("JPN", "JP"), ("DEU", "DE"), ("FRA", "FR"), ("GBR", "UK"),
        ("ITA", "IT"), ("CAN", "CA"), ("AUS", "AU"), ("KOR", "KR"),
        ("IND", "IN"), ("BRA", "BR"), ("MEX", "MX"),
    ]
    observed = {
        str(country): {str(series_id) for series_id, in conn.execute(
            "SELECT DISTINCT canonical_series_id FROM observation_vintage WHERE source='OECD' AND country=?",
            [country],
        ).fetchall()}
        for country, _ in targets
    }
    rows = []
    categories = ["REAL_GDP", "CPI", "INDUSTRIAL_PRODUCTION", "UNEMPLOYMENT", "RETAIL"]
    for country, prefix in targets:
        values = {category: f"{prefix}_{category}" in observed[country] for category in categories}
        rows.append(
            {
                "country": country,
                **{category.lower(): values[category] for category in categories},
                "complete": all(values.values()),
                "missing": ";".join(category for category in categories if not values[category]),
            }
        )
    return rows


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


def _write_coverage_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0]) if rows else ["canonical_series_id"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_audit(
    result: AuditResult,
    coverage_rows: list[dict[str, Any]],
    global_coverage_rows: list[dict[str, Any]],
) -> str:
    check_rows = "".join(
        f"<tr><td>{html.escape(check.name)}</td><td>{html.escape(str(check.value))}</td><td>{check.status}</td><td>{html.escape(check.detail)}</td></tr>"
        for check in result.checks
    )
    coverage_html = "".join(
        f"<tr><td>{html.escape(str(row['canonical_series_id']))}</td><td>{html.escape(str(row['source']))}</td><td>{row['coverage']:.1%}</td><td>{row['pit_a_rows']}</td><td>{row['pit_b_rows']}</td><td>{row['pit_c_rows']}</td><td>{row['pit_d_rows']}</td></tr>"
        for row in coverage_rows
    )
    global_html = "".join(
        f"<tr><td>{row['country']}</td><td>{row['real_gdp']}</td><td>{row['cpi']}</td><td>{row['industrial_production']}</td><td>{row['unemployment']}</td><td>{row['retail']}</td><td>{html.escape(row['missing'])}</td></tr>"
        for row in global_coverage_rows
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Macro PIT Audit</title>
<style>body{{font-family:sans-serif;margin:2rem}}table{{border-collapse:collapse;margin-bottom:2rem}}td,th{{border:1px solid #bbb;padding:.4rem}}</style></head><body>
<h1>Macro PIT Audit - {'PASS' if result.passed else 'FAIL'}</h1>
<table><tr><th>Check</th><th>Value</th><th>Status</th><th>Detail</th></tr>{check_rows}</table>
<h2>China coverage</h2><table><tr><th>Series</th><th>Source</th><th>Coverage</th><th>A</th><th>B</th><th>C</th><th>D</th></tr>{coverage_html}</table>
<h2>Global core coverage</h2><table><tr><th>Country</th><th>GDP</th><th>CPI</th><th>IP</th><th>Unemployment</th><th>Retail</th><th>Missing</th></tr>{global_html}</table>
</body></html>"""
