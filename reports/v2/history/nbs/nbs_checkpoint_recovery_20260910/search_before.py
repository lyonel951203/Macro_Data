from __future__ import annotations

import json
import hashlib
import math
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .config import source_policy
from .db import get_connection, record_crawl_events
from .errors import CrawlSafetyError, DataContractError
from .http import PoliteHttpClient
from .index_discovery import CandidateUrl, _title_period, write_candidates
from .sources.base import decode_content
from .timeutils import SHANGHAI


SEARCH_ENDPOINT = "https://api.so-gov.cn/query/s"
SITE_CODE = "bm36000002"
PAGE_SIZE = 20  # The official API caps responses at 20 even when asked for more.
MAX_EMPTY_QUERY_RETRIES = 3
OFFICIAL_HOSTS = {"www.stats.gov.cn", "stats.gov.cn"}
LEGACY_RELEASE_PATH = re.compile(r"^/sj/zxfb/20\d{4}/t20\d{6}_\d+\.html?$")


def load_search_terms(path: str | Path) -> list[str]:
    terms = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            terms.append(value)
    if not terms:
        raise ValueError("NBS legacy search term manifest is empty")
    return list(dict.fromkeys(terms))


def discover_nbs_legacy(
    db_path: str | Path,
    *,
    terms: list[str],
    start_date: str,
    end_date: str,
    state_path: str | Path,
    output_dir: str | Path,
    allow_network: bool,
    max_network_pages: int,
    client: PoliteHttpClient | None = None,
) -> dict:
    """Discover migrated pre-2020 NBS releases through its official search API.

    Search responses are immutable raw evidence. Only canonical NBS release
    article URLs are admitted to the downstream parser queue. State advances
    after candidate output is durably merged, so interruption is safe.
    """
    _validate_date_range(start_date, end_date)
    if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
        raise ValueError("at least one nonempty NBS legacy search term is required")
    if max_network_pages < 1:
        raise ValueError("max_network_pages must be positive")

    state_file = Path(state_path)
    state = _load_state(state_file, terms, start_date, end_date)
    policy = source_policy("NBS")
    if urlparse(SEARCH_ENDPOINT).hostname not in set(policy.get("allowed_hosts", [])):
        raise ValueError("official search API host is not allowlisted for NBS")

    owns_client = client is None
    if client is not None and client.source != "NBS":
        raise ValueError("shared official-search client must use source NBS")
    client = client or PoliteHttpClient(source="NBS", policy=policy, allow_network=allow_network)
    network_pages = 0
    event_offset = len(client.events)
    state["status"] = "RUNNING"
    _save_state(state_file, state)
    try:
        for term in terms:
            item = state["items"][term]
            if item.get("needs_narrowing", False):
                continue
            while not item.get("complete", False):
                if network_pages >= max_network_pages:
                    state["status"] = "PAUSED"
                    _save_state(state_file, state)
                    return state

                page = int(item.get("next_page", 1))
                retry = item.get("empty_query_retry", {})
                if retry.get("page") == page and retry.get("network_failures", 0) >= MAX_EMPTY_QUERY_RETRIES:
                    raise DataContractError("NBS empty-query retries exhausted; inspect evidence before resuming")
                params = {
                    "siteCode": SITE_CODE,
                    "tab": "",
                    "qt": term,
                    "page": page,
                    "pageSize": PAGE_SIZE,
                    "timeOption": 2,
                    "startDateStr": start_date,
                    "endDateStr": end_date,
                    "sort": "dateDesc",
                    "keyPlace": 1,
                }
                requests_before = getattr(client, "_request_count", None)
                result = client.fetch_form(
                    SEARCH_ENDPOINT, params, refresh=retry.get("page") == page,
                )
                # An HTTP 200 with identical bytes can be labeled from_cache by
                # the HTTP client. It still consumed a request and retry budget.
                requests_used = (client._request_count - requests_before
                                 if requests_before is not None else int(not result.from_cache))
                network_pages += requests_used
                state["network_pages"] = int(state.get("network_pages", 0)) + requests_used
                state["cached_pages"] = int(state.get("cached_pages", 0)) + int(requests_used == 0)
                payload = _decode_payload(result.content)
                if payload.get("ok") is False and payload.get("code") == 201 and payload.get("msg") == "无搜索词":
                    failures = (retry.get("network_failures", 0) if retry.get("page") == page else 0) + requests_used
                    item["empty_query_retry"] = dict(page=page, network_failures=failures)
                    item.setdefault("search_errors", []).append(dict(
                        page=page, raw_file=result.artifact.path, message=payload["msg"],
                        network_requests=requests_used, at=_now_iso(),
                    ))
                    state["status"] = "PAUSED"
                    state["last_error"] = f"NBS returned 无搜索词 for nonempty query; page {page}, failed requests {failures}/{MAX_EMPTY_QUERY_RETRIES}"
                    _save_state(state_file, state)
                    event_offset = _record_events(Path(db_path), client, event_offset)
                    if failures >= MAX_EMPTY_QUERY_RETRIES:
                        raise DataContractError(state["last_error"] + "; retries exhausted")
                    # Do not advance the page, merge candidates, or mark complete.
                    # The next request uses the same form and normal client pacing.
                    continue
                candidates = candidates_from_search(
                    payload,
                    raw_file=result.artifact.path,
                    term=term,
                )
                item.pop("empty_query_retry", None)
                state.pop("last_error", None)
                fingerprint = _page_fingerprint(payload)
                fingerprints = item.setdefault("page_fingerprints", {})
                repeated_page = next((int(p) for p, digest in fingerprints.items()
                                      if digest == fingerprint and int(p) != page), None)
                if fingerprint and repeated_page is not None:
                    # Some broad searches loop to page 1 at the result-window limit.
                    # A processed queue does not prove exhaustive search coverage.
                    item.update({"complete": False, "needs_narrowing": True,
                                 "pagination_repeat": {"page": page, "matches_page": repeated_page,
                                                       "raw_file": result.artifact.path},
                                 "updated_at": _now_iso()})
                    _save_state(state_file, state)
                    event_offset = _record_events(Path(db_path), client, event_offset)
                    break
                if fingerprint:
                    fingerprints[str(page)] = fingerprint
                if candidates:
                    write_candidates(candidates, output_dir=output_dir)

                total_hits = int(payload.get("totalHits") or 0)
                total_pages = math.ceil(total_hits / PAGE_SIZE) if total_hits else 1
                docs = payload.get("resultDocs") or []
                item.update(
                    {
                        "last_page": page,
                        "next_page": page + 1,
                        "total_hits": total_hits,
                        "total_pages": total_pages,
                        "last_current_hits": int(payload.get("currentHits") or len(docs)),
                        "candidates": int(item.get("candidates", 0)) + len(candidates),
                        "complete": page >= total_pages or not docs,
                        "updated_at": _now_iso(),
                    }
                )
                state["candidate_rows"] = int(state.get("candidate_rows", 0)) + len(candidates)
                _save_state(state_file, state)
                event_offset = _record_events(Path(db_path), client, event_offset)
    except DataContractError as exc:
        state.update(status="ERROR", last_error=str(exc), last_error_at=_now_iso())
        _save_state(state_file, state)
        raise
    except CrawlSafetyError as exc:
        state["status"] = "PAUSED" if "budget exhausted" in str(exc) else "BLOCKED"
        state["last_error"] = str(exc)
        state["last_error_at"] = _now_iso()
        _save_state(state_file, state)
        return state
    finally:
        _record_events(Path(db_path), client, event_offset)
        if owns_client:
            client.close()

    state["status"] = "PARTIAL" if any(item.get("needs_narrowing") for item in state["items"].values()) else "COMPLETE"
    if state["status"] == "COMPLETE":
        state["completed_at"] = _now_iso()
    _save_state(state_file, state)
    return state


def _page_fingerprint(payload: dict) -> str | None:
    """Identify repeated result documents despite changing API response metadata."""
    documents = []
    for doc in payload.get("resultDocs", []):
        data = doc.get("data", {}) if isinstance(doc, dict) else {}
        if isinstance(data, dict) and data.get("url"):
            documents.append((str(data["url"]), str(data.get("docDate") or "")))
    if not documents:
        return None
    return hashlib.sha256(json.dumps(sorted(documents), ensure_ascii=False).encode("utf-8")).hexdigest()


def candidates_from_search(payload: dict, *, raw_file: str, term: str) -> list[CandidateUrl]:
    if payload.get("ok") is not True:
        raise DataContractError(f"NBS official search returned an error: {payload.get('msg')}")
    docs = payload.get("resultDocs")
    if not isinstance(docs, list):
        raise DataContractError("NBS official search response has no resultDocs list")

    candidates: dict[str, CandidateUrl] = {}
    for doc in docs:
        data = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data, dict):
            continue
        url = _canonical_release_url(str(data.get("url") or ""))
        if url is None:
            continue
        title = re.sub(r"<[^>]+>", "", str(data.get("titleO") or data.get("title") or ""))
        title = " ".join(title.split())
        if not title:
            continue
        period = _title_period(title) or _infer_month_period(title, str(data.get("docDate") or ""))
        candidates[url] = CandidateUrl(
            source="NBS",
            title=title,
            url=url,
            period=period,
            kind=f"statistics_release_search:{term}",
            index_raw_file=Path(raw_file).as_posix(),
        )
    return sorted(candidates.values(), key=lambda item: (item.period or "", item.url), reverse=True)


def _canonical_release_url(value: str) -> str | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in OFFICIAL_HOSTS:
        return None
    if not LEGACY_RELEASE_PATH.match(parsed.path):
        return None
    return urlunparse(("https", "www.stats.gov.cn", parsed.path, "", "", ""))


def _infer_month_period(title: str, doc_date: str) -> str | None:
    match = re.search(r"(?<!\d)(1[0-2]|0?[1-9])\s*月份?", title)
    if not match:
        return None
    try:
        published = date.fromisoformat(doc_date[:10])
    except ValueError:
        return None
    month = int(match.group(1))
    year = published.year - 1 if month > published.month else published.year
    return f"{year:04d}-{month:02d}"


def _decode_payload(content: bytes) -> dict:
    try:
        payload = json.loads(decode_content(content))
    except json.JSONDecodeError as exc:
        raise DataContractError("NBS official search response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise DataContractError("NBS official search response is not an object")
    return payload


def _load_state(path: Path, terms: list[str], start_date: str, end_date: str) -> dict:
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        if (
            state.get("terms") != terms
            or state.get("start_date") != start_date
            or state.get("end_date") != end_date
        ):
            raise ValueError("NBS legacy search state does not match terms/date range")
        return state
    return {
        "version": 1,
        "source": "NBS",
        "status": "NEW",
        "created_at": _now_iso(),
        "terms": terms,
        "start_date": start_date,
        "end_date": end_date,
        "items": {term: {"next_page": 1, "complete": False, "candidates": 0} for term in terms},
        "network_pages": 0,
        "cached_pages": 0,
        "candidate_rows": 0,
    }


def _save_state(path: Path, state: dict) -> None:
    state["updated_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _record_events(db_path: Path, client: PoliteHttpClient, offset: int) -> int:
    events = client.events[offset:]
    if not events:
        return offset
    conn = get_connection(db_path)
    try:
        record_crawl_events(conn, events, parser_version="nbs_legacy_search_v1")
    finally:
        conn.close()
    return len(client.events)


def _validate_date_range(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("NBS legacy search dates must use YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("NBS legacy search start date is after end date")


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat()
