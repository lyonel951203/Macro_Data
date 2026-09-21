from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..archive import RawArtifact
from ..timeutils import SHANGHAI, conservative_date_only_available, ensure_aware
from .base import decode_content


def html_text(content: bytes) -> tuple[BeautifulSoup, str]:
    soup = BeautifulSoup(decode_content(content), "lxml")
    text = " ".join(soup.get_text(" ", strip=True).split())
    return soup, text


def extract_period(text: str) -> tuple[int, int]:
    quarter_match = re.search(r"(20\d{2})\s*年\s*(?:前\s*)?([一二三四1-4])\s*季(?:度)?", text)
    if quarter_match:
        quarter_map = {"一": 1, "二": 2, "三": 3, "四": 4}
        quarter = quarter_map.get(quarter_match.group(2), int(quarter_match.group(2)) if quarter_match.group(2).isdigit() else 0)
        return int(quarter_match.group(1)), quarter * 3
    half_match = re.search(r"(20\d{2})\s*年\s*上半年", text)
    if half_match:
        return int(half_match.group(1)), 6
    patterns = [
        r"(20\d{2})\s*年\s*1\s*[-—–至]\s*(1[0-2]|0?[1-9])\s*月",
        r"(20\d{2})\s*年\s*前\s*(1[0-2]|0?[1-9])\s*个?月",
        r"(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1)), int(match.group(2))
    raise ValueError("monthly period not found in official publication")


def extract_period_from_title(soup: BeautifulSoup, text: str) -> tuple[int, int]:
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        try:
            return extract_period(title)
        except ValueError:
            annual = re.search(r"(20\d{2})\s*年", title)
            if annual:
                return int(annual.group(1)), 12
    return extract_period(text)


def extract_release_evidence(soup: BeautifulSoup, text: str, first_seen: datetime) -> dict[str, Any]:
    metadata_date: date | None = None
    for selector in (
        {"property": "article:published_time"},
        {"name": "publishdate"},
        {"name": "PubDate"},
        {"name": "publish-time"},
    ):
        node = soup.find("meta", attrs=selector)
        if node and node.get("content"):
            raw_value = str(node["content"]).strip()
            parsed = _parse_datetime(raw_value)
            if parsed and re.search(r"\d{1,2}:\d{2}", raw_value):
                return _grade_a(parsed, "official_page_metadata")
            if parsed:
                metadata_date = parsed.astimezone(SHANGHAI).date()

    timestamp_patterns = [
        r"文章来源\s*[：:]?\s*(20\d{2}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)",
        r"发布时间\s*[：:]?\s*(20\d{2}[-年]\d{1,2}[-月]\d{1,2}日?\s+\d{1,2}:\d{2}(?::\d{2})?)",
        r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)",
    ]
    for pattern in timestamp_patterns:
        match = re.search(pattern, text)
        if match:
            parsed = _parse_datetime(match.group(1))
            if parsed:
                return _grade_a(parsed, "official_page_timestamp")

    if metadata_date is not None:
        release_at = datetime.combine(metadata_date, datetime.min.time(), tzinfo=SHANGHAI)
        return {
            "release_at": ensure_aware(release_at),
            "available_at": conservative_date_only_available(metadata_date),
            "release_date_source": "official_page_metadata_date",
            "pit_grade": "B",
        }

    date_patterns = [
        r"(?:文章来源|发布时间|发布日期)\s*[：:]?\s*(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?",
        r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            release_date = date(*(int(part) for part in match.groups()))
            release_at = datetime.combine(release_date, datetime.min.time(), tzinfo=SHANGHAI)
            return {
                "release_at": ensure_aware(release_at),
                "available_at": conservative_date_only_available(release_date),
                "release_date_source": "official_page_date",
                "pit_grade": "B",
            }

    first_seen_utc = ensure_aware(first_seen)
    return {
        "release_at": None,
        "available_at": first_seen_utc,
        "release_date_source": "first_seen_only",
        "pit_grade": "D",
    }


def make_observation(
    *,
    source: str,
    canonical_series_id: str,
    source_series_id: str,
    series_name: str,
    unit: str,
    year: int,
    month: int,
    value: float,
    artifact: RawArtifact,
    release: dict[str, Any],
    parser_version: str,
    frequency: str = "M",
    seasonal_adjustment: str = "NSA",
) -> dict[str, Any]:
    last_day = calendar.monthrange(year, month)[1]
    return {
        "country": "CN",
        "source": source.upper(),
        "canonical_series_id": canonical_series_id,
        "source_series_id": source_series_id,
        "series_name": series_name,
        "frequency": frequency,
        "unit": unit,
        "seasonal_adjustment": seasonal_adjustment,
        "period": f"{year:04d}-{month:02d}",
        "period_start": date(year, month, 1),
        "period_end": date(year, month, last_day),
        "value": float(value),
        "release_at": release["release_at"],
        "release_date_source": release["release_date_source"],
        "first_seen_at": artifact.retrieved_at,
        "available_at": release["available_at"],
        "pit_grade": release["pit_grade"],
        "source_url": artifact.url,
        "raw_file": artifact.path,
        "raw_sha256": artifact.sha256,
        "retrieved_at": artifact.retrieved_at,
        "parser_version": parser_version,
    }


def make_quarterly_observation(
    *,
    source: str,
    canonical_series_id: str,
    source_series_id: str,
    series_name: str,
    unit: str,
    year: int,
    quarter: int,
    value: float,
    artifact: RawArtifact,
    release: dict[str, Any],
    parser_version: str,
    seasonal_adjustment: str = "NSA",
) -> dict[str, Any]:
    start_month = (quarter - 1) * 3 + 1
    end_month = quarter * 3
    return {
        "country": "CN",
        "source": source.upper(),
        "canonical_series_id": canonical_series_id,
        "source_series_id": source_series_id,
        "series_name": series_name,
        "frequency": "Q",
        "unit": unit,
        "seasonal_adjustment": seasonal_adjustment,
        "period": f"{year:04d}-Q{quarter}",
        "period_start": date(year, start_month, 1),
        "period_end": date(year, end_month, calendar.monthrange(year, end_month)[1]),
        "value": float(value),
        "release_at": release["release_at"],
        "release_date_source": release["release_date_source"],
        "first_seen_at": artifact.retrieved_at,
        "available_at": release["available_at"],
        "pit_grade": release["pit_grade"],
        "source_url": artifact.url,
        "raw_file": artifact.path,
        "raw_sha256": artifact.sha256,
        "retrieved_at": artifact.retrieved_at,
        "parser_version": parser_version,
    }


def signed_percent(text_value: str, direction: str | None = None) -> float:
    value = float(text_value.replace(",", ""))
    return -abs(value) if direction and "下降" in direction else value


def _grade_a(value: datetime, source: str) -> dict[str, Any]:
    timestamp = ensure_aware(value)
    return {
        "release_at": timestamp,
        "available_at": timestamp,
        "release_date_source": source,
        "pit_grade": "A",
    }


def _parse_datetime(value: str) -> datetime | None:
    normalized = (
        value.strip()
        .replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
    )
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed
