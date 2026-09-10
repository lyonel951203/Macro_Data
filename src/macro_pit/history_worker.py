from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import duckdb
import polars as pl

from .db import get_connection, insert_observations, record_crawl_events
from .errors import CrawlSafetyError
from .pipeline import SOURCE_CLASSES, _parse, _validate_manifest
from .timeutils import SHANGHAI


TERMINAL_STATUSES = {"success", "parse_error"}


def load_history_urls(path: str | Path, *, start_period: str) -> list[str]:
    source = Path(path)
    if source.suffix.lower() == ".parquet":
        frame = pl.read_parquet(source)
        if "url" not in frame.columns:
            raise ValueError("history candidate parquet requires a url column")
        if "period" in frame.columns:
            frame = frame.filter(
                pl.col("period").is_null() | (pl.col("period").cast(pl.Utf8) >= start_period)
            )
        return list(dict.fromkeys(str(value) for value in frame.get_column("url").to_list()))
    urls = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    if not urls:
        raise ValueError("history URL queue is empty")
    return list(dict.fromkeys(urls))


def run_history_queue(
    *,
    db_path: str | Path,
    source_name: str,
    candidate_path: str | Path,
    start_period: str,
    state_path: str | Path,
    log_path: str | Path,
    allow_network: bool,
    max_network_urls_per_session: int = 20,
    wait_across_days: bool = False,
    resume_hour: int = 10,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    source_key = source_name.upper()
    if source_key not in {"NBS", "PBOC", "CUSTOMS", "MOF", "SAFE"}:
        raise ValueError(f"unsupported China history source: {source_name}")
    state_file = Path(state_path)
    log_file = Path(log_path)
    state = _load_state(state_file, source_key, start_period)

    while True:
        urls = load_history_urls(candidate_path, start_period=start_period)
        pending = [url for url in urls if state["items"].get(url, {}).get("status") not in TERMINAL_STATUSES]
        state["queue_size"] = len(urls)
        state["pending"] = len(pending)
        _save_state(state_file, state)
        if not pending:
            state["status"] = "COMPLETE"
            state["completed_at"] = _now_iso()
            _save_state(state_file, state)
            _log(log_file, {"event": "complete", "source": source_key, "queue_size": len(urls)})
            return state

        outcome = _run_session(
            db_path=Path(db_path),
            source_key=source_key,
            urls=pending,
            state=state,
            state_file=state_file,
            log_file=log_file,
            allow_network=allow_network,
            max_network_urls=max_network_urls_per_session,
        )
        if outcome == "blocked":
            state["status"] = "BLOCKED"
            _save_state(state_file, state)
            return state
        if outcome == "complete":
            continue
        if not wait_across_days:
            state["status"] = "PAUSED"
            _save_state(state_file, state)
            return state
        state["status"] = "WAITING_NEXT_DAY"
        _save_state(state_file, state)
        wait_seconds = _seconds_until_resume(resume_hour)
        _log(log_file, {"event": "wait", "seconds": int(wait_seconds), "resume_hour": resume_hour})
        sleep(wait_seconds)


def _run_session(
    *,
    db_path: Path,
    source_key: str,
    urls: list[str],
    state: dict,
    state_file: Path,
    log_file: Path,
    allow_network: bool,
    max_network_urls: int,
) -> str:
    source = SOURCE_CLASSES[source_key](allow_network=allow_network)
    _validate_manifest(urls[: max(1, max_network_urls)], source.policy)
    network_urls = 0
    state["status"] = "RUNNING"
    state["session_started_at"] = _now_iso()
    _save_state(state_file, state)
    try:
        for url in urls:
            if network_urls >= max_network_urls:
                return "session_limit"
            event_offset = len(source.client.events)
            try:
                fetched = source.fetch(url, refresh=False)
                network_urls += int(not fetched.from_cache)
                rows = _parse(source, fetched.content, fetched.artifact)
                conn = get_connection(db_path)
                try:
                    stats = insert_observations(conn, rows)
                    record_crawl_events(
                        conn,
                        source.client.events[event_offset:],
                        parser_version=source.parser_version,
                    )
                finally:
                    conn.close()
                state["items"][url] = {
                    "status": "success",
                    "updated_at": _now_iso(),
                    "from_cache": fetched.from_cache,
                    "rows": len(rows),
                    "inserted": stats.inserted,
                    "revisions": stats.revisions,
                    "unchanged": stats.unchanged,
                }
                _log(log_file, {"event": "success", "source": source_key, "url": url, **state["items"][url]})
            except CrawlSafetyError as exc:
                _record_new_events(db_path, source, event_offset)
                message = str(exc)
                state["last_error"] = message
                state["last_error_at"] = _now_iso()
                _save_state(state_file, state)
                _log(log_file, {"event": "safety_stop", "source": source_key, "url": url, "error": message})
                if "budget exhausted" in message:
                    return "budget"
                return "blocked"
            except Exception as exc:
                _record_new_events(db_path, source, event_offset, parser_error=exc)
                state["items"][url] = {
                    "status": "parse_error",
                    "updated_at": _now_iso(),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
                _log(log_file, {"event": "parse_error", "source": source_key, "url": url, **state["items"][url]})
            state["pending"] = max(0, int(state.get("pending", 0)) - 1)
            _save_state(state_file, state)
        return "complete"
    finally:
        source.close()


def _record_new_events(db_path: Path, source, offset: int, parser_error: Exception | None = None) -> None:
    events = source.client.events[offset:]
    if parser_error and events:
        events[-1].error_type = type(parser_error).__name__
        events[-1].error_message = str(parser_error)[:1000]
    if not events:
        return
    conn = get_connection(db_path)
    try:
        record_crawl_events(conn, events, parser_version=source.parser_version)
    finally:
        conn.close()


def _load_state(path: Path, source: str, start_period: str) -> dict:
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("source") != source or state.get("start_period") != start_period:
            raise ValueError("history state does not match source/start_period")
        return state
    return {
        "version": 1,
        "source": source,
        "start_period": start_period,
        "status": "NEW",
        "created_at": _now_iso(),
        "items": {},
    }


def _save_state(path: Path, state: dict) -> None:
    state["updated_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _log(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": _now_iso(), **payload}, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _seconds_until_resume(hour: int) -> float:
    now = datetime.now(SHANGHAI)
    target = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=SHANGHAI)
    target += timedelta(hours=hour)
    return max(60.0, (target - now).total_seconds())


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat()
