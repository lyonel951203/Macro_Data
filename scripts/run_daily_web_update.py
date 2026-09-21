"""Unattended incremental update from official and reviewed fallback sources.

The runner discovers current release links from reviewed official index pages,
refreshes versioned datasets, and observes a bounded set of third-party current-
history fields as low-priority PIT_D fallbacks. It sends every accepted value
through the append-only/idempotent database writer. A failure in one source is
logged and does not prevent the remaining sources from running.

Wind is deliberately outside this workflow.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta
import ctypes
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import yaml

from macro_pit.db import get_connection
from macro_pit.email_delivery import send_audit_email
from macro_pit.errors import CrawlSafetyError
from macro_pit.index_discovery import CandidateUrl, fetch_and_discover_indexes
from macro_pit.pipeline import (
    ingest_chinabond_history, ingest_cn_fallback, ingest_imf_commodity,
    ingest_us_treasury_history,
    ingest_oecd_manifest, ingest_rtdsm_manifest, ingest_url_manifest,
    load_url_manifest,
)
from macro_pit.semantic_audit import run_semantic_audit
from macro_pit.timeutils import SHANGHAI


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "daily_web_update.yml"
ALLOWED_SOURCES = (
    "NBS", "PBOC", "PBOC_MIRROR", "CUSTOMS", "MOF", "SAFE",
    "EASTMONEY_MACRO", "SINA_MACRO", "OECD", "RTDSM",
    "CHINABOND", "USTREASURY", "IMF",
)


def _progress(message: str) -> None:
    timestamp = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def _workspace_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"daily update path must stay inside workspace: {path}")
    return path


def _job_manifest_paths(settings: dict[str, Any]) -> list[Path]:
    values = settings.get("job_manifests")
    if values is None:
        single = settings.get("job_manifest")
        values = [single] if single else []
    if not isinstance(values, list) or not values:
        return []
    return [_workspace_path(value) for value in values]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return payload if isinstance(payload, dict) else default


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = _workspace_path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if payload.get("version") != 1:
        raise ValueError("daily web update config requires version: 1")
    sources = payload.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("daily web update config requires sources")
    unknown = sorted(set(sources) - set(ALLOWED_SOURCES))
    if unknown:
        raise ValueError(f"daily web update has unsupported sources: {unknown}")
    for source, settings in sources.items():
        if not isinstance(settings, dict):
            raise ValueError(f"{source} settings must be a mapping")
        if source in {"OECD", "RTDSM"}:
            manifest_paths = _job_manifest_paths(settings)
            if settings.get("enabled", True) and not manifest_paths:
                raise ValueError(f"{source} requires at least one job manifest")
            for manifest_path in manifest_paths:
                if not manifest_path.is_file():
                    raise ValueError(f"missing {source} job manifest: {manifest_path}")
        elif source in {"CHINABOND", "USTREASURY"}:
            try:
                date.fromisoformat(str(settings["history_start"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"{source} requires ISO history_start"
                ) from exc
            if int(settings.get("daily_lookback_days", 75)) < 31:
                raise ValueError(
                    f"{source}.daily_lookback_days must be at least 31"
                )
        elif source == "IMF":
            url = str(settings.get("url") or "")
            if not url.startswith("https://"):
                raise ValueError("IMF requires an https url")
        elif source in {"EASTMONEY_MACRO", "SINA_MACRO"}:
            latest_periods = int(settings.get("latest_periods", 3))
            if latest_periods < 1 or latest_periods > 6:
                raise ValueError(f"{source}.latest_periods must be between 1 and 6")
        else:
            manifests = settings.get("index_manifests", [])
            if settings.get("enabled", True) and not manifests:
                raise ValueError(f"{source} requires at least one index manifest")
            for manifest in manifests:
                manifest_path = _workspace_path(manifest)
                if not manifest_path.is_file():
                    raise ValueError(f"missing {source} index manifest: {manifest_path}")
            for name in ("recheck_latest", "max_candidates_per_run"):
                if int(settings.get(name, 0)) < 0:
                    raise ValueError(f"{source}.{name} must be non-negative")
            retry_days = settings.get("retry_backoff_days", [1, 3, 7])
            if not isinstance(retry_days, list) or not retry_days or any(int(day) <= 0 for day in retry_days):
                raise ValueError(f"{source}.retry_backoff_days must contain positive days")
            if int(settings.get("not_found_cooldown_days", 30)) <= 0:
                raise ValueError(f"{source}.not_found_cooldown_days must be positive")
    for key in ("state_path", "lock_path", "report_dir", "logs_dir"):
        if key not in payload:
            raise ValueError(f"daily web update config requires {key}")
        payload[key] = str(_workspace_path(payload[key]))
    audit = payload.get("semantic_audit")
    if audit is not None:
        if not isinstance(audit, dict):
            raise ValueError("semantic_audit settings must be a mapping")
        if "api_key" in audit:
            raise ValueError(
                "semantic_audit.api_key is forbidden; use DEEPSEEK_API_KEY "
                "or the private key file"
            )
        if str(audit.get("provider", "deepseek")).lower() != "deepseek":
            raise ValueError("semantic_audit currently supports provider: deepseek")
        base_url = str(
            audit.get("base_url", "https://api.deepseek.com")
        ).rstrip("/")
        if base_url != "https://api.deepseek.com":
            raise ValueError(
                "semantic_audit.base_url must be https://api.deepseek.com"
            )
        env_name = str(audit.get("api_key_env", "DEEPSEEK_API_KEY"))
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name):
            raise ValueError(
                "semantic_audit.api_key_env must be an uppercase "
                "environment variable name"
            )
        defaults = {
            "max_candidates": 24,
            "max_excerpt_chars": 1400,
            "max_output_tokens": 3000,
            "timeout_seconds": 120,
            "api_attempts": 2,
        }
        bounds = {
            "max_candidates": (1, 100),
            "max_excerpt_chars": (200, 5000),
            "max_output_tokens": (500, 8000),
            "timeout_seconds": (5, 300),
            "api_attempts": (1, 3),
        }
        for name, (lower, upper) in bounds.items():
            value = int(audit.get(name, defaults[name]))
            if value < lower or value > upper:
                raise ValueError(
                    f"semantic_audit.{name} must be between {lower} and {upper}"
                )
        audit["base_url"] = base_url
        audit["api_key_env"] = env_name
        audit["report_dir"] = str(_workspace_path(
            audit.get(
                "report_dir",
                Path(payload["report_dir"]) / "deepseek_audit",
            )
        ))
    email = payload.get("email_notification")
    if email is not None:
        if not isinstance(email, dict):
            raise ValueError("email_notification settings must be a mapping")
        forbidden = {"password", "authorization_code", "smtp_password"}
        if forbidden.intersection(email):
            raise ValueError(
                "email credentials are forbidden in YAML; use the private "
                "QQ SMTP credential file"
            )
        recipient = str(email.get("recipient") or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient):
            raise ValueError("email_notification.recipient is invalid")
        config_file = email.get("config_file")
        if config_file:
            config_file_path = _workspace_path(config_file)
            if not config_file_path.is_file():
                raise ValueError(
                    f"email_notification.config_file is missing: "
                    f"{config_file_path}"
                )
            email["config_file"] = str(config_file_path)
        else:
            if str(email.get("smtp_host", "smtp.qq.com")) != "smtp.qq.com":
                raise ValueError(
                    "email_notification.smtp_host must be smtp.qq.com "
                    "when config_file is not used"
                )
            if int(email.get("smtp_port", 465)) != 465:
                raise ValueError("email_notification.smtp_port must be 465")
        timeout = int(email.get("timeout_seconds", 60))
        if timeout < 5 or timeout > 300:
            raise ValueError(
                "email_notification.timeout_seconds must be between 5 and 300"
            )
        if email.get("enabled", False) and audit is None:
            raise ValueError(
                "enabled email_notification requires semantic_audit"
            )
        email["recipient"] = recipient
        email["report_dir"] = str(_workspace_path(
            email.get(
                "report_dir",
                Path(payload["report_dir"]) / "email_delivery",
            )
        ))
    payload["config_path"] = str(config_path)
    return payload


def _state_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)


def _retry_due(entry: dict[str, Any], now: datetime) -> bool:
    retry_at = _state_datetime(entry.get("next_retry_at"))
    return retry_at is None or now >= retry_at


def _record_candidate_failure(
    entry: dict[str, Any],
    error: str,
    attempted_at: datetime,
    *,
    retry_backoff_days: list[int],
    not_found_cooldown_days: int,
) -> None:
    failure_count = int(entry.get("failure_count", 0)) + 1
    is_not_found = "404" in error and "not found" in error.lower()
    if is_not_found:
        error_kind = "HTTP_404"
        delay_days = int(not_found_cooldown_days)
    else:
        error_kind = "PARSE_OR_FETCH"
        delay_days = int(retry_backoff_days[min(failure_count - 1, len(retry_backoff_days) - 1)])
    entry.update(
        last_attempt_at=attempted_at.isoformat(),
        last_error=error,
        error_kind=error_kind,
        failure_count=failure_count,
        next_retry_at=(attempted_at + timedelta(days=delay_days)).isoformat(),
    )


def _ensure_retry_schedule(
    entry: dict[str, Any],
    settings: dict[str, Any],
    now: datetime,
) -> None:
    if not entry.get("last_error") or entry.get("last_success_at") or entry.get("next_retry_at"):
        return
    attempted_at = _state_datetime(entry.get("last_attempt_at")) or now
    _record_candidate_failure(
        entry,
        str(entry["last_error"]),
        attempted_at,
        retry_backoff_days=[int(day) for day in settings.get("retry_backoff_days", [1, 3, 7])],
        not_found_cooldown_days=int(settings.get("not_found_cooldown_days", 30)),
    )


def _record_candidate_success(entry: dict[str, Any], attempted_at: datetime) -> None:
    entry.update(
        last_attempt_at=attempted_at.isoformat(),
        last_success_at=attempted_at.isoformat(),
        last_error=None,
        failure_count=0,
    )
    entry.pop("error_kind", None)
    entry.pop("next_retry_at", None)


def _recent_start_period(lookback_months: int, now: datetime | None = None) -> str | None:
    if lookback_months <= 0:
        return None
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    month_index = current.year * 12 + current.month - 1 - lookback_months
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def select_candidates(
    candidates: list[CandidateUrl],
    known_urls: dict[str, dict[str, Any]],
    *,
    recheck_latest: int,
    max_candidates: int,
    now: datetime | None = None,
) -> list[CandidateUrl]:
    """Select due pending URLs and a small newest-page revision sample."""
    current = now or datetime.now(SHANGHAI)
    selected: list[CandidateUrl] = []
    selected_urls: set[str] = set()
    pending = [
        item for item in candidates
        if not known_urls.get(item.url, {}).get("last_success_at")
        and not known_urls.get(item.url, {}).get("baseline_ignored_at")
        and _retry_due(known_urls.get(item.url, {}), current)
    ]
    recent: list[CandidateUrl] = []
    pending_urls = {item.url for item in pending}
    for item in candidates:
        entry = known_urls.get(item.url, {})
        if entry.get("last_error") and not _retry_due(entry, current):
            continue
        if item.url not in pending_urls:
            recent.append(item)
        if len(recent) >= recheck_latest:
            break
    for item in [*pending, *recent]:
        if item.url in selected_urls:
            continue
        selected.append(item)
        selected_urls.add(item.url)
        if len(selected) >= max_candidates:
            break
    return selected


def _process_alive(pid: Any) -> bool:
    try:
        numeric_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if numeric_pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(numeric_pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, numeric_pid)
    if not handle:
        return False
    code = wintypes.DWORD()
    try:
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


class RunLock:
    def __init__(self, path: Path, *, wait_seconds: int = 0, poll_seconds: int = 30):
        self.path = path
        self.wait_seconds = max(0, int(wait_seconds))
        self.poll_seconds = max(1, int(poll_seconds))
        self.owned = False

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            if self.path.exists():
                existing = _load_json(self.path, {})
                if _process_alive(existing.get("pid")):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError(
                            f"daily update already running with PID {existing.get('pid')}"
                        )
                    sleep_for = min(self.poll_seconds, max(1, int(remaining)))
                    _progress(
                        f"database writer busy with PID {existing.get('pid')}; "
                        f"waiting {sleep_for}s (up to {self.wait_seconds}s total)"
                    )
                    time.sleep(sleep_for)
                    continue
                stale = self.path.with_name(
                    self.path.name + ".stale_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                )
                os.replace(self.path, stale)
            try:
                with self.path.open("x", encoding="utf-8") as stream:
                    json.dump(
                        {"pid": os.getpid(), "started_at": datetime.now(SHANGHAI).isoformat()},
                        stream,
                    )
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("daily update lock was acquired by another process")
                time.sleep(min(self.poll_seconds, 1))
                continue
            self.owned = True
            return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.owned and self.path.exists():
            self.path.unlink()


def _index_urls(settings: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for manifest in settings.get("index_manifests", []):
        for url in load_url_manifest(_workspace_path(manifest)):
            if url not in seen:
                urls.append(url)
                seen.add(url)
    return urls


def _error_for_url(errors: list[str], url: str) -> str | None:
    return next((error for error in errors if error.startswith(url + ":")), None)


def _carry_pending_candidates(
    source: str,
    current: list[CandidateUrl],
    known_urls: dict[str, dict[str, Any]],
) -> list[CandidateUrl]:
    """Keep retrying discovered failures after they leave the current index."""
    combined = list(current)
    present = {item.url for item in current}
    for url, entry in known_urls.items():
        if (
            url in present
            or entry.get("last_success_at")
            or entry.get("baseline_ignored_at")
        ):
            continue
        combined.append(CandidateUrl(
            source=source,
            title=str(entry.get("title") or url),
            url=url,
            period=entry.get("period"),
            kind=str(entry.get("kind") or "pending_release"),
            index_raw_file=str(entry.get("index_raw_file") or "daily_state"),
        ))
    return combined


def run_manifest_source(
    source: str,
    settings: dict[str, Any],
    source_state: dict[str, Any],
    *,
    db_path: Path,
    allow_network: bool,
    logs_dir: Path,
) -> dict[str, Any]:
    """Refresh every configured versioned-data manifest independently."""
    started = datetime.now(SHANGHAI)
    manifests = _job_manifest_paths(settings)
    receipt: dict[str, Any] = {
        "source": source,
        "started_at": started.isoformat(),
        "status": "STARTED",
        "job_manifests": [str(path) for path in manifests],
        "manifest_runs": [],
        "discovered": 0,
        "carried_pending": 0,
        "baseline_skipped": 0,
        "selected": 0,
        "new_observations": 0,
        "revisions": 0,
        "metadata_updates": 0,
        "unchanged": 0,
        "parse_errors": 0,
        "no_recent_records": 0,
        "http_success": 0,
        "raw_downloaded": 0,
        "runtime_seconds": 0.0,
        "errors": [],
    }
    ingest = ingest_oecd_manifest if source == "OECD" else ingest_rtdsm_manifest
    conn = None
    statuses: list[str] = []
    try:
        conn = get_connection(db_path)
        for manifest in manifests:
            manifest_run: dict[str, Any] = {
                "manifest": str(manifest),
                "status": "STARTED",
                "errors": [],
            }
            _progress(f"{source}/{manifest.name}: START")
            try:
                common = {
                    "manifest_path": manifest,
                    "allow_network": allow_network,
                    "refresh": True,
                    "logs_dir": logs_dir,
                    "skip_unchanged_fetch": bool(settings.get("skip_unchanged_fetch", False)),
                }
                if source == "OECD":
                    lookback = int(settings.get("recent_lookback_months", 0))
                    start_period = _recent_start_period(lookback)
                    result = ingest(conn, start_period=start_period, **common)
                    manifest_run["start_period"] = start_period
                    manifest_run["mode"] = "recent_periods" if start_period else "full_history"
                else:
                    result = ingest(conn, **common)
                    manifest_run["mode"] = (
                        "conditional_files"
                        if common["skip_unchanged_fetch"]
                        else "full_workbooks"
                    )
                manifest_run.update({
                    "status": result.status,
                    "urls_requested": result.urls_requested,
                    "new_observations": result.new_observations,
                    "revisions": result.revisions,
                    "metadata_updates": result.metadata_updates,
                    "unchanged": result.unchanged,
                    "parse_errors": result.parse_errors,
                    "no_recent_records": result.no_recent_records,
                    "http_success": result.http_success,
                    "raw_downloaded": result.raw_downloaded,
                    "runtime_seconds": result.runtime_seconds,
                    "errors": list(result.errors),
                })
            except Exception as exc:
                manifest_run["status"] = "FAILED"
                manifest_run["errors"] = [f"{type(exc).__name__}: {exc}"]
            statuses.append(manifest_run["status"])
            receipt["manifest_runs"].append(manifest_run)
            requested = int(manifest_run.get("urls_requested", 0))
            receipt["discovered"] += requested
            receipt["selected"] += requested
            for field in (
                "new_observations", "revisions", "metadata_updates", "unchanged",
                "parse_errors", "no_recent_records", "http_success", "raw_downloaded",
            ):
                receipt[field] += int(manifest_run.get(field, 0))
            receipt["runtime_seconds"] += float(manifest_run.get("runtime_seconds", 0.0))
            receipt["errors"].extend(
                f"{manifest.name}: {error}" for error in manifest_run.get("errors", [])
            )
            _progress(
                f"{source}/{manifest.name}: {manifest_run['status']} "
                f"requested={requested} inserted={manifest_run.get('new_observations', 0)} "
                f"revisions={manifest_run.get('revisions', 0)} "
                f"parse_errors={manifest_run.get('parse_errors', 0)} "
                f"no_recent_records={manifest_run.get('no_recent_records', 0)}"
            )
    except Exception as exc:
        statuses.append("FAILED")
        receipt["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if conn is not None:
            conn.close()
    if statuses and all(status in {"SUCCESS", "SUCCESS_NO_CHANGE"} for status in statuses):
        changed = receipt["new_observations"] + receipt["revisions"] + receipt["metadata_updates"]
        receipt["status"] = "SUCCESS" if changed else "SUCCESS_NO_CHANGE"
    elif statuses and all(status == "FAILED" for status in statuses):
        receipt["status"] = "FAILED"
    else:
        receipt["status"] = "PARTIAL"
    receipt["finished_at"] = datetime.now(SHANGHAI).isoformat()
    receipt["elapsed_seconds"] = round(
        (datetime.now(SHANGHAI) - started).total_seconds(), 3
    )
    receipt["runtime_seconds"] = round(receipt["runtime_seconds"], 3)
    source_state["last_run"] = dict(receipt)
    return receipt



def run_direct_data_source(
    source: str,
    settings: dict[str, Any],
    source_state: dict[str, Any],
    *,
    db_path: Path,
    allow_network: bool,
    logs_dir: Path,
) -> dict[str, Any]:
    """Run a structured endpoint that does not use an index manifest."""

    started = datetime.now(SHANGHAI)
    receipt: dict[str, Any] = {
        "source": source,
        "started_at": started.isoformat(),
        "status": "STARTED",
        "discovered": 0,
        "baseline_skipped": 0,
        "carried_pending": 0,
        "selected": 0,
        "new_observations": 0,
        "revisions": 0,
        "metadata_updates": 0,
        "unchanged": 0,
        "parse_errors": 0,
        "http_success": 0,
        "raw_downloaded": 0,
        "runtime_seconds": 0.0,
        "errors": [],
    }
    conn = None
    try:
        conn = get_connection(db_path)
        if source in {"CHINABOND", "USTREASURY"}:
            today = datetime.now(SHANGHAI).date()
            closed_before = today.replace(day=1)
            if source_state.get("history_complete"):
                lookback = int(settings.get("daily_lookback_days", 75))
                start_date = (
                    closed_before - timedelta(days=lookback)
                ).replace(day=1)
                run_mode = "recent_closed_months"
            else:
                start_date = date.fromisoformat(
                    str(settings["history_start"])
                )
                run_mode = "initial_history"
            ingest_history = (
                ingest_chinabond_history
                if source == "CHINABOND"
                else ingest_us_treasury_history
            )
            result = ingest_history(
                conn,
                start_date=start_date,
                end_date=today,
                closed_before=closed_before,
                allow_network=allow_network,
                refresh=True,
                logs_dir=logs_dir,
            )
            receipt.update(
                mode=run_mode,
                query_start=start_date.isoformat(),
                query_end=today.isoformat(),
                closed_before=closed_before.isoformat(),
            )
            if (
                run_mode == "initial_history"
                and result.status == "SUCCESS"
                and result.parse_errors == 0
            ):
                source_state["history_complete"] = True
                source_state["history_completed_at"] = (
                    datetime.now(SHANGHAI).isoformat()
                )
        elif source == "IMF":
            result = ingest_imf_commodity(
                conn,
                url=str(settings["url"]),
                allow_network=allow_network,
                refresh=True,
                logs_dir=logs_dir,
                skip_unchanged_fetch=bool(settings.get("skip_unchanged_fetch", False)),
            )
            receipt.update(
                mode="official_current_history_with_estimated_visibility",
                url=str(settings["url"]),
            )
        elif source in {"EASTMONEY_MACRO", "SINA_MACRO"}:
            result = ingest_cn_fallback(
                conn,
                source_name=source,
                latest_periods=int(settings.get("latest_periods", 3)),
                allow_network=allow_network,
                refresh=True,
                logs_dir=logs_dir,
            )
            receipt.update(
                mode="third_party_current_history_first_seen_fallback",
                latest_periods=int(settings.get("latest_periods", 3)),
            )
        else:
            raise ValueError(f"unsupported direct data source: {source}")

        receipt["discovered"] = result.urls_requested
        receipt["selected"] = result.urls_requested
        for field in (
            "new_observations",
            "revisions",
            "metadata_updates",
            "unchanged",
            "parse_errors",
            "http_success",
            "raw_downloaded",
            "runtime_seconds",
        ):
            receipt[field] = getattr(result, field)
        receipt["errors"] = list(result.errors)
        receipt["status"] = result.status
        changed = (
            result.new_observations
            + result.revisions
            + result.metadata_updates
        )
        if receipt["status"] == "SUCCESS" and changed == 0:
            receipt["status"] = "SUCCESS_NO_CHANGE"
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        budget_deferred = (
            source in {"EASTMONEY_MACRO", "SINA_MACRO"}
            and isinstance(exc, CrawlSafetyError)
            and "request budget exhausted" in str(exc)
        )
        if budget_deferred:
            receipt["status"] = "DEFERRED_BUDGET"
            receipt["deferred_reason"] = message
        else:
            receipt["status"] = "FAILED"
            receipt["errors"].append(message)
    finally:
        if conn is not None:
            conn.close()

    receipt["finished_at"] = datetime.now(SHANGHAI).isoformat()
    receipt["elapsed_seconds"] = round(
        (datetime.now(SHANGHAI) - started).total_seconds(), 3
    )
    receipt["runtime_seconds"] = round(
        float(receipt.get("runtime_seconds", 0.0)), 3
    )
    source_state["last_run"] = dict(receipt)
    return receipt

def _policy_blocked_receipt(source: str, source_state: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(SHANGHAI).isoformat()
    receipt = {
        "source": source,
        "started_at": now,
        "finished_at": now,
        "elapsed_seconds": 0.0,
        "status": "BLOCKED_POLICY",
        "discovered": 0,
        "baseline_skipped": 0,
        "carried_pending": 0,
        "deferred_backoff": 0,
        "selected": 0,
        "new_observations": 0,
        "revisions": 0,
        "metadata_updates": 0,
        "unchanged": 0,
        "parse_errors": 0,
        "http_success": 0,
        "raw_downloaded": 0,
        "runtime_seconds": 0.0,
        "errors": [],
        "policy_note": "daily fetch disabled; robots policy is probed by the weekly revision task",
        "last_policy_probe_at": source_state.get("last_policy_probe_at"),
    }
    source_state["policy_status"] = "BLOCKED_POLICY"
    source_state["last_run"] = dict(receipt)
    return receipt


def run_source(
    source: str,
    settings: dict[str, Any],
    source_state: dict[str, Any],
    *,
    db_path: Path,
    allow_network: bool,
    logs_dir: Path,
) -> dict[str, Any]:
    if settings.get("policy_blocked") and not settings.get("policy_probe", False):
        return _policy_blocked_receipt(source, source_state)
    if settings.get("policy_blocked") and settings.get("policy_probe", False):
        source_state["last_policy_probe_at"] = datetime.now(SHANGHAI).isoformat()
    if source in {
        "CHINABOND", "USTREASURY", "IMF",
        "EASTMONEY_MACRO", "SINA_MACRO",
    }:
        return run_direct_data_source(
            source,
            settings,
            source_state,
            db_path=db_path,
            allow_network=allow_network,
            logs_dir=logs_dir,
        )
    if source in {"OECD", "RTDSM"}:
        return run_manifest_source(
            source,
            settings,
            source_state,
            db_path=db_path,
            allow_network=allow_network,
            logs_dir=logs_dir,
        )
    started = datetime.now(SHANGHAI)
    receipt: dict[str, Any] = {
        "source": source,
        "started_at": started.isoformat(),
        "status": "STARTED",
        "index_urls": _index_urls(settings),
        "discovered": 0,
        "baseline_skipped": 0,
        "deferred_backoff": 0,
        "selected": 0,
        "new_observations": 0,
        "revisions": 0,
        "metadata_updates": 0,
        "unchanged": 0,
        "parse_errors": 0,
        "errors": [],
        "index_errors": [],
        "candidate_warnings": [],
    }
    known_urls = source_state.setdefault("known_urls", {})
    migration_time = datetime.now(SHANGHAI)
    for entry in known_urls.values():
        _ensure_retry_schedule(entry, settings, migration_time)
    conn = None
    selected: list[CandidateUrl] = []
    try:
        conn = get_connection(db_path)
        _progress(f"{source}: fetching {len(receipt['index_urls'])} index page(s)")
        if settings.get("independent_indexes", False):
            candidates_by_url: dict[str, CandidateUrl] = {}
            raw_files: list[str] = []
            for index_url in receipt["index_urls"]:
                try:
                    found, archived = fetch_and_discover_indexes(
                        conn,
                        source=source,
                        urls=[index_url],
                        allow_network=allow_network,
                        refresh=True,
                    )
                    raw_files.extend(archived)
                    candidates_by_url.update({item.url: item for item in found})
                except Exception as exc:
                    receipt["index_errors"].append(
                        f"{index_url}: {type(exc).__name__}: {exc}"
                    )
            if not raw_files:
                detail = "; ".join(receipt["index_errors"])
                raise RuntimeError(f"all independent indexes failed: {detail}")
            candidates = sorted(
                candidates_by_url.values(),
                key=lambda item: (item.period or "", item.url),
                reverse=True,
            )
        else:
            candidates, raw_files = fetch_and_discover_indexes(
                conn,
                source=source,
                urls=receipt["index_urls"],
                allow_network=allow_network,
                refresh=True,
            )
        now_text = datetime.now(SHANGHAI).isoformat()
        receipt["discovered"] = len(candidates)
        receipt["index_raw_files"] = raw_files
        receipt["candidates"] = [asdict(item) for item in candidates]
        bootstrap_baseline = bool(
            settings.get("bootstrap_existing_as_baseline", False)
        ) and not known_urls
        for item in candidates:
            entry = known_urls.setdefault(item.url, {})
            entry.setdefault("first_seen_at", now_text)
            entry.update(
                last_seen_at=now_text,
                title=item.title,
                period=item.period,
                kind=item.kind,
                index_raw_file=item.index_raw_file,
            )
            if bootstrap_baseline:
                entry["baseline_ignored_at"] = now_text
        if bootstrap_baseline:
            receipt["baseline_skipped"] = len(candidates)
        candidate_pool = _carry_pending_candidates(source, candidates, known_urls)
        receipt["carried_pending"] = len(candidate_pool) - len(candidates)
        selection_time = datetime.now(SHANGHAI)
        receipt["deferred_backoff"] = sum(
            1
            for item in candidate_pool
            if known_urls.get(item.url, {}).get("last_error")
            and not known_urls.get(item.url, {}).get("last_success_at")
            and not _retry_due(known_urls.get(item.url, {}), selection_time)
        )
        selected = select_candidates(
            candidate_pool,
            known_urls,
            recheck_latest=int(settings.get("recheck_latest", 1)),
            max_candidates=int(settings.get("max_candidates_per_run", 20)),
            now=selection_time,
        )
        receipt["selected"] = len(selected)
        receipt["selected_urls"] = [item.url for item in selected]
        _progress(
            f"{source}: discovery complete discovered={len(candidates)} "
            f"selected={len(selected)} carried_pending={receipt['carried_pending']}"
        )
        for item in selected:
            known_urls[item.url].pop("baseline_ignored_at", None)
        if not candidates and not selected:
            receipt["status"] = "DISCOVERY_EMPTY"
            receipt["errors"].append("official index returned no matching release links")
        elif not selected:
            receipt["status"] = "SUCCESS_NO_CHANGE"
        else:
            _progress(f"{source}: ingesting {len(selected)} selected URL(s)")
            result_errors: dict[str, str] = {}
            successful_periods: set[str | None] = set()
            if settings.get("independent_candidates", False):
                for item in selected:
                    try:
                        result = ingest_url_manifest(
                            conn,
                            source_name=source,
                            urls=[item.url],
                            allow_network=allow_network,
                            refresh=True,
                            logs_dir=logs_dir,
                            observe_same_url_revisions=True,
                        )
                        for field in (
                            "new_observations",
                            "revisions",
                            "metadata_updates",
                            "unchanged",
                            "parse_errors",
                            "http_success",
                            "raw_downloaded",
                            "runtime_seconds",
                        ):
                            receipt[field] = receipt.get(field, 0) + getattr(result, field)
                        error = _error_for_url(result.errors, item.url)
                        if error:
                            result_errors[item.url] = error
                        elif result.status == "SUCCESS":
                            successful_periods.add(item.period)
                        else:
                            result_errors[item.url] = (
                                f"{item.url}: candidate status {result.status}"
                            )
                    except Exception as exc:
                        result_errors[item.url] = (
                            f"{item.url}: {type(exc).__name__}: {exc}"
                        )
                for item in selected:
                    error = result_errors.get(item.url)
                    if not error:
                        continue
                    if item.period in successful_periods:
                        receipt["candidate_warnings"].append(error)
                    else:
                        receipt["errors"].append(error)
                receipt["status"] = (
                    "SUCCESS"
                    if successful_periods and not receipt["errors"]
                    else "PARTIAL"
                    if successful_periods
                    else "FAILED"
                )
            else:
                result = ingest_url_manifest(
                    conn,
                    source_name=source,
                    urls=[item.url for item in selected],
                    allow_network=allow_network,
                    refresh=True,
                    logs_dir=logs_dir,
                    observe_same_url_revisions=True,
                )
                for field in (
                    "new_observations",
                    "revisions",
                    "metadata_updates",
                    "unchanged",
                    "parse_errors",
                    "http_success",
                    "raw_downloaded",
                    "runtime_seconds",
                ):
                    receipt[field] = getattr(result, field)
                receipt["errors"] = list(result.errors)
                receipt["status"] = result.status
                for item in selected:
                    error = _error_for_url(result.errors, item.url)
                    if error:
                        result_errors[item.url] = error

            attempt_at = datetime.now(SHANGHAI)
            retry_days = [int(day) for day in settings.get("retry_backoff_days", [1, 3, 7])]
            cooldown_days = int(settings.get("not_found_cooldown_days", 30))
            for item in selected:
                entry = known_urls.setdefault(item.url, {})
                error = result_errors.get(item.url)
                if error:
                    _record_candidate_failure(
                        entry,
                        error,
                        attempt_at,
                        retry_backoff_days=retry_days,
                        not_found_cooldown_days=cooldown_days,
                    )
                else:
                    _record_candidate_success(entry, attempt_at)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        is_policy_block = bool(settings.get("policy_blocked")) and "robots.txt disallows" in message
        is_transport_block = bool(settings.get("transport_soft_block")) and any(
            marker in message
            for marker in (
                "cannot verify robots.txt",
                "CERTIFICATE_VERIFY_FAILED",
                "certificate verify failed",
            )
        )
        if is_policy_block:
            receipt["status"] = "BLOCKED_POLICY"
            receipt["errors"].append(message)
            source_state["policy_status"] = "BLOCKED_POLICY"
            source_state["last_policy_error"] = message
        elif is_transport_block:
            receipt["status"] = "BLOCKED_TRANSPORT"
            receipt["transport_note"] = message
            source_state["transport_status"] = "BLOCKED_TRANSPORT"
            source_state["last_transport_error"] = message
        else:
            receipt["status"] = "FAILED"
            receipt["errors"].append(message)
        attempt_at = datetime.now(SHANGHAI)
        retry_days = [int(day) for day in settings.get("retry_backoff_days", [1, 3, 7])]
        cooldown_days = int(settings.get("not_found_cooldown_days", 30))
        for item in selected:
            entry = known_urls.setdefault(item.url, {})
            _record_candidate_failure(
                entry,
                message,
                attempt_at,
                retry_backoff_days=retry_days,
                not_found_cooldown_days=cooldown_days,
            )
    finally:
        if conn is not None:
            conn.close()
    receipt["finished_at"] = datetime.now(SHANGHAI).isoformat()
    receipt["elapsed_seconds"] = round(
        (datetime.now(SHANGHAI) - started).total_seconds(), 3
    )
    source_state["last_run"] = {
        key: value for key, value in receipt.items()
        if key not in {"candidates", "selected_urls", "index_raw_files"}
    }
    return receipt


def _overall_status(receipts: list[dict[str, Any]]) -> str:
    statuses = [item["status"] for item in receipts]
    successful = {
        "SUCCESS", "SUCCESS_NO_CHANGE", "BLOCKED_POLICY", "BLOCKED_TRANSPORT", "DEFERRED_BUDGET"
    }
    if statuses and all(status in successful for status in statuses):
        return "SUCCESS"
    if statuses and all(status == "FAILED" for status in statuses):
        return "FAILED"
    return "PARTIAL"


def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Daily macro update - {report['finished_at']}",
        "",
        f"Overall: **{report['status']}**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.",
        "",
        "| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["sources"]:
        lines.append(
            f"| {item['source']} | {item['status']} | {item['discovered']} | "
            f"{item.get('baseline_skipped', 0)} | "
            f"{item.get('carried_pending', 0)} | {item.get('deferred_backoff', 0)} | "
            f"{item['selected']} | "
            f"{item['new_observations']} | {item['revisions']} | "
            f"{item['unchanged']} | {item['parse_errors']} |"
        )
    for item in report["sources"]:
        if item.get("no_recent_records", 0):
            lines.append(
                f"{item['source']}: {item['no_recent_records']} valid OECD queries "
                "returned NoRecordsFound within the recent window."
            )
    lines.extend([
        "",
        "Each run archives source response bytes and uses append-only, idempotent ingestion. "
        "Parser failures remain pending in durable state and are retried even after their URL leaves the current index.",
    ])
    for item in report["sources"]:
        if item.get("transport_note"):
            lines.extend([
                "", f"## {item['source']} transport block",
                f"- {item['transport_note']}",
            ])
        if item.get("errors"):
            lines.extend(["", f"## {item['source']} errors"])
            lines.extend(f"- {error}" for error in item["errors"])
        if item.get("index_errors"):
            lines.extend(["", f"## {item['source']} index warnings"])
            lines.extend(f"- {error}" for error in item["index_errors"])
        if item.get("candidate_warnings"):
            lines.extend(["", f"## {item['source']} candidate warnings"])
            lines.extend(f"- {error}" for error in item["candidate_warnings"])
    audit = report.get("semantic_audit")
    if audit:
        lines.extend([
            "",
            "## DeepSeek semantic audit",
            "",
            f"Status: **{audit.get('status', 'UNKNOWN')}**; "
            f"candidates: {audit.get('candidate_count', 0)} / "
            f"{audit.get('candidate_total', 0)}; "
            f"API called: {'yes' if audit.get('api_called') else 'no'}.",
            "",
            f"Report: `{audit.get('report_md', '')}`",
        ])
    delivery = report.get("email_delivery")
    if delivery:
        lines.extend([
            "",
            "## Email delivery",
            "",
            f"Status: **{delivery.get('status', 'UNKNOWN')}**; "
            f"recipient: {delivery.get('recipient', '')}.",
        ])
    return "\n".join(lines) + "\n"


def write_reports(config: dict[str, Any], report: dict[str, Any]) -> tuple[Path, Path]:
    report_dir = Path(config["report_dir"])
    run_dir = report_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_path = run_dir / f"{report['run_id']}.json"
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    _atomic_json(run_path, report)
    _atomic_json(latest_json, report)
    temporary = latest_md.with_suffix(".md.tmp")
    temporary.write_text(render_report(report), encoding="utf-8")
    os.replace(temporary, latest_md)
    return latest_json, latest_md


def dry_run_plan(config: dict[str, Any], selected_sources: list[str]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for source in selected_sources:
        settings = config["sources"][source]
        if source in {"OECD", "RTDSM"}:
            sources.append({
                "source": source,
                "job_manifests": [str(path) for path in _job_manifest_paths(settings)],
                "mode": (
                    "official_sdmx_recent_periods"
                    if source == "OECD" and int(settings.get("recent_lookback_months", 0)) > 0
                    else "official_sdmx_full_revisions"
                    if source == "OECD"
                    else "official_rtdsm_conditional_files"
                    if settings.get("skip_unchanged_fetch", False)
                    else "official_rtdsm_full_workbooks"
                ),
                "recent_lookback_months": int(settings.get("recent_lookback_months", 0)),
                "skip_unchanged_fetch": bool(settings.get("skip_unchanged_fetch", False)),
            })
        elif source in {"CHINABOND", "USTREASURY"}:
            sources.append({
                "source": source,
                "history_start": str(settings["history_start"]),
                "daily_lookback_days": int(
                    settings.get("daily_lookback_days", 75)
                ),
                "mode": "official_daily_curves_to_closed_month_end",
            })
        elif source == "IMF":
            sources.append({
                "source": source,
                "url": str(settings["url"]),
                "mode": "official_current_history_with_estimated_visibility",
            })
        elif source in {"EASTMONEY_MACRO", "SINA_MACRO"}:
            sources.append({
                "source": source,
                "latest_periods": int(settings.get("latest_periods", 3)),
                "mode": "third_party_current_history_first_seen_fallback",
            })
        else:
            sources.append({
                "source": source,
                "index_urls": _index_urls(settings),
                "recheck_latest": int(settings.get("recheck_latest", 3)),
                "max_candidates_per_run": int(
                    settings.get("max_candidates_per_run", 20)
                ),
                "bootstrap_existing_as_baseline": bool(
                    settings.get("bootstrap_existing_as_baseline", False)
                ),
                "retry_backoff_days": [int(day) for day in settings.get("retry_backoff_days", [1, 3, 7])],
                "not_found_cooldown_days": int(settings.get("not_found_cooldown_days", 30)),
                "policy_blocked": bool(settings.get("policy_blocked", False)),
                "policy_probe": bool(settings.get("policy_probe", False)),
                "independent_indexes": bool(settings.get("independent_indexes", False)),
                "independent_candidates": bool(settings.get("independent_candidates", False)),
                "transport_soft_block": bool(settings.get("transport_soft_block", False)),
                "mode": (
                    "government_reprint_indexes"
                    if source == "PBOC_MIRROR"
                    else "official_web_index"
                ),
            })
    return {
        "status": "DRY_RUN",
        "config": config["config_path"],
        "wind_included": False,
        "semantic_audit": {
            "enabled": bool(
                config.get("semantic_audit", {}).get("enabled", False)
            ),
            "provider": str(
                config.get("semantic_audit", {}).get("provider", "deepseek")
            ),
            "model": str(
                config.get("semantic_audit", {}).get("model", "deepseek-flash")
            ),
            "runs_only_on_changes_or_errors": True,
        },
        "email_notification": {
            "enabled": bool(
                config.get("email_notification", {}).get("enabled", False)
            ),
            "recipient": str(
                config.get("email_notification", {}).get("recipient", "")
            ),
            "label": str(
                config.get("email_notification", {}).get("label", "")
            ),
            "attachments": ["update_report", "deepseek_audit"],
        },
        "sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--db-path", default=str(ROOT / "macro_pit_v2.duckdb"))
    parser.add_argument("--sources", nargs="*", choices=ALLOWED_SOURCES)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--lock-wait-seconds", type=int, default=0,
        help="Wait for another scheduled database writer before starting.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    configured = [
        source for source in ALLOWED_SOURCES
        if source in config["sources"] and config["sources"][source].get("enabled", True)
    ]
    selected_sources = args.sources or configured
    if args.dry_run:
        print(json.dumps(dry_run_plan(config, selected_sources), ensure_ascii=False, indent=2))
        return 0
    if not args.allow_network:
        parser.error("live daily update requires --allow-network")

    db_path = _workspace_path(args.db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    state_path = Path(config["state_path"])
    lock_path = Path(config["lock_path"])
    logs_dir = Path(config["logs_dir"])
    logs_dir.mkdir(parents=True, exist_ok=True)
    state = _load_json(state_path, {"version": 1, "sources": {}})
    run_started = datetime.now(SHANGHAI)
    run_id = run_started.strftime("%Y%m%dT%H%M%S")
    receipts: list[dict[str, Any]] = []

    _progress(
        f"RUN_START id={run_id} sources={','.join(selected_sources)} "
        f"database={db_path}"
    )
    with RunLock(lock_path, wait_seconds=args.lock_wait_seconds):
        for source in selected_sources:
            _progress(f"{source}: START")
            settings = config["sources"][source]
            source_state = state.setdefault("sources", {}).setdefault(source, {})
            receipt = run_source(
                source,
                settings,
                source_state,
                db_path=db_path,
                allow_network=True,
                logs_dir=logs_dir,
            )
            receipts.append(receipt)
            state["last_run_at"] = datetime.now(SHANGHAI).isoformat()
            state["last_run_id"] = run_id
            _atomic_json(state_path, state)
            _progress(
                f"{source}: {receipt['status']} discovered={receipt['discovered']} "
                f"selected={receipt['selected']} inserted={receipt['new_observations']} "
                f"revisions={receipt['revisions']} parse_errors={receipt['parse_errors']}"
            )

        finished = datetime.now(SHANGHAI)
        report = {
            "run_id": run_id,
            "started_at": run_started.isoformat(),
            "finished_at": finished.isoformat(),
            "elapsed_seconds": round((finished - run_started).total_seconds(), 3),
            "status": _overall_status(receipts),
            "run_mode": str(config.get("run_mode", "daily_light")),
            "wind_included": False,
            "database": str(db_path),
            "sources": receipts,
        }
        latest_json, latest_md = write_reports(config, report)
        _progress(f"report_json: {latest_json}")
        _progress(f"report_md: {latest_md}")

    audit_settings = config.get("semantic_audit")
    audit: dict[str, Any] | None = None
    if audit_settings:
        _progress("DEEPSEEK_AUDIT: START")
        audit = run_semantic_audit(
            db_path=db_path,
            daily_report=report,
            settings=audit_settings,
            root=ROOT,
        )
        report["semantic_audit"] = {
            key: audit.get(key) for key in (
                "status", "candidate_count", "candidate_total", "truncated",
                "operational_error_count", "api_called", "model", "summary",
                "error", "report_json", "report_md",
            ) if audit.get(key) is not None
        }
        latest_json, latest_md = write_reports(config, report)
        _progress(
            f"DEEPSEEK_AUDIT: {audit['status']} "
            f"candidates={audit.get('candidate_count', 0)}/"
            f"{audit.get('candidate_total', 0)} "
            f"report={audit.get('report_md', '')}"
        )
    email_settings = config.get("email_notification")
    if email_settings and audit is not None:
        _progress("EMAIL_DELIVERY: START")
        delivery = send_audit_email(
            settings=email_settings,
            update_report=report,
            audit_result=audit,
            update_report_md=latest_md,
        )
        report["email_delivery"] = {
            key: delivery.get(key) for key in (
                "status", "recipient", "label", "sent_at", "error",
                "attachments", "run_report", "latest_report",
            ) if delivery.get(key) is not None
        }
        latest_json, latest_md = write_reports(config, report)
        _progress(
            f"EMAIL_DELIVERY: {delivery['status']} "
            f"recipient={delivery.get('recipient', '')} "
            f"receipt={delivery.get('latest_report', '')}"
        )
    return 0 if report["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
