"""Independent cross-checks for modern NBS monthly CPI/PPI release articles."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .archive import RawArtifact
from .sources.cn_common import html_text
from .timeutils import SHANGHAI


PRICE_TITLE = re.compile(
    r"^(?P<year>20\d{2})年(?P<month>\d{1,2})月份"
    r"(?P<subject>居民消费价格|工业生产者出厂价格)同比"
    r"(?P<direction>上涨|下降)(?P<value>\d+(?:\.\d+)?)[%％]"
)


def search_expectation(item: dict) -> dict:
    raw = Path(item["index_raw_file"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["index_sha256"]:
        raise ValueError("Search evidence hash changed")
    docs = [x["data"] for x in json.loads(raw)["resultDocs"]
            if x.get("data", {}).get("url") == item["url"]]
    if len(docs) != 1:
        raise ValueError("Expected exactly one matching official search record")
    doc = docs[0]
    title = re.sub(r"\s+", "", doc["titleO"])
    if title != re.sub(r"\s+", "", item["title"]):
        raise ValueError("Candidate and archived search titles disagree")
    match = PRICE_TITLE.match(title)
    if not match:
        raise ValueError("Unsupported price title; manual review required")
    period = f"{int(match['year']):04d}-{int(match['month']):02d}"
    indicator = "CN_CPI_YOY" if match["subject"] == "居民消费价格" else "CN_PPI_YOY"
    if period != item["period"] or indicator != item["indicator"]:
        raise ValueError("Candidate period or indicator disagrees with search title")
    release = datetime.fromtimestamp(int(doc["dreDate"]) / 1000, SHANGHAI)
    if release.date().isoformat() != doc["docDate"]:
        raise ValueError("Search date and timestamp disagree")
    return {"canonical_series_id": indicator, "period": period,
            "value": float(match["value"]) * (-1 if match["direction"] == "下降" else 1),
            "release_at": release.isoformat(), "subject": match["subject"],
            "search_title": doc["titleO"], "index_raw_file": item["index_raw_file"],
            "index_sha256": item["index_sha256"]}


def review_price_article(item: dict, content: bytes, artifact: RawArtifact) -> dict:
    """Require independent search, visible article header and body agreement.

    This intentionally supports only the literal modern monthly price wording.
    An unexpected structure stops the batch instead of weakening PIT evidence.
    """
    if artifact.url != item["url"] or hashlib.sha256(content).hexdigest() != artifact.sha256:
        raise ValueError("Article URL or raw hash mismatch")
    expected = search_expectation(item)
    soup, _ = html_text(content)
    title = re.sub(r"\s+", "", soup.title.get_text() if soup.title else "")
    title = title.removesuffix("-国家统计局")
    if title != re.sub(r"\s+", "", expected["search_title"]):
        raise ValueError("Article title disagrees with archived search title")
    header = soup.select_one(".detail-title-des")
    matches = [] if header is None else re.findall(
        r"20\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}(?::\d{2})?", header.get_text(" ", strip=True)
    )
    if len(matches) != 1:
        raise ValueError("No unique visible publication timestamp")
    stamp = " ".join(matches[0].split())
    fmt = "%Y/%m/%d %H:%M:%S" if stamp.count(":") == 2 else "%Y/%m/%d %H:%M"
    release = datetime.strptime(stamp, fmt).replace(tzinfo=SHANGHAI)
    if release != datetime.fromisoformat(expected["release_at"]):
        raise ValueError("Article and search publication timestamps disagree")
    body = soup.select_one(".txt-content") or soup.select_one(".TRS_Editor") or soup.select_one(".trs_editor")
    body_text = re.sub(r"\s+", "", body.get_text(" ", strip=True)) if body else ""
    year, month = map(int, expected["period"].split("-"))
    match = re.match(
        rf"{year}年{month}月份，(?:全国)?{expected['subject']}同比"
        r"(?P<direction>上涨|下降)(?P<value>\d+(?:\.\d+)?)[%％]", body_text
    )
    if not match:
        raise ValueError("No unambiguous monthly YoY statement at start of article body")
    value = float(match["value"]) * (-1 if match["direction"] == "下降" else 1)
    if value != expected["value"]:
        raise ValueError("Article body and search-title values disagree")
    return {**{k: v for k, v in expected.items() if k != "subject"},
            "pit_grade": "A", "available_at": release.isoformat(),
            "body_evidence": match[0], "timestamp_evidence": stamp,
            "review_method": "independent_search_title_article_body_visible_timestamp"}
