# Configuration guide

The directory contains both live production configuration and frozen manifests
from historical backfills. File names alone do not imply that a manifest is
still scheduled.

## Scheduled configurations

- `daily_web_update.yml`
- `daily_global_update.yml`
- `weekly_web_revision.yml`
- `weekly_global_revision.yml`

These reference the active source manifests:

- `daily_nbs_index_urls.txt`
- `pboc_index_urls.txt`
- `pboc_mirror_index_urls.txt`
- `customs_english_index_urls.txt`
- `daily_mof_index_urls.txt`
- `weekly_mof_index_urls.txt`
- `daily_safe_index_urls.txt`
- `oecd_china_core.yml`
- `oecd_core_part1.yml`
- `oecd_core_part2.yml`
- `rtdsm_core.yml`

## Shared production contracts

- `sources.yml` — source policy and network settings.
- `series_registry.yml` — canonical series registry; `active: false` retires a
  field from user-facing queries and exports without deleting historical rows.
- `estimated_availability_rules_v1.csv` — virtual publication rules.
- `estimated_availability_overrides_v1.csv` — reviewed row-level overrides.
- `acceptance.yml` — acceptance thresholds.
- `wind_mcp_mappings.csv` — reviewed Wind import mappings; Wind is not called
  by the unattended web tasks.

## Historical and diagnostic manifests

Completed manifests containing names such as `batch`, `probe`, `candidate`,
`review`, `expected`, or `validation` are grouped by source under `history/`.
They remain evidence for one-time backfill and diagnostic work. Do not add one
to a scheduled configuration without a fresh review.

Historical script defaults and report references were updated when these files
were moved. The supported production and offline configurations listed above
remain directly under `config/`.
