$ErrorActionPreference = 'Stop'

$projectRoot = 'E:\Macro_Data'
$python = 'C:\Users\71871\AppData\Local\Programs\Python\Python311\python.exe'
$database = Join-Path $projectRoot 'macro_pit_v2.duckdb'
$logFile = Join-Path $projectRoot 'logs\nbs_legacy_search.stdout.log'

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
New-Item -ItemType Directory -Path (Split-Path -Parent $logFile) -Force | Out-Null

Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("{0} NBS legacy search started." -f (Get-Date -Format o))
$output = & $python @(
  '-m', 'macro_pit', '--db-path', $database,
  'discover-nbs-legacy',
  '--term-manifest', (Join-Path $projectRoot 'config\nbs_legacy_search_terms.txt'),
  '--start-date', '2005-01-01',
  '--end-date', '2020-02-29',
  '--state-path', (Join-Path $projectRoot 'data\history_backfill\nbs_legacy_search_state.json'),
  '--output-dir', (Join-Path $projectRoot 'data\discovery\nbs_legacy'),
  '--max-network-pages', '20',
  '--allow-network'
) 2>&1
$exitCode = $LASTEXITCODE
foreach ($line in $output) {
  Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ([string]$line)
}
Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("{0} NBS legacy search exited with code {1}." -f (Get-Date -Format o), $exitCode)
exit $exitCode
