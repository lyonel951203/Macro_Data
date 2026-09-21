# Production acceptance after repository cleanup

Run date: 2026-09-21 (Asia/Shanghai)

This acceptance was read-only against `macro_pit_v2.duckdb`. It did not use
the network, call DeepSeek, send email, or modify `data/`. Temporary query
exports were written under ignored `outputs/` and removed after comparison.

## Scheduled workflow validation

All four configurations returned `DRY_RUN` successfully and resolved every
configured manifest, credential file, report directory, and log directory.
The absent `data/daily_web_update/run.lock` was expected and confirmed that no
writer held the shared database lock.

| Workflow | Enabled sources |
| --- | ---: |
| China daily | 9 |
| Global daily | 5 |
| China weekly revision | 7 |
| Global weekly revision | 3 |

The four root launchers still call only `scripts/run_with_live_log.py` and
`scripts/run_daily_web_update.py`.

## Fixed-T query validation

Cutoff: `2026-07-31 23:59:59.999999 Asia/Shanghai`; start date: 2005-01-01.

| Scope/frequency | Rows | Fields | Selected cells | Coverage | Latest visible period |
| --- | ---: | ---: | ---: | ---: | --- |
| CN / M | 259 | 55 | 11,839 | 83.1% | 2026-07-31 |
| CN / Q | 87 | 55 | 4,135 | 86.4% | 2026-06-30 |
| US / M | 259 | 18 | 3,575 | 76.7% | 2026-06-30 |
| US / Q | 87 | 18 | 1,529 | 97.6% | 2026-06-30 |
| GLB / M | 259 | 54 | 10,962 | 78.4% | 2026-05-31 |
| GLB / Q | 87 | 54 | 4,405 | 93.8% | 2026-03-31 |

For all six queries, database input and a newly generated 239,942-row effective
PIT long Parquet produced byte-identical values, source periods, and cell
provenance files. The auxiliary metadata source list differs for CN because
the database inventory lists every ingested source while the effective long
table lists sources that produced effective events. The long-input
`selected_long` file also exposes the full 31-column event schema rather than
the compact 14-column database selection schema. These differences do not
change the wide values, periods, or provenance contract.

CN monthly production-data checks returned:

- duplicate selected field-periods: 0;
- rows visible before `available_at`: 0;
- ordinary Wind/SAFE/fallback D selected where an A/B record exists: 0.

## Acceptance gate

The maintained test suite passed: **219 passed**.

The formal acceptance gate passed 16 of 17 checks. Raw archive reproducibility
was 100%, duplicate vintage rows were 0, all 16 required CN series were
populated, and US RTDSM validation remained 100% over 1,500 sampled cells.

The only failing check is `China required sources: 4 / 5`: CUSTOMS has no
official observation in the database because the official CDN currently fails
TLS verification. The strict A/B share is still reported as 48.1%, but is no
longer a hard gate because the production query contract explicitly permits
governed PIT_D only where A/B is absent.

## Remaining production step

Observe the next real China 22:00 and global 00:00 runs, including logs,
DeepSeek reports and email receipts. After that cycle, the remaining business
blocker is the official Customs five-field backfill through reviewed,
browser-saved official files and the existing offline archive workflow.
