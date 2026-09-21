# Daily Sina and Eastmoney PIT_D fallback validation

Validated: 2026-09-17 (Asia/Shanghai).

## Contract

- Both sources are polled by the 22:00 China task every day, even when the official source succeeds. This records the earliest observation time available to this project.
- Only the latest three periods are requested and archived. No old release timestamp is inferred.
- Every accepted row is `PIT_D`, with `available_at = first_seen_at` and `release_date_source = third_party_current_history_first_seen_only`.
- Fixed-T and long-table selection priority is `PIT_A > PIT_B > WIND > EASTMONEY_D > SINA_D`.
- A later official A/B observation automatically supersedes a fallback; existing A/B/Wind values are never overwritten.

## Reviewed coverage

- Sina: 16 fields.
- Eastmoney: 11 fields.
- Overlap: 8 fields.
- Union: 19 of the 50 automatically refreshed China fields.

Excluded mappings include cumulative-versus-single-quarter GDP, Eastmoney monthly-versus-YTD investment, inconsistent new-loan totals, stale series, derived balances, and fields without the required definition.

## Initial live ingestion

| Source | API requests | Fields | Rows | Parse errors | Grade |
|---|---:|---:|---:|---:|---|
| EASTMONEY_MACRO | 8 | 11 | 33 | 0 | D |
| SINA_MACRO | 8 | 16 | 48 | 0 | D |

All rows cover the latest three available periods for their field. Raw responses are under `data/raw/eastmoney_macro/` and `data/raw/sina_macro/`; pipeline logs are under `logs/daily_web_update/`.

## Query validation

The formal CN query for `T=2026-09-17` generated four rows and 55 fields. Its 151 selected cells were 104 `PIT_A`, 32 `PIT_B`, and 15 `WIND`; no fallback D was selected because higher-priority evidence already existed. The synthetic failure test separately proves Sina-only fallback, Eastmoney-over-Sina, and automatic transitions to Wind, B, and A.

Artifacts use the prefix `cn_20260917` in this directory. Full suite: 254 tests passed.
