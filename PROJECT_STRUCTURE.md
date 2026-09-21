# Macro_Data project map

This file is the navigation page for the repository. It separates unattended
production code from one-time research work without changing any runtime path.

## Production path

The unattended pipeline has four Windows entry points in the repository root:

| Schedule | Entry point | Configuration | Purpose |
| --- | --- | --- | --- |
| Daily 22:00 | `run_daily_web_update.cmd` | `config/daily_web_update.yml` | China official/fallback refresh and audit |
| Daily 00:00 | `run_daily_global_update.cmd` | `config/daily_global_update.yml` | Global, rates and commodity refresh |
| Sunday 02:00 | `run_weekly_web_revision.cmd` | `config/weekly_web_revision.yml` | China revision scan |
| Sunday 04:00 | `run_weekly_global_revision.cmd` | `config/weekly_global_revision.yml` | Global historical-revision scan |

All four launch `scripts/run_with_live_log.py`, then
`scripts/run_daily_web_update.py`. The production library is
`src/macro_pit/`; source-specific adapters are in `src/macro_pit/sources/`.

The current database is `macro_pit_v2.duckdb`. Query and export shortcuts are:

- `query_pit_wide.cmd`
- `export_pit_long.cmd`
- `python -m macro_pit query-wide ...`
- `python -m macro_pit export-long ...`

## Configuration boundary

The four scheduled YAML files, the manifests referenced by them,
`config/sources.yml`, `config/series_registry.yml`, the estimated-availability
rules, and `config/acceptance.yml` are production configuration.

Dated `batch`, `probe`, `review`, `candidate`, `expected`, and `validation`
files are grouped by source under `config/history/`. They are frozen evidence
for completed backfills and are not loaded by the daily or weekly entry points.
See `config/README.md` before changing or running one of them.

## Runtime and evidence directories

| Path | Role | Cleanup rule |
| --- | --- | --- |
| `data/` | raw archives, state, exports, backups | frozen; do not move, delete, deduplicate or rewrite during repository cleanup |
| `logs/` | live task logs | local runtime output |
| `outputs/` | ad-hoc command output | local generated output |
| `reports/v2/` | current status plus historical evidence | keep current entry points easy to find; retain evidence unless a separate retention decision is made |
| `tests/` | automated contracts | run after production code/config changes |

The old root databases named `macro_pit.duckdb` and
`macro_pit_v2_pre_*.duckdb` are retained snapshots. They are not the production
database and are not cleanup targets in the current pass.

Completed architecture and migration documents are under `docs/history/`.
They describe earlier project states and should not override the current
scheduled configurations or `reports/v2/STATUS.md`.

The 44 completed archive-parser rounds are grouped under
`reports/v2/history/archive_parse/`; current operational reports remain directly
under `reports/v2/`.

## Script boundary

`scripts/README.md` divides scripts into scheduled runtime, installation,
maintenance/export, and historical one-time work. Only the scheduled runtime
files are part of the normal daily execution path. A script with a date or a
specific backfill name should be treated as a reproducibility artifact unless
the production configuration explicitly references it.

## Reports to open first

1. `reports/v2/STATUS.md` — cumulative project status and decisions.
2. `reports/v2/daily_web_update/latest.md` — latest China scheduled run.
3. `reports/v2/daily_global_update/latest.md` — latest global scheduled run.
4. `reports/v2/weekly_web_revision/latest.md` — latest China revision audit.
5. `reports/v2/weekly_global_revision/latest.md` — latest global revision audit.
6. `reports/v2/combined_pit_long/README.md` — composite long-table contract.

## Cleanup policy

Repository cleanup must preserve the four root launchers, their referenced
configuration, `src/`, `tests/`, the main database, and all of `data/`.
Regenerable `.pytest_*` and `__pycache__` directories may be removed. Moving
historical scripts or manifests requires a reference scan and corresponding
documentation updates first.
