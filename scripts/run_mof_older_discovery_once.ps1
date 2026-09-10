$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\Macro_Data'
$env:PYTHONPATH = 'D:\Macro_Data\src'

# One-time wait only. Run before the history worker's 10:00 daily resume so the
# same official domain is never accessed by two project processes at once.
while ((Get-Date).Date -le [datetime]'2026-09-03') {
  Start-Sleep -Seconds 300
}
$runAt = (Get-Date).Date.AddHours(8)
if ((Get-Date) -lt $runAt) {
  Start-Sleep -Seconds ([int][Math]::Ceiling(($runAt - (Get-Date)).TotalSeconds))
}

py -3.11 -m macro_pit --db-path macro_pit_v2.duckdb discover-index `
  --source MOF `
  --url-manifest config\mof_index_pages21_26.txt `
  --allow-network
