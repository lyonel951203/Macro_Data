from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import polars as pl
from bs4 import BeautifulSoup
import duckdb

from .db import record_crawl_events
from .pipeline import SOURCE_CLASSES, _validate_manifest
from .sources.base import decode_content


@dataclass(frozen=True)
class CandidateUrl:
    source: str
    title: str
    url: str
    period: str | None
    kind: str
    index_raw_file: str


SOURCE_RULES = {
    "PBOC": {
        "base": "http://www.pbc.gov.cn",
        "hosts": {"www.pbc.gov.cn", "pbc.gov.cn"},
        "keywords": ("金融统计数据报告",),
        "kind": "financial_statistics_release",
    },
    "MOF": {
        "base": "https://gks.mof.gov.cn/tongjishuju/",
        "hosts": {"gks.mof.gov.cn"},
        "keywords": ("财政收支情况",),
        "kind": "fiscal_release",
    },
    "SAFE": {
        "base": "https://www.safe.gov.cn",
        "hosts": {"www.safe.gov.cn", "safe.gov.cn"},
        "keywords": ("银行结售汇", "涉外收付款", "外汇储备"),
        "kind": "fx_release",
    },
    "NBS": {
        # Both the combined release/interpretation listing (zxfbhjd) and the
        # longer historical release listing (zxfb) are supported.  Links from
        # zxfbhjd use ../zxfb while links from zxfb use ./YYYYMM, so zxfb is
        # the common base that resolves both forms correctly.
        "base": "https://www.stats.gov.cn/sj/zxfb/",
        "hosts": {"www.stats.gov.cn", "stats.gov.cn"},
        "keywords": (
            "国民经济", "经济运行", "居民消费价格", "工业生产者出厂价格",
            "采购经理指数", "国内生产总值",
        ),
        "kind": "statistics_release",
    },
    "CUSTOMS": {
        "base": "https://english.customs.gov.cn/statics/report/",
        "hosts": {"www.customs.gov.cn", "customs.gov.cn", "english.customs.gov.cn"},
        "keywords": (
            "进出口商品总值表", "进出口总值",
            "Summary of Imports and Exports",
        ),
        "kind": "customs_release",
    },
}


def discover_candidates(source: str, raw_files: list[str | Path]) -> list[CandidateUrl]:
    source_key = source.upper()
    if source_key not in SOURCE_RULES:
        raise ValueError(f"no index discovery rule for {source}")
    rule = SOURCE_RULES[source_key]
    candidates: dict[str, CandidateUrl] = {}
    for raw_file in raw_files:
        path = Path(raw_file)
        soup = BeautifulSoup(decode_content(path.read_bytes()), "lxml")
        for anchor in soup.find_all("a", href=True):
            title = " ".join((anchor.get("title") or anchor.get_text(" ", strip=True)).split())
            if not title or not any(keyword in title for keyword in rule["keywords"]):
                continue
            url = urljoin(str(rule["base"]), str(anchor["href"]))
            if (urlparse(url).hostname or "").lower() not in rule["hosts"]:
                continue
            if not re.search(r"/20\d{2}(?:\d{2})?/|20\d{10,}", url):
                continue
            candidates[url] = CandidateUrl(
                source=source_key,
                title=title,
                url=url,
                period=_title_period(title),
                kind=str(rule["kind"]),
                index_raw_file=path.as_posix(),
            )
    return sorted(candidates.values(), key=lambda item: (item.period or "", item.url), reverse=True)


def write_candidates(
    candidates: list[CandidateUrl],
    *,
    output_dir: str | Path = "data/discovery",
) -> tuple[Path, Path]:
    if not candidates:
        raise ValueError("candidate list is empty")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = candidates[0].source.lower()
    parquet_path = output / f"{source}_candidates.parquet"
    url_path = output / f"{source}_candidate_urls.txt"
    frame = pl.DataFrame([asdict(item) for item in candidates])
    if parquet_path.is_file():
        existing = pl.read_parquet(parquet_path)
        if existing.height and set(existing.get_column("source").unique()) != {source.upper()}:
            raise ValueError(f"existing candidate file has a different source: {parquet_path}")
        frame = pl.concat([existing, frame], how="vertical_relaxed")
    frame = frame.unique(subset=["url"], keep="last").sort(
        ["period", "url"], descending=[True, True], nulls_last=True
    )
    frame.write_parquet(parquet_path)
    url_path.write_text(
        "# Generated from archived official index raw; review before network use.\n"
        + "\n".join(frame.get_column("url").to_list())
        + "\n",
        encoding="utf-8",
    )
    return parquet_path, url_path


def fetch_and_discover_indexes(
    conn: duckdb.DuckDBPyConnection,
    *,
    source: str,
    urls: list[str],
    allow_network: bool,
    refresh: bool = False,
) -> tuple[list[CandidateUrl], list[str]]:
    """Archive a bounded list of index pages, then discover links offline."""
    source_key = source.upper()
    if source_key not in SOURCE_RULES or source_key not in SOURCE_CLASSES:
        raise ValueError(f"unsupported index source: {source}")
    adapter = SOURCE_CLASSES[source_key](allow_network=allow_network)
    raw_files: list[str] = []
    try:
        _validate_manifest(urls, adapter.policy)
        for url in urls:
            result = adapter.fetch(url, refresh=refresh)
            raw_files.append(result.artifact.path)
    finally:
        record_crawl_events(conn, adapter.client.events, parser_version="index_discovery_v1")
        adapter.close()
    return discover_candidates(source_key, [Path(path) for path in raw_files]), raw_files


def _title_period(title: str) -> str | None:
    match = re.search(r"(20\d{2})年\s*1\s*[-—–至]\s*(1[0-2]|0?[1-9])月", title)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    match = re.search(r"(20\d{2})年\s*(1[0-2]|0?[1-9])月", title)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    match = re.search(r"(20\d{2})年(?:上半年|一季度)", title)
    if match:
        month = 6 if "上半年" in title else 3
        return f"{int(match.group(1)):04d}-{month:02d}"
    match = re.search(r"(20\d{2})年\s*(?:前\s*)?([一二三四1-4])\s*季(?:度)?", title)
    if match:
        quarter_map = {"一": 1, "二": 2, "三": 3, "四": 4}
        quarter = quarter_map.get(match.group(2), int(match.group(2)) if match.group(2).isdigit() else 0)
        return f"{int(match.group(1)):04d}-{quarter * 3:02d}"
    match = re.search(r"(20\d{2})年", title)
    if match:
        return f"{int(match.group(1)):04d}-12"
    return None
