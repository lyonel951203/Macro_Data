# Maintained scripts

This directory now contains production runners, task installers, current
ingestion/export utilities, and the historical parsers that remain covered by
the test suite.

The completed one-off review, migration, and round-specific scripts were
removed from the active tree on 2026-09-16. Their local recovery archive is:

    data/backups/code_cleanup/deprecated_code_20260916.zip

The SHA-256 inventory is recorded in:

    reports/v2/code_cleanup/removed_code_manifest.csv

Current scheduled-task entry points must remain here:

- run_daily_web_update.py
- run_with_live_log.py
- run_nbs_history_once.ps1
- install_daily_web_update_task.ps1
- install_daily_global_update_task.ps1

`run_daily_web_update.py` also drives the 00:00 global task. IMF's official
commodity workbook, the ChinaBond structured source, and the official U.S. Treasury daily yield-curve XML source are enabled. ChinaBond
uses a user-authorized bounded robots.txt retrieval-failure exception; an explicit
Disallow response remains blocking.

Weekly revision entry points:

- `install_weekly_revision_tasks.ps1`
- `run_weekly_web_revision.cmd` (workspace root)
- `run_weekly_global_revision.cmd` (workspace root)

Daily jobs use recent/conditional refreshes; weekly jobs perform the complete OECD/RTDSM revision audit. Failed web pages use 1/3/7-day backoff and 404 pages use a 30-day cooldown.