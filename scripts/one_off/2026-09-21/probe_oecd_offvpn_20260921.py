# coding: utf-8
"""One-shot, read-only OECD connectivity probe for 2026-09-21 09:45 CST."""
from __future__ import annotations

import json
import os
import socket
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import httpx

from macro_pit.pipeline import _expand_oecd_country_jobs
from macro_pit.sources.oecd import OECDSource
from macro_pit.timeutils import SHANGHAI

OUTPUT_DIR = ROOT / "reports" / "v2" / "oecd_offvpn_probe"
REPORT_PATH = OUTPUT_DIR / "20260921T094500.json"
LATEST_PATH = OUTPUT_DIR / "latest.json"


def save(report: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    for path in (REPORT_PATH, LATEST_PATH):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)


def proxy_signals() -> dict:
    result = {
        "proxy_environment_names": sorted(
            key for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
            if os.environ.get(key)
        ),
        "windows_proxy_enabled": None,
    }
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            result["windows_proxy_enabled"] = bool(
                winreg.QueryValueEx(key, "ProxyEnable")[0]
            )
        finally:
            winreg.CloseKey(key)
    except (OSError, ImportError):
        pass
    return result


def data_job(ref_area: str, prefix: str) -> str:
    job = _expand_oecd_country_jobs({
        "countries": [{"ref_area": ref_area, "prefix": prefix}]
    })[0]
    return job["url"] + "&startPeriod=2025-03"


def run() -> int:
    report = {
        "scheduled_for": "2026-09-21T09:45:00+08:00",
        "started_at": datetime.now(SHANGHAI).isoformat(),
        "status": "RUNNING",
        "host": "sdmx.oecd.org",
        "proxy_signals": proxy_signals(),
        "dns": {},
        "checks": [],
        "finished_at": None,
    }
    save(report)
    try:
        try:
            answers = socket.getaddrinfo("sdmx.oecd.org", 443)
            report["dns"] = {"resolved": True, "answer_count": len(answers)}
        except OSError as exc:
            report["dns"] = {
                "resolved": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        save(report)

        source = OECDSource(allow_network=True)
        try:
            for label, url in (
                ("DEU_recent_GDP", data_job("DEU", "DE")),
                ("IND_recent_GDP", data_job("IND", "IN")),
            ):
                row = {
                    "label": label,
                    "url": url,
                    "started_at": datetime.now(SHANGHAI).isoformat(),
                }
                before = len(source.client.events)
                try:
                    fetched = source.fetch(
                        url, refresh=True,
                        headers={"Accept": "text/csv;version=2.0"},
                    )
                    header = fetched.content.splitlines()[0].decode(
                        "utf-8-sig", errors="replace"
                    ) if fetched.content else ""
                    row.update({
                        "result": "DATA",
                        "fetch_status_code": fetched.status_code,
                        "from_cache": fetched.from_cache,
                        "content_bytes": len(fetched.content),
                        "csv_header_ok": all(
                            field in header.split(",")
                            for field in ("REF_AREA", "EDITION", "OBS_VALUE")
                        ),
                    })
                except httpx.HTTPStatusError as exc:
                    row.update({
                        "result": "HTTP_ERROR",
                        "http_status": exc.response.status_code,
                        "response_body": exc.response.text[:200],
                    })
                except Exception as exc:
                    row.update({
                        "result": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                row["requests"] = [
                    {
                        "url": event.url,
                        "http_status": event.http_status,
                        "error_type": event.error_type,
                        "error_message": event.error_message,
                    }
                    for event in source.client.events[before:]
                ]
                row["finished_at"] = datetime.now(SHANGHAI).isoformat()
                report["checks"].append(row)
                save(report)
        finally:
            source.close()

        germany, india = report["checks"]
        german_data_request = any(
            item["url"] == germany["url"]
            and item["http_status"] in (200, 304)
            for item in germany["requests"]
        )
        german_ok = (
            germany.get("result") == "DATA"
            and germany.get("csv_header_ok") is True
            and german_data_request
        )
        india_answered = (
            india.get("result") == "DATA"
            or (
                india.get("http_status") == 404
                and india.get("response_body", "").strip() == "NoRecordsFound"
            )
        )
        report["status"] = "PASS" if german_ok and india_answered else (
            "PARTIAL" if german_ok else "FAIL"
        )
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        report["finished_at"] = datetime.now(SHANGHAI).isoformat()
        save(report)
        print(json.dumps({
            "status": report["status"],
            "report": str(REPORT_PATH),
            "checks": [
                {"label": item["label"], "result": item["result"]}
                for item in report["checks"]
            ],
        }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        print(json.dumps({
            "status": "DRY_RUN",
            "report_path": str(REPORT_PATH),
            "urls": [
                data_job("DEU", "DE"),
                data_job("IND", "IN"),
            ],
        }, ensure_ascii=False))
        raise SystemExit(0)
    raise SystemExit(run())
