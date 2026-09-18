# Macro PIT email delivery

The four unattended tasks send their update report and DeepSeek audit report to
`718711226@qq.com` after each run:

- China daily update at 22:00
- Global daily update at 00:00
- China weekly revision on Sunday at 02:00
- Global weekly revision on Sunday at 04:00

Delivery receipts are stored under `reports/v2/email_delivery/<task>/`. Email
failure is recorded but does not roll back source ingestion or change its exit
status.

## Mail account configuration

All four tasks use the existing workspace-local `emailconfig.ini`. It contains
the 163 Mail sender, SMTP credential, server, port, subject/body templates, and
the two attachment filename templates.

The active non-secret templates are:

- subject: `[Macro PIT] {label} | {audit_status} | {run_id}`
- update attachment: `macro_pit_{label_slug}_{run_id}_update.md`
- audit attachment:
  `macro_pit_{label_slug}_{run_id}_deepseek_audit.md`

The message body includes task name, run id, update status, DeepSeek status,
model, candidate coverage, and the DeepSeek summary. The two Markdown reports
are attached. Database files and raw source archives are never attached.

`emailconfig.ini` contains a live SMTP credential and is excluded from Git.
The credential is sent only to the configured allowlisted endpoint
`smtp.163.com:465` (or `smtp.qq.com:465` for the optional JSON fallback).

## Manual resend

Send the latest China daily reports without rerunning data collection or
DeepSeek:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts\send_latest_audit_email.py
```

Use `--config` with any of the other three task YAML files to resend that
task's latest reports.
