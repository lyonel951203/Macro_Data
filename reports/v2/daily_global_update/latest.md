# Daily macro update - 2026-09-18T00:13:35.680056+08:00

Overall: **PARTIAL**. Wind is excluded; reviewed third-party fallbacks remain PIT_D.

| Source | Status | Discovered | Baseline skipped | Carried pending | Deferred | Selected | Inserted | Revisions | Unchanged | Parse errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OECD | PARTIAL | 34 | 0 | 0 | 0 | 34 | 0 | 0 | 2079 | 2 |
| RTDSM | SUCCESS_NO_CHANGE | 15 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0 |
| CHINABOND | SUCCESS_NO_CHANGE | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 9 | 0 |
| IMF | SUCCESS_NO_CHANGE | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

Each run archives source response bytes and uses append-only, idempotent ingestion. Parser failures remain pending in durable state and are retried even after their URL leaves the current index.

## OECD errors
- oecd_core_part2.yml: https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0/IND.Q.B1GQ_Q.XDC._T.?dimensionAtObservation=AllDimensions&startPeriod=2025-03: HTTPStatusError: Client error '404 Not Found' for url 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0/IND.Q.B1GQ_Q.XDC._T.?dimensionAtObservation=AllDimensions&startPeriod=2025-03'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- oecd_core_part2.yml: https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0/IND.M.PRVM+TOVM.IX.BTE+G47.?dimensionAtObservation=AllDimensions&startPeriod=2025-03: HTTPStatusError: Client error '404 Not Found' for url 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0/IND.M.PRVM+TOVM.IX.BTE+G47.?dimensionAtObservation=AllDimensions&startPeriod=2025-03'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
