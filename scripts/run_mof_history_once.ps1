param(
  [Parameter(Mandatory = $true)]
  [int]$DiscoveryProcessId
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'D:\Macro_Data'
$env:PYTHONPATH = 'D:\Macro_Data\src'

# Do not run two processes against the same government domain. Wait for the
# bounded index discovery process to finish before consuming its merged queue.
while (Get-Process -Id $DiscoveryProcessId -ErrorAction SilentlyContinue) {
  Start-Sleep -Seconds 30
}

$discoveryLog = 'D:\Macro_Data\logs\mof_history_discovery.stdout.log'
if (-not (Test-Path -LiteralPath $discoveryLog) -or
    -not (Select-String -LiteralPath $discoveryLog -Pattern 'Candidate releases:' -Quiet)) {
  throw 'MOF index discovery did not complete successfully; release backfill was not started.'
}

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
