$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\Macro_Data'
$env:PYTHONPATH = 'D:\Macro_Data\src'

# This is a one-time background wait, not a scheduled task. The NBS daily
# budget for 2026-09-03 is already exhausted, so wait until the next local day
# and then until 10:00 before making the single bounded request.
while ((Get-Date).Date -le [datetime]'2026-09-03') {
  Start-Sleep -Seconds 300
}
$runAt = (Get-Date).Date.AddHours(10)
if ((Get-Date) -lt $runAt) {
  Start-Sleep -Seconds ([int][Math]::Ceiling(($runAt - (Get-Date)).TotalSeconds))
}

py -3.11 -m macro_pit --db-path macro_pit_v2.duckdb backfill `
  --scope cn `
  --source NBS `
  --url-manifest config\nbs_easyquery_cpi_history_probe.txt `
  --allow-network
