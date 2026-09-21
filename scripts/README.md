# Scripts guide

This directory contains scheduled runtime code, task setup, and current
operator tools.

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

## Retired one-time work

Completed backfill, probe and review scripts formerly under `history/` and
`one_off/` were removed on 2026-09-21 after their scheduled work ended. Their
reports, inputs and Git history remain available. New reusable behavior belongs
in `src/macro_pit/`; new operator commands belong in `tools/`.

The earlier cleanup archive remains at
`data/backups/code_cleanup/deprecated_code_20260916.zip`; its SHA-256 inventory
is `reports/v2/history/project_cleanup/removed_code_manifest.csv`.

Daily jobs use recent or conditional refreshes. Weekly jobs perform broader
OECD/RTDSM and official-source revision checks. Failed pages use 1/3/7-day
backoff; HTTP 404 pages use a 30-day cooldown.
