from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import duckdb
import yaml

from .db import InsertStats, insert_observations, record_crawl_events
from .errors import CrawlSafetyError, DataContractError
from .sources import (
    CustomsSource, MOFSource, NBSSource, PBOCMirrorSource, PBOCSource,
    SAFESource,
)
from .sources.oecd import OECDSeries, OECDSource
from .sources.us_rtdsm import RTDSMSeries, RTDSMSource
from .sources.cn_chinabond import ChinaBondSource
from .sources.us_treasury import USTreasurySource
from .sources.imf_commodity import IMFCommoditySource
from .sources.cn_fallback import FALLBACK_SOURCE_CLASSES
from .timeutils import SHANGHAI, UTC


SOURCE_CLASSES = {
    "NBS": NBSSource,
    "PBOC": PBOCSource,
    "PBOC_MIRROR": PBOCMirrorSource,
    "CUSTOMS": CustomsSource,
    "MOF": MOFSource,
    "SAFE": SAFESource,
    "RTDSM": RTDSMSource,
    "OECD": OECDSource,
    "CHINABOND": ChinaBondSource,
    "USTREASURY": USTreasurySource,
    "IMF": IMFCommoditySource,
}


@dataclass
class PipelineResult:
    source: str
    urls_requested: int = 0
    http_success: int = 0
    raw_downloaded: int = 0
    new_observations: int = 0
    revisions: int = 0
    metadata_updates: int = 0
    unchanged: int = 0
    parse_errors: int = 0
    coverage_warnings: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = "SUCCESS"
    runtime_seconds: float = 0.0


def load_url_manifest(path: str | Path) -> list[str]:
    urls = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    if not urls:
        raise ValueError("URL manifest is empty")
    return urls


def ingest_url_manifest(
    conn: duckdb.DuckDBPyConnection,
    *,
    source_name: str,
    urls: list[str],
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
    observe_same_url_revisions: bool = False,
) -> PipelineResult:
    source_key = source_name.upper()
    if source_key not in SOURCE_CLASSES:
        raise ValueError(f"unsupported China source: {source_name}")
    source = SOURCE_CLASSES[source_key](allow_network=allow_network, config_path=config_path)
    result = PipelineResult(source=source_key)
    started = datetime.now(UTC)
    try:
        _validate_manifest(urls, source.policy)
        for url in urls:
            result.urls_requested += 1
            try:
                fetched = source.fetch(url, refresh=refresh)
                result.http_success += 1
                result.raw_downloaded += int(not fetched.from_cache)
                rows = _parse(source, fetched.content, fetched.artifact)
                if source_key == "NBS":
                    _guard_nbs_revision_anomalies(conn, rows)
                if observe_same_url_revisions:
                    rows = _mark_same_url_revisions(conn, rows)
                stats = insert_observations(conn, rows)
                _merge_stats(result, stats)
            except CrawlSafetyError as exc:
                result.status = "FAILED"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                raise
            except Exception as exc:
                result.parse_errors += 1
                result.status = "PARTIAL"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                _mark_parser_error(source, exc)
        if result.parse_errors and result.new_observations + result.unchanged == 0:
            result.status = "FAILED"
    finally:
        record_crawl_events(conn, source.client.events, parser_version=source.parser_version)
        source.close()
        result.runtime_seconds = (datetime.now(UTC) - started).total_seconds()
        _write_daily_log(result, logs_dir)
    return result



def ingest_cn_fallback(
    conn: duckdb.DuckDBPyConnection,
    *,
    source_name: str,
    latest_periods: int,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
) -> PipelineResult:
    """Archive and ingest reviewed third-party current-history fallback fields."""
    source_key = source_name.upper()
    source_class = FALLBACK_SOURCE_CLASSES.get(source_key)
    if source_class is None:
        raise ValueError(f"unsupported China fallback source: {source_name}")
    if latest_periods < 1:
        raise ValueError("latest_periods must be positive")
    source = source_class(allow_network=allow_network, config_path=config_path)
    result = PipelineResult(source=source_key)
    started = datetime.now(UTC)
    jobs = source.jobs()
    try:
        _validate_manifest([url for _, url in jobs], source.policy)
        for job_name, url in jobs:
            result.urls_requested += 1
            try:
                fetched = source.fetch(url, refresh=refresh)
                result.http_success += 1
                result.raw_downloaded += int(not fetched.from_cache)
                rows = source.parse_job(
                    job_name, fetched.content, fetched.artifact,
                    latest_periods=latest_periods,
                )
                _merge_stats(result, insert_observations(conn, rows))
            except CrawlSafetyError as exc:
                message = f"{url}: {type(exc).__name__}: {exc}"
                if "request budget exhausted" in str(exc):
                    result.status = "DEFERRED_BUDGET"
                    result.errors.append(message)
                    break
                result.status = "FAILED"
                result.errors.append(message)
                raise
            except Exception as exc:
                result.parse_errors += 1
                result.status = "PARTIAL"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                _mark_parser_error(source, exc)
        if result.parse_errors and result.new_observations + result.unchanged == 0:
            result.status = "FAILED"
    finally:
        record_crawl_events(conn, source.client.events, parser_version=source.parser_version)
        source.close()
        result.runtime_seconds = (datetime.now(UTC) - started).total_seconds()
        _write_daily_log(result, logs_dir)
    return result



def ingest_chinabond_history(
    conn: duckdb.DuckDBPyConnection,
    *,
    start_date: date,
    end_date: date,
    closed_before: date,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
) -> PipelineResult:
    """Fetch official ChinaBond history in calendar-year chunks."""

    source = ChinaBondSource(
        allow_network=allow_network, config_path=config_path
    )
    result = PipelineResult(source="CHINABOND")
    started = datetime.now(UTC)
    try:
        current = start_date
        while current <= end_date:
            chunk_end = min(end_date, date(current.year, 12, 31))
            url = source.history_url(current, chunk_end)
            result.urls_requested += 1
            try:
                fetched = source.fetch(url, refresh=refresh)
                result.http_success += 1
                result.raw_downloaded += int(not fetched.from_cache)
                rows = source.parse_history(
                    fetched.content,
                    fetched.artifact,
                    closed_before=closed_before,
                )
                rows = _mark_same_url_revisions(conn, rows)
                _merge_stats(result, insert_observations(conn, rows))
            except CrawlSafetyError as exc:
                result.status = "FAILED"
                result.errors.append(
                    f"{url}: {type(exc).__name__}: {exc}"
                )
                raise
            except Exception as exc:
                result.parse_errors += 1
                result.status = "PARTIAL"
                result.errors.append(
                    f"{url}: {type(exc).__name__}: {exc}"
                )
                _mark_parser_error(source, exc)
            current = date(current.year + 1, 1, 1)
        if (
            result.parse_errors
            and result.new_observations + result.unchanged == 0
        ):
            result.status = "FAILED"
    finally:
        record_crawl_events(
            conn, source.client.events, parser_version=source.parser_version
        )
        source.close()
        result.runtime_seconds = (
            datetime.now(UTC) - started
        ).total_seconds()
        _write_daily_log(result, logs_dir)
    return result


def ingest_us_treasury_history(
    conn: duckdb.DuckDBPyConnection,
    *,
    start_date: date,
    end_date: date,
    closed_before: date,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
) -> PipelineResult:
    """Fetch official U.S. Treasury daily curves in calendar-year chunks."""

    source = USTreasurySource(
        allow_network=allow_network, config_path=config_path
    )
    result = PipelineResult(source="USTREASURY")
    started = datetime.now(UTC)
    try:
        for year in range(start_date.year, end_date.year + 1):
            url = source.history_url(year)
            result.urls_requested += 1
            try:
                fetched = source.fetch(url, refresh=refresh)
                result.http_success += 1
                result.raw_downloaded += int(not fetched.from_cache)
                rows = source.parse_history(
                    fetched.content,
                    fetched.artifact,
                    closed_before=closed_before,
                )
                rows = _mark_same_url_revisions(conn, rows)
                _merge_stats(result, insert_observations(conn, rows))
            except CrawlSafetyError as exc:
                result.status = "FAILED"
                result.errors.append(
                    f"{url}: {type(exc).__name__}: {exc}"
                )
                raise
            except Exception as exc:
                result.parse_errors += 1
                result.status = "PARTIAL"
                result.errors.append(
                    f"{url}: {type(exc).__name__}: {exc}"
                )
                _mark_parser_error(source, exc)
        if (
            result.parse_errors
            and result.new_observations + result.unchanged == 0
        ):
            result.status = "FAILED"
    finally:
        record_crawl_events(
            conn, source.client.events, parser_version=source.parser_version
        )
        source.close()
        result.runtime_seconds = (
            datetime.now(UTC) - started
        ).total_seconds()
        _write_daily_log(result, logs_dir)
    return result


def ingest_imf_commodity(
    conn: duckdb.DuckDBPyConnection,
    *,
    url: str,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
    skip_unchanged_fetch: bool = False,
) -> PipelineResult:
    """Archive and ingest the IMF all-commodity current-history CSV."""

    source = IMFCommoditySource(
        allow_network=allow_network, config_path=config_path
    )
    result = PipelineResult(source="IMF")
    started = datetime.now(UTC)
    result.urls_requested = 1
    try:
        fetched = source.fetch(url, refresh=refresh)
        result.http_success = 1
        result.raw_downloaded = int(not fetched.from_cache)
        if not (skip_unchanged_fetch and fetched.from_cache):
            rows = source.parse_workbook(fetched.content, fetched.artifact)
            rows = _stabilize_current_snapshot_rows(conn, rows)
            rows = _mark_same_url_revisions(conn, rows)
            _merge_stats(result, insert_observations(conn, rows))
    except CrawlSafetyError as exc:
        result.status = "FAILED"
        result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
        raise
    except Exception as exc:
        result.parse_errors = 1
        result.status = "FAILED"
        result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
        _mark_parser_error(source, exc)
    finally:
        record_crawl_events(
            conn, source.client.events, parser_version=source.parser_version
        )
        source.close()
        result.runtime_seconds = (
            datetime.now(UTC) - started
        ).total_seconds()
        _write_daily_log(result, logs_dir)
    return result


def _stabilize_current_snapshot_rows(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict],
) -> list[dict]:
    """Keep unchanged PIT_D snapshots idempotent across daily downloads."""

    stabilized: list[dict] = []
    for row in rows:
        latest = conn.execute(
            """
            SELECT value, CAST(release_at AS VARCHAR),
                   release_date_source, CAST(first_seen_at AS VARCHAR),
                   CAST(available_at AS VARCHAR)
            FROM observation_vintage
            WHERE source = ? AND canonical_series_id = ? AND period = ?
            ORDER BY vintage_no DESC, available_at DESC
            LIMIT 1
            """,
            [
                row["source"],
                row["canonical_series_id"],
                row["period"],
            ],
        ).fetchone()
        if (
            latest is not None
            and math.isclose(
                float(latest[0]),
                float(row["value"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            row = dict(row)
            row.update(
                release_at=latest[1],
                release_date_source=latest[2],
                first_seen_at=latest[3],
                available_at=latest[4],
            )
        stabilized.append(row)
    return stabilized

def _mark_same_url_revisions(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict],
) -> list[dict]:
    """Make a silently changed official page visible only when re-observed.

    New official URLs keep their publication evidence. If the same URL already
    supplied a source/series/period and now carries a different value, the
    retrieval time is the earliest defensible revision-availability bound.
    """
    adjusted: list[dict] = []
    for row in rows:
        latest = conn.execute(
            """
            SELECT value, source_url
            FROM observation_vintage
            WHERE source = ? AND canonical_series_id = ? AND period = ?
            ORDER BY vintage_no DESC, available_at DESC
            LIMIT 1
            """,
            [row["source"], row["canonical_series_id"], row["period"]],
        ).fetchone()
        if (
            latest is not None
            and latest[1] == row.get("source_url")
            and not math.isclose(
                float(latest[0]), float(row["value"]), rel_tol=0.0, abs_tol=1e-12
            )
        ):
            row = dict(row)
            observed_at = row["first_seen_at"]
            row.update(
                release_at=None,
                available_at=observed_at,
                pit_grade="D",
                release_date_source="official_web_revision_first_seen",
            )
        adjusted.append(row)
    return adjusted


def _guard_nbs_revision_anomalies(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict],
) -> None:
    """Fail closed when a secondary NBS page contradicts a primary release.

    Interpretation and spokesperson pages contain many nearby sub-industry and
    comparison values. A conflicting value from such a page is held for review
    instead of becoming a new A-grade vintage. Large cross-URL changes in
    percentage series are also held for review. Silent changes at the same URL
    keep the existing first-seen revision treatment.
    """
    for row in rows:
        incoming_url = str(row.get("source_url") or "")
        latest = conn.execute(
            """
            SELECT value, source_url
            FROM observation_vintage
            WHERE source = 'NBS' AND canonical_series_id = ? AND period = ?
            ORDER BY available_at DESC, vintage_no DESC
            LIMIT 1
            """,
            [row["canonical_series_id"], row["period"]],
        ).fetchone()
        if latest is None or str(latest[1]) == incoming_url:
            continue
        old_value = float(latest[0])
        new_value = float(row["value"])
        if math.isclose(old_value, new_value, rel_tol=0.0, abs_tol=1e-12):
            continue
        existing_url = str(latest[1] or "")
        secondary_conflict = (
            "/zxfbhjd/" in incoming_url and "/zxfb/" in existing_url
        )
        large_percentage_change = (
            row.get("unit") in {"pct", "pct_yoy"}
            and abs(new_value - old_value) > 10.0
        )
        if secondary_conflict or large_percentage_change:
            reason = (
                "secondary NBS page conflicts with primary release"
                if secondary_conflict
                else "large cross-URL NBS percentage revision"
            )
            raise DataContractError(
                f"{reason}: {row['canonical_series_id']} {row['period']} "
                f"{old_value} -> {new_value}; existing={existing_url}; "
                f"incoming={incoming_url}"
            )


def _with_query_parameter(url: str, name: str, value: str) -> str:
    parsed = urlparse(url)
    query = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key != name]
    query.append((name, value))
    return urlunparse(parsed._replace(query=urlencode(query)))


def ingest_rtdsm_manifest(
    conn: duckdb.DuckDBPyConnection,
    *,
    manifest_path: str | Path,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
    skip_unchanged_fetch: bool = False,
) -> PipelineResult:
    payload = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8")) or {}
    jobs = payload.get("series", [])
    if not jobs:
        raise ValueError("RTDSM manifest requires a non-empty 'series' list")
    source = RTDSMSource(allow_network=allow_network, config_path=config_path)
    result = PipelineResult(source="RTDSM")
    started = datetime.now(UTC)
    try:
        urls = [str(job["url"]) for job in jobs]
        _validate_manifest(urls, source.policy)
        for job, url in zip(jobs, urls):
            result.urls_requested += 1
            try:
                fetched = source.fetch(url, refresh=refresh)
                result.http_success += 1
                result.raw_downloaded += int(not fetched.from_cache)
                if skip_unchanged_fetch and fetched.from_cache:
                    continue
                spec = RTDSMSeries(
                    canonical_id=str(job["canonical_id"]),
                    source_id=str(job["source_id"]),
                    name=str(job["name"]),
                    unit=str(job["unit"]),
                    observation_frequency=str(job["observation_frequency"]),
                    seasonal_adjustment=str(job.get("seasonal_adjustment", "SA")),
                )
                _merge_stats(result, insert_observations(conn, source.parse_workbook(fetched.content, fetched.artifact, spec)))
            except CrawlSafetyError as exc:
                result.status = "FAILED"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                raise
            except Exception as exc:
                result.parse_errors += 1
                result.status = "PARTIAL"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                _mark_parser_error(source, exc)
        if result.parse_errors and result.new_observations + result.unchanged == 0:
            result.status = "FAILED"
    finally:
        record_crawl_events(conn, source.client.events, parser_version=source.parser_version)
        source.close()
        result.runtime_seconds = (datetime.now(UTC) - started).total_seconds()
        _write_daily_log(result, logs_dir)
    return result


def ingest_oecd_manifest(
    conn: duckdb.DuckDBPyConnection,
    *,
    manifest_path: str | Path,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
    start_period: str | None = None,
    skip_unchanged_fetch: bool = False,
) -> PipelineResult:
    payload = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8")) or {}
    jobs = payload.get("jobs", []) or _expand_oecd_country_jobs(payload)
    if not jobs:
        raise ValueError("OECD manifest requires a non-empty 'jobs' list")
    source = OECDSource(allow_network=allow_network, config_path=config_path)
    result = PipelineResult(source="OECD")
    started = datetime.now(UTC)
    try:
        urls = [str(job["url"]) for job in jobs]
        if start_period:
            urls = [_with_query_parameter(url, "startPeriod", start_period) for url in urls]
        _validate_manifest(urls, source.policy)
        for job, url in zip(jobs, urls):
            result.urls_requested += 1
            try:
                mappings = {
                    (
                        str(item["ref_area"]), str(item["frequency"]),
                        str(item["measure"]), str(item["unit_measure"]),
                    ): OECDSeries(
                        canonical_id=str(item["canonical_id"]),
                        name=str(item["name"]),
                        unit=str(item["unit"]),
                        seasonal_adjustment=str(item.get("seasonal_adjustment", "UNKNOWN")),
                        country=str(item["country"]) if item.get("country") else None,
                    )
                    for item in job.get("series", [])
                }
                if not mappings:
                    raise ValueError("each OECD job requires explicit series mappings")
                fetched = source.fetch(
                    url,
                    refresh=refresh,
                    headers={"Accept": "text/csv;version=2.0"},
                )
                result.http_success += 1
                result.raw_downloaded += int(not fetched.from_cache)
                if skip_unchanged_fetch and fetched.from_cache:
                    continue
                _merge_stats(result, insert_observations(conn, source.parse_csv(fetched.content, fetched.artifact, mappings)))
            except CrawlSafetyError as exc:
                result.status = "FAILED"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                raise
            except Exception as exc:
                result.parse_errors += 1
                result.status = "PARTIAL"
                result.errors.append(f"{url}: {type(exc).__name__}: {exc}")
                _mark_parser_error(source, exc)
        if result.parse_errors and result.new_observations + result.unchanged == 0:
            result.status = "FAILED"
    finally:
        record_crawl_events(conn, source.client.events, parser_version=source.parser_version)
        source.close()
        result.runtime_seconds = (datetime.now(UTC) - started).total_seconds()
        _write_daily_log(result, logs_dir)
    return result


def _expand_oecd_country_jobs(payload: dict) -> list[dict]:
    countries = payload.get("countries", [])
    if not countries:
        return []
    base = (
        "https://sdmx.oecd.org/public/rest/data/"
        "OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0"
    )
    suffix = "?dimensionAtObservation=AllDimensions"
    jobs: list[dict] = []
    for country in countries:
        ref = str(country["ref_area"])
        prefix = str(country["prefix"])
        jobs.extend(
            [
                {
                    "url": f"{base}/{ref}.Q.B1GQ_Q.XDC._T.{suffix}",
                    "series": [
                        {
                            "ref_area": ref, "frequency": "Q", "measure": "B1GQ_Q",
                            "unit_measure": "XDC", "canonical_id": f"{prefix}_REAL_GDP",
                            "name": "Real GDP", "unit": "national_currency",
                        }
                    ],
                },
                {
                    "url": f"{base}/{ref}.M.CP+UNEMP.IX+PT_LF..{suffix}",
                    "series": [
                        {
                            "ref_area": ref, "frequency": "M", "measure": "CP",
                            "unit_measure": "IX", "canonical_id": f"{prefix}_CPI",
                            "name": "Consumer prices", "unit": "index",
                        },
                        {
                            "ref_area": ref, "frequency": "M", "measure": "UNEMP",
                            "unit_measure": "PT_LF", "canonical_id": f"{prefix}_UNEMPLOYMENT",
                            "name": "Unemployment", "unit": "pct",
                        },
                    ],
                },
            ]
        )
        if country.get("split_production_retail"):
            production_frequency = str(country.get("production_frequency", "M"))
            retail_frequency = str(country.get("retail_frequency", "M"))
            jobs.extend(
                [
                    {
                        "url": f"{base}/{ref}.{production_frequency}.PRVM.IX.BTE.{suffix}",
                        "series": [
                            {
                                "ref_area": ref, "frequency": production_frequency, "measure": "PRVM",
                                "unit_measure": "IX", "canonical_id": f"{prefix}_INDUSTRIAL_PRODUCTION",
                                "name": "Industrial production", "unit": "index",
                            }
                        ],
                    },
                    {
                        "url": f"{base}/{ref}.{retail_frequency}.TOVM.IX.G47.{suffix}",
                        "series": [
                            {
                                "ref_area": ref, "frequency": retail_frequency, "measure": "TOVM",
                                "unit_measure": "IX", "canonical_id": f"{prefix}_RETAIL",
                                "name": "Retail trade volume", "unit": "index",
                            }
                        ],
                    },
                ]
            )
        else:
            jobs.append(
                {
                    "url": f"{base}/{ref}.M.PRVM+TOVM.IX.BTE+G47.{suffix}",
                    "series": [
                        {
                            "ref_area": ref, "frequency": "M", "measure": "PRVM",
                            "unit_measure": "IX", "canonical_id": f"{prefix}_INDUSTRIAL_PRODUCTION",
                            "name": "Industrial production", "unit": "index",
                        },
                        {
                            "ref_area": ref, "frequency": "M", "measure": "TOVM",
                            "unit_measure": "IX", "canonical_id": f"{prefix}_RETAIL",
                            "name": "Retail trade volume", "unit": "index",
                        },
                    ],
                }
            )
    return jobs


def _validate_manifest(urls: list[str], policy: dict) -> None:
    allowed = {str(host).lower() for host in policy.get("allowed_hosts", [])}
    if not allowed:
        raise CrawlSafetyError("source has no allowed_hosts safety list")
    invalid = [url for url in urls if urlparse(url).scheme not in {"http", "https"} or urlparse(url).hostname not in allowed]
    if invalid:
        raise CrawlSafetyError(f"URL outside configured official hosts: {invalid[0]}")
    origins = {(urlparse(url).scheme, urlparse(url).netloc) for url in urls}
    request_budget = policy.get("max_requests_per_run", 100)
    # Reserve one robots.txt request per origin.
    if request_budget is not None and len(urls) + len(origins) > int(request_budget):
        raise CrawlSafetyError(
            f"manifest needs up to {len(urls) + len(origins)} requests but run budget is {request_budget}"
        )


def _parse(source, content: bytes, artifact):
    if isinstance(source, NBSSource):
        return source.parse(content, artifact)
    if isinstance(source, PBOCSource):
        return source.parse_article(content, artifact)
    return source.parse_release(content, artifact)


def _merge_stats(result: PipelineResult, stats: InsertStats) -> None:
    result.new_observations += stats.inserted
    result.revisions += stats.revisions
    result.metadata_updates += stats.metadata_updates
    result.unchanged += stats.unchanged


def _mark_parser_error(source, exc: Exception) -> None:
    if not source.client.events:
        return
    event = source.client.events[-1]
    event.error_type = type(exc).__name__
    event.error_message = str(exc)[:1000]


def _write_daily_log(result: PipelineResult, logs_dir: str | Path) -> None:
    local_day = datetime.now(UTC).astimezone(SHANGHAI).strftime("%Y%m%d")
    path = Path(logs_dir) / f"update_{local_day}.json"
    payload = {"date": local_day, "sources": {}}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"date": local_day, "sources": {}}
    payload.setdefault("sources", {})[result.source] = asdict(result)
    statuses = [row.get("status", "FAILED") for row in payload["sources"].values()]
    payload["status"] = "FAILED" if "FAILED" in statuses else "PARTIAL" if "PARTIAL" in statuses else "SUCCESS"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
