# Reports index

`reports/v2/` contains current operational reports and historical evidence.
Large numbers of files here do not mean they are all part of the daily runtime.

## Current operational entry points

- `STATUS.md`
- `daily_web_update/latest.md`
- `daily_global_update/latest.md`
- `weekly_web_revision/latest.md`
- `weekly_global_revision/latest.md`
- `deepseek_daily_audit/china/latest.md`
- `deepseek_daily_audit/global/latest.md`
- `combined_pit_long/README.md`
- `current_field_inventory/`
- `non_cn_field_inventory/`

## Historical evidence

Directories under `history/archive_parse/`, plus `nbs_*`, `pboc_*`, `pit_*`,
`stage*`, and `wind_batch*`, record completed parsing, backfill, review, or migration work.
They are not scanned by the scheduled runner. They remain useful for tracing a
database row to the work that introduced or reviewed it.

Generated CSV, Parquet, logs, and raw evidence remain local under the existing
ignore rules. Markdown reports are retained in Git because they document data
contracts and decisions.
