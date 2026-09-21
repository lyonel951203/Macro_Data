# Scripts guide

This directory contains scheduled runtime code together with maintenance and
historical reproducibility scripts. Only the first group is executed by the
normal unattended pipeline.

## Scheduled runtime

- `run_daily_web_update.py` — shared China/global and daily/weekly runner.
- `run_with_live_log.py` — streams task output into launcher logs.

The four root `run_*update.cmd` and `run_*revision.cmd` files call these two
scripts. Do not rename or move them without updating and reinstalling the
Windows scheduled tasks.

## Task installation and credentials

- `setup/install_daily_web_update_task.ps1`
- `setup/install_daily_global_update_task.ps1`
- `setup/install_weekly_revision_tasks.ps1`
- `setup/set_deepseek_api_key.ps1`

## Current maintenance and exports

Inventory, audit, calibration, availability, email, and Wind ingestion scripts
are operator-invoked tools under `tools/`. They are not run merely because they
are present. Examples include `tools/export_current_field_inventory.py`,
`tools/export_non_cn_field_inventory.py`, `tools/estimate_availability.py`,
`tools/ingest_wind_mcp.py`, and `tools/send_latest_audit_email.py`.

## Historical and one-time work

Reusable scripts for completed source gaps and review rounds are under
`history/`; date-specific programs are under `one_off/`. They may rely on local
evidence in `data/` and a matching report under `reports/v2/`. Treat them as
historical tools unless a current runbook explicitly calls them.

`run_nbs_history_once.ps1` is retained for the disabled, completed NBS history
task. It is not part of the four active daily/weekly jobs.

The earlier cleanup archive remains at
`data/backups/code_cleanup/deprecated_code_20260916.zip`; its SHA-256 inventory
is `reports/v2/code_cleanup/removed_code_manifest.csv`.

Daily jobs use recent or conditional refreshes. Weekly jobs perform broader
OECD/RTDSM and official-source revision checks. Failed pages use 1/3/7-day
backoff; HTTP 404 pages use a 30-day cooldown.
