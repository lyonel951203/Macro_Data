"""SMTP delivery for unattended macro update and audit reports."""
from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
import json
import os
from pathlib import Path
import smtplib
import ssl
from typing import Any


def _flat_ini(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        key, separator, value = line.partition("=")
        if separator:
            payload[key.strip().lower()] = value.strip()
    return payload


def _account(settings: dict[str, Any]) -> tuple[dict[str, Any] | None, Path]:
    config_file = settings.get("config_file")
    if config_file:
        path = Path(str(config_file))
        try:
            payload = _flat_ini(path)
        except OSError:
            return None, path
        sender = str(payload.get("sender") or "").strip()
        password = str(payload.get("password") or "").strip()
        if not sender or not password:
            return None, path
        return {
            "sender": sender,
            "credential": password,
            "smtp_host": str(payload.get("smtp_server") or ""),
            "smtp_port": int(payload.get("smtp_port") or 465),
            "subject": payload.get("subject"),
            "body": payload.get("body"),
            "attachment_update_filename": payload.get(
                "attachment_update_filename"
            ),
            "attachment_audit_filename": payload.get(
                "attachment_audit_filename"
            ),
        }, path

    configured = settings.get("credentials_file")
    path = (
        Path(str(configured)).expanduser()
        if configured
        else Path.home() / ".macro_pit" / "qq_smtp.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None, path
    sender = str(payload.get("sender") or "").strip()
    code = str(payload.get("authorization_code") or "").strip()
    if not sender or not code:
        return None, path
    return {
        "sender": sender,
        "credential": code,
        "smtp_host": str(settings.get("smtp_host", "smtp.qq.com")),
        "smtp_port": int(settings.get("smtp_port", 465)),
    }, path


def _render(template: str | None, fallback: str, context: dict[str, Any]) -> str:
    value = str(template or fallback).replace("\\n", "\n")
    return value.format_map(context)


def _write_delivery(report_dir: Path, result: dict[str, Any]) -> tuple[Path, Path]:
    runs = report_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_path = runs / f"{result['run_id']}.json"
    latest_path = report_dir / "latest.json"
    encoded = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    for path in (run_path, latest_path):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)
    return run_path, latest_path


def _attachment(message: EmailMessage, path_value: str | None, filename: str) -> bool:
    if not path_value:
        return False
    path = Path(path_value)
    if not path.is_file():
        return False
    message.add_attachment(
        path.read_text(encoding="utf-8"),
        subtype="markdown",
        filename=filename,
    )
    return True


def send_audit_email(
    *,
    settings: dict[str, Any],
    update_report: dict[str, Any],
    audit_result: dict[str, Any],
    update_report_md: str | Path,
) -> dict[str, Any]:
    """Send both Markdown reports and persist a credential-free receipt."""
    run_id = str(update_report["run_id"])
    report_dir = Path(str(settings["report_dir"]))
    result: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "status": "DISABLED",
        "recipient": str(settings.get("recipient") or ""),
        "label": str(settings.get("label") or update_report.get("run_mode") or "macro"),
        "audit_status": str(audit_result.get("status") or "UNKNOWN"),
        "update_status": str(update_report.get("status") or "UNKNOWN"),
        "attachments": [],
    }
    if not settings.get("enabled", False):
        run_path, latest_path = _write_delivery(report_dir, result)
        return {**result, "run_report": str(run_path), "latest_report": str(latest_path)}

    account, credential_path = _account(settings)
    result["credential_source"] = f"file:{credential_path}"
    if account is None:
        result.update(
            status="SKIPPED_NO_CREDENTIALS",
            error="SMTP account configuration is missing or incomplete.",
        )
        run_path, latest_path = _write_delivery(report_dir, result)
        return {**result, "run_report": str(run_path), "latest_report": str(latest_path)}

    host = str(account["smtp_host"]).lower()
    port = int(account["smtp_port"])
    if host not in {"smtp.qq.com", "smtp.163.com"} or port != 465:
        result.update(
            status="ERROR",
            error=(
                "SMTP credentials may only be sent to "
                "smtp.qq.com:465 or smtp.163.com:465."
            ),
        )
        run_path, latest_path = _write_delivery(report_dir, result)
        return {**result, "run_report": str(run_path), "latest_report": str(latest_path)}

    recipient = str(settings["recipient"])
    label = str(settings.get("label") or "Macro PIT")
    safe_label = "".join(
        character.lower() if character.isalnum() else "_"
        for character in label
    ).strip("_")
    context = {
        "label": label,
        "label_slug": safe_label,
        "run_id": run_id,
        "update_status": update_report.get("status", "UNKNOWN"),
        "audit_status": audit_result.get("status", "UNKNOWN"),
        "model": audit_result.get("model", "deepseek-flash"),
        "candidate_count": audit_result.get("candidate_count", 0),
        "candidate_total": audit_result.get("candidate_total", 0),
        "summary": audit_result.get("summary", ""),
    }
    message = EmailMessage()
    message["From"] = account["sender"]
    message["To"] = recipient
    message["Subject"] = _render(
        account.get("subject"),
        "[Macro PIT] {label} | {audit_status} | {run_id}",
        context,
    )
    message.set_content(_render(
        account.get("body"),
        (
            "Macro PIT automated report.\\n"
            "Task: {label}\\nRun: {run_id}\\n"
            "Update status: {update_status}\\n"
            "DeepSeek audit: {audit_status}\\nModel: {model}\\n"
            "Candidates: {candidate_count} / {candidate_total}\\n"
            "Summary: {summary}\\n\\n"
            "The update and audit Markdown reports are attached."
        ),
        context,
    ))
    update_filename = _render(
        account.get("attachment_update_filename"),
        "macro_pit_{label_slug}_{run_id}_update.md",
        context,
    )
    audit_filename = _render(
        account.get("attachment_audit_filename"),
        "macro_pit_{label_slug}_{run_id}_deepseek_audit.md",
        context,
    )
    if _attachment(
        message, str(update_report_md),
        update_filename,
    ):
        result["attachments"].append("update_report")
    if _attachment(
        message, audit_result.get("report_md"),
        audit_filename,
    ):
        result["attachments"].append("deepseek_audit")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            host, port, timeout=float(settings.get("timeout_seconds", 60)),
            context=context,
        ) as server:
            server.login(
                account["sender"], account["credential"]
            )

            server.send_message(message)
        result.update(
            status="SENT",
            sent_at=datetime.now().astimezone().isoformat(),
            sender=account["sender"],
        )
    except (OSError, smtplib.SMTPException) as exc:
        result.update(
            status="ERROR",
            error=f"{type(exc).__name__}: {exc}",
        )
    run_path, latest_path = _write_delivery(report_dir, result)
    return {**result, "run_report": str(run_path), "latest_report": str(latest_path)}
