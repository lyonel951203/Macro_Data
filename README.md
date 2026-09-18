# Global Macro PIT Database

Append-only DuckDB/Parquet pipeline for point-in-time macroeconomic data. The
project treats an official publication timestamp and a reproducible raw file as
part of every strict-PIT observation.

## Repository contents and local data

This repository contains source code, configuration, tests, documentation, and
small frozen task manifests. The `data/` directory, DuckDB databases and backups,
logs, runtime checkpoints, caches, and generated data reports remain local and
are excluded by `.gitignore`. A clone does not include the existing dataset or
the archived evidence needed to reproduce historical ingestion receipts.

For a new environment, install the package from the project root:

```powershell
py -3.11 -m pip install -e .
py -3.11 -m macro_pit --help
```

Restore your own local databases and `data/` archive separately when continuing
an existing collection. Historical one-off scripts and background launchers can
also require generated local checkpoints and validation reports; consult the
script's documented prerequisites before running them on a fresh clone.

## Install

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 -m macro_pit --help
```

## Safe operating model for China official sources

Network access is disabled by default. Live runs require a short, reviewed URL
manifest and the explicit `--allow-network` flag. The HTTP client is
single-threaded, cache-first, respects `robots.txt`, uses conditional requests,
applies source-specific 30-90 second pacing, and has per-run/per-day budgets.
HTTP 401/403/407/429 opens the circuit immediately and is never retried.

Do not run multiple Macro PIT processes against the same official domain. Do
not use proxy rotation, browser fingerprint spoofing, CAPTCHA bypass, or broad
automatic pagination.

Example bounded manifest:

```text
# urls_pboc.txt
http://www.pbc.gov.cn/example/official-release.html
```

```powershell
py -3.11 -m macro_pit backfill `
  --scope cn `
  --source PBOC `
  --url-manifest .\urls_pboc.txt `
  --allow-network
```

Run the first live request with a one-URL manifest. Inspect `crawl_log`, the raw
file and parser output before adding more URLs.

## Offline commands

```powershell
py -3.11 -m macro_pit discover
py -3.11 -m macro_pit archive-manual --source PBOC `
  --input-dir data\manual_inbox\pboc `
  --manifest-output config\pboc_manual_inbox_raw.yml
py -3.11 -m macro_pit snapshot --country CN --as-of "2025-02-14 17:00:00+08:00"
py -3.11 -m macro_pit export-monthly --country CN
py -3.11 -m macro_pit --db-path macro_pit_v2.duckdb export-wide `
  --country CN --pit-mode strict `
  --start-date 2005-01-31 --end-date 2026-07-31 `
  --output-prefix data\exports\cn_pit_month_end_2005_20260731
py -3.11 -m macro_pit audit
py -3.11 -m macro_pit acceptance
```

`export-wide` writes a values panel, a companion source-period panel, and an
indicator metadata table. Each row is a natural month end; each value is the
latest observation legally available at that month-end timestamp.

For a fixed information cutoff `T`, use `query-wide`. It returns one natural
month-end row per month from 2005 through the month containing `T`, keeps every
field in the requested scope, and leaves periods that were not yet published at
`T` empty. Base values follow `PIT_A` -> `PIT_B` -> delayed-availability Wind.
The approved IMF all-commodity proxy remains `PIT_D` in the database and enters
the GLB research view only after its documented 40-day conservative lag; later
web revisions take effect from their first observed date. Documented Wind
revisions likewise take effect only from their dated revision event.
Use --frequency M for month ends or --frequency Q for quarter ends; Q keeps
quarter-end months and does not aggregate monthly data.

```powershell
py -3.11 -m macro_pit query-wide --as-of 2026-07-31 --scope CN --frequency M
py -3.11 -m macro_pit query-wide --as-of 2026-07-31 --scope CN --frequency Q
py -3.11 -m macro_pit query-wide --as-of 2026-07-31 --scope US --frequency M
py -3.11 -m macro_pit query-wide --as-of 2026-07-31 --scope GLB --frequency M

# Rebuild the same fixed-T output directly from the effective-event Parquet.
py -3.11 -m macro_pit query-wide --long-parquet data\exports\cn_pit_long_from_2005-01-01.parquet --as-of 2026-07-31 --scope CN --frequency Q
```

With `--long-parquet`, the command reads the embedded `valid_from`/`valid_to`
intervals and does not open DuckDB or the Wind availability sidecar. Without the
option, the existing database-backed behavior is unchanged.

The command writes values, source periods, cell provenance, field metadata,
selected long-form observations, and a JSON query receipt under `data/queries/`.
See `reports/v2/asof_query/README.md` for the full contract and validation.

To export the complete effective PIT history once, without looping over T or
M/Q, use export-long. The output prefix is stable and repeated runs refresh the
same CSV, Parquet, and JSON receipt.

~~~powershell
py -3.11 -m macro_pit export-long --scope CN --start-date 2005-01-01
.\export_pit_long.cmd CN 2005-01-01
~~~

Each row carries source_frequency, period_end, value, valid_from, valid_to,
selection origin, and raw evidence fields. See
reports/v2/asof_query/LONG_EXPORT.md for the interval contract.

`archive-manual` is the governed fallback for official pages saved in a normal
browser when automated access is disallowed. It preserves the original file,
copies verified bytes into the SHA archive, and writes a raw manifest for a
separate offline `backfill-raw` run.

The official OECD STES revisions dataset supplies two supplemental China PIT_B
series in `config/oecd_china_core.yml`: CPI and industrial production. They use
the provider's edition month, retain source `OECD`, and do not replace the
required domestic NBS series. The China unemployment series is unavailable in
that query, and the STES revision GDP query returns 404. A misleading China
retail result was removed after its values contradicted the declared index
unit; its raw CSV and repair backup remain archived.

US RTDSM and OECD use reviewed YAML job manifests rather than broad automatic
downloads. Start from `config/rtdsm_jobs.example.yml` and
`config/oecd_jobs.example.yml`. OECD jobs must be filtered by country and
indicator; unfiltered dataset downloads are intentionally unsupported.

The 00:00 global task also downloads the official IMF `external-data.xlsx`
workbook and maintains `GLB_IMF_ALL_COMMODITY_PRICE_INDEX` (PALLFNF, monthly,
2016=100). Its current-history rows are archived as `PIT_D`; query-wide and
export-long apply the approved estimated visibility rule without relabeling the
evidence grade. The first live load added 560 months from 1980-01 through
2026-08, and a cached replay returned 560 unchanged rows.

Three China market factors are implemented from the public ChinaBond curve
history: `CN_CGB_YTM_10Y`, `CN_CGB_TERM_SPREAD_10Y_1Y`, and
`CN_AAA_CP_NOTE_CREDIT_SPREAD_3Y`. Each closed month uses the final trading-day
curve and the documented 17:30 Beijing publication time. The 00:00 unattended
task is enabled. A user-authorized policy continues only when robots.txt cannot
be retrieved; an explicit Disallow response still blocks access. The initial
backfill completed with 716 rows and zero parse errors.

`discover` does not invent historical start dates. Unverified coverage remains
`UNVERIFIED` until a bounded discovery run supplies evidence.

The required acceptance scope is China and the United States. OECD/global data
is retained as an optional extension and is reported separately, but it does
not block `OVERALL`.

## One-time China history backfill

Long official time-series tables and original release archives are deliberately
kept as two evidence layers:

- Official bulk/current-history tables are archived and loaded as `PIT_D`.
  They are suitable for long descriptive series, but not for strict historical
  as-of snapshots.
- Original dated releases remain `PIT_A` or `PIT_B` and are the only China rows
  included by `pit_mode=strict`.

SAFE bulk workbooks are listed in `config/safe_fx_reserve_bulk_files.txt` and
`config/safe_bulk_flow_files.txt`. Once archived, they can be parsed again
without network access:

```powershell
py -3.11 -m macro_pit --db-path macro_pit_v2.duckdb backfill-raw `
  --source SAFE `
  --raw-manifest config\safe_bulk_raw.yml
```

The PBOC annual money-supply table URLs are recorded in
`config/pboc_money_supply_history_2004_2026.txt`, but PBOC currently disallows
their statistics paths in `robots.txt`. The automated client must not fetch
that manifest. Browser-saved official pages can instead be archived through the
manual inbox and parsed as `CN_M0_STOCK`, `CN_M1_STOCK`, and `CN_M2_STOCK`, all
with `PIT_D` evidence. No Selenium, proxy rotation, or browser-fingerprint
automation is required or permitted.

The unattended China update therefore keeps the direct PBOC adapter at
`BLOCKED_POLICY` and uses `PBOC_MIRROR` as a separate fallback. It scans the
reviewed Shanghai, Jilin, and Qingdao government reprint indexes, preserves the
reprint URL and publication evidence, and writes the underlying observations as
source `PBOC` with grade `B`. A page must be an unambiguous national financial
statistics report and contain all ten core PBOC fields; local financial reports
are rejected. The mirror configuration is
`config/pboc_mirror_index_urls.txt`.

The 22:00 China task also observes reviewed Sina and Eastmoney current-history
APIs every day. These are query fallbacks, not substitutes for official
evidence. Only 19 verified canonical fields are mapped; every row remains
`PIT_D`, becomes visible at its archived `first_seen_at`, and retains the raw
response hash. Fixed-T selection uses `PIT_A > PIT_B > WIND > EASTMONEY_D >
SINA_D`. The adapters request only the latest three periods, so they establish
future first-seen availability without pretending to reconstruct historical
release dates.

For a reviewed release-candidate parquet, the one-time worker can run in the
background and carry its own checkpoint across calendar days:

```powershell
py -3.11 -m macro_pit --db-path macro_pit_v2.duckdb history-backfill `
  --source MOF `
  --candidates data\discovery\mof_candidates.parquet `
  --start-period 2005-01 `
  --state-path data\history_backfill\mof_2005_state.json `
  --log-path logs\mof_history_backfill.jsonl `
  --max-network-urls 15 `
  --wait-across-days `
  --resume-hour 10 `
  --allow-network
```

This is a single resumable process, not a scheduled task. It releases the
database before waiting for the next day. Cached URLs do not consume the daily
network batch. Parser errors are checkpointed without retrying the URL, and any
HTTP 401/403/407/429 stops the process instead of attempting a workaround.

## PIT grades

- `A`: original official value and exact official release timestamp.
- `B`: original official value and release date only; available next local day
  at 00:00.
- `C`: release date exists but the original vintage cannot be proven; excluded
  from strict snapshots.
- `D`: only the current/final value is observable; available from
  `first_seen_at` and excluded from strict/loose snapshots.

The legacy `macro_pit.duckdb` predates these contracts. Treat its rows as
untrusted until they are rebuilt from linked raw artifacts and pass
`acceptance`.
