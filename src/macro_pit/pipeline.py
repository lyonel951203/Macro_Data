from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import yaml

from .db import InsertStats, insert_observations, record_crawl_events
from .errors import CrawlSafetyError
from .sources import CustomsSource, MOFSource, NBSSource, PBOCSource, SAFESource
from .sources.oecd import OECDSeries, OECDSource
from .sources.us_rtdsm import RTDSMSeries, RTDSMSource
from .timeutils import SHANGHAI, UTC


SOURCE_CLASSES = {
    "NBS": NBSSource,
    "PBOC": PBOCSource,
    "CUSTOMS": CustomsSource,
    "MOF": MOFSource,
    "SAFE": SAFESource,
    "RTDSM": RTDSMSource,
    "OECD": OECDSource,
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


def ingest_rtdsm_manifest(
    conn: duckdb.DuckDBPyConnection,
    *,
    manifest_path: str | Path,
    allow_network: bool,
    refresh: bool,
    config_path: str | Path | None = None,
    logs_dir: str | Path = "logs",
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
                        "url": f"{base}/{ref}.M.TOVM.IX.G47.{suffix}",
                        "series": [
                            {
                                "ref_area": ref, "frequency": "M", "measure": "TOVM",
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
