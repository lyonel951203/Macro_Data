from __future__ import annotations

import json
from pathlib import Path

import macro_pit.email_delivery as delivery


def _reports(tmp_path: Path):
    update_md = tmp_path / "update.md"
    audit_md = tmp_path / "audit.md"
    update_md.write_text("# Update\n", encoding="utf-8")
    audit_md.write_text("# Audit\n", encoding="utf-8")
    update = {
        "run_id": "20260920T020000",
        "status": "SUCCESS",
        "run_mode": "weekly_revision",
    }
    audit = {
        "status": "PASS",
        "model": "deepseek-flash",
        "candidate_count": 2,
        "candidate_total": 2,
        "summary": "All supplied evidence is consistent.",
        "report_md": str(audit_md),
    }
    return update, audit, update_md


def _settings(tmp_path: Path, credential: Path):
    return {
        "enabled": True,
        "recipient": "718711226@qq.com",
        "label": "China weekly revision",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "timeout_seconds": 60,
        "credentials_file": str(credential),
        "report_dir": str(tmp_path / "receipts"),
    }


def test_missing_credentials_is_logged_without_sending(tmp_path, monkeypatch):
    update, audit, update_md = _reports(tmp_path)
    monkeypatch.setattr(
        delivery.smtplib, "SMTP_SSL",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("SMTP must not be called")
        ),
    )
    result = delivery.send_audit_email(
        settings=_settings(tmp_path, tmp_path / "missing.json"),
        update_report=update,
        audit_result=audit,
        update_report_md=update_md,
    )
    assert result["status"] == "SKIPPED_NO_CREDENTIALS"
    assert Path(result["latest_report"]).is_file()


def test_qq_smtp_sends_two_markdown_attachments(tmp_path, monkeypatch):
    credential = tmp_path / "qq.json"
    credential.write_text(json.dumps({
        "sender": "718711226@qq.com",
        "authorization_code": "private-auth-code",
    }), encoding="utf-8")
    update, audit, update_md = _reports(tmp_path)
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout, context):
            captured["endpoint"] = (host, port)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, sender, code):
            captured["login"] = (sender, code)
        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr(delivery.smtplib, "SMTP_SSL", FakeSMTP)
    result = delivery.send_audit_email(
        settings=_settings(tmp_path, credential),
        update_report=update,
        audit_result=audit,
        update_report_md=update_md,
    )
    assert result["status"] == "SENT"
    assert result["attachments"] == ["update_report", "deepseek_audit"]
    assert captured["endpoint"] == ("smtp.qq.com", 465)
    assert captured["message"]["To"] == "718711226@qq.com"
    filenames = {
        part.get_filename() for part in captured["message"].iter_attachments()
    }
    assert len(filenames) == 2
    receipt = Path(result["latest_report"]).read_text(encoding="utf-8")
    assert "private-auth-code" not in receipt
    assert "authorization_code" not in receipt


def test_non_qq_endpoint_never_receives_credentials(tmp_path, monkeypatch):
    credential = tmp_path / "qq.json"
    credential.write_text(json.dumps({
        "sender": "718711226@qq.com",
        "authorization_code": "private-auth-code",
    }), encoding="utf-8")
    update, audit, update_md = _reports(tmp_path)
    monkeypatch.setattr(
        delivery.smtplib, "SMTP_SSL",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("SMTP must not be called")
        ),
    )
    settings = _settings(tmp_path, credential)
    settings["smtp_host"] = "example.com"
    result = delivery.send_audit_email(
        settings=settings,
        update_report=update,
        audit_result=audit,
        update_report_md=update_md,
    )
    assert result["status"] == "ERROR"
    assert "only be sent" in result["error"]


def test_flat_ini_uses_163_templates_and_two_reports(tmp_path, monkeypatch):
    ini = tmp_path / "emailconfig.ini"
    ini.write_text(
        "sender=sender@163.com\n"
        "password=private-163-code\n"
        "smtp_server=smtp.163.com\n"
        "smtp_port=465\n"
        "subject=[Macro PIT] {label} | {audit_status} | {run_id}\n"
        "body=Task: {label}\\nSummary: {summary}\n"
        "attachment_update_filename={label_slug}_{run_id}_update.md\n"
        "attachment_audit_filename={label_slug}_{run_id}_audit.md\n",
        encoding="utf-8",
    )
    update, audit, update_md = _reports(tmp_path)
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout, context):
            captured["endpoint"] = (host, port)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, sender, code):
            captured["login"] = (sender, code)
        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr(delivery.smtplib, "SMTP_SSL", FakeSMTP)
    settings = _settings(tmp_path, tmp_path / "unused.json")
    settings.pop("smtp_host")
    settings.pop("smtp_port")
    settings["config_file"] = str(ini)
    result = delivery.send_audit_email(
        settings=settings,
        update_report=update,
        audit_result=audit,
        update_report_md=update_md,
    )
    assert result["status"] == "SENT"
    assert captured["endpoint"] == ("smtp.163.com", 465)
    assert captured["message"]["From"] == "sender@163.com"
    assert captured["message"]["Subject"].startswith(
        "[Macro PIT] China weekly revision"
    )
    filenames = {
        part.get_filename() for part in captured["message"].iter_attachments()
    }
    assert filenames == {
        "china_weekly_revision_20260920T020000_update.md",
        "china_weekly_revision_20260920T020000_audit.md",
    }
    receipt = Path(result["latest_report"]).read_text(encoding="utf-8")
    assert "private-163-code" not in receipt
