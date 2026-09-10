$ErrorActionPreference = 'Stop'

$projectRoot = 'E:\Macro_Data'
$python = 'C:\Users\71871\AppData\Local\Programs\Python\Python311\python.exe'
$database = Join-Path $projectRoot 'macro_pit_v2.duckdb'
$logFile = Join-Path $projectRoot 'logs\nbs_history_daily.stdout.log'
$batch1 = Join-Path $projectRoot 'config\nbs_release_index_pages1_50.txt'
$batch2 = Join-Path $projectRoot 'config\nbs_release_index_pages51_66.txt'

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
New-Item -ItemType Directory -Path (Split-Path -Parent $logFile) -Force | Out-Null

function Write-RunLog([string]$message) {
  Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("{0} {1}" -f (Get-Date -Format o), $message)
}

function Test-UrlCached([string]$url) {
  $hasher = [Security.Cryptography.SHA256]::Create()
  try {
    $digestBytes = $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($url))
  }
  finally {
    $hasher.Dispose()
  }
  $digest = ([BitConverter]::ToString($digestBytes)).Replace('-', '').ToLowerInvariant()
  $cachePath = Join-Path $projectRoot ("data\http_cache\nbs\{0}.json" -f $digest)
  if (-not (Test-Path -LiteralPath $cachePath -PathType Leaf)) {
    return $false
  }
  try {
    $entry = Get-Content -LiteralPath $cachePath -Raw | ConvertFrom-Json
    $rawPath = [string]$entry.raw_file
    if (-not [IO.Path]::IsPathRooted($rawPath)) {
      $rawPath = Join-Path $projectRoot $rawPath
    }
    return (Test-Path -LiteralPath $rawPath -PathType Leaf)
  }
  catch {
    return $false
  }
}

function Test-ManifestCached([string]$manifest) {
  $urls = Get-Content -LiteralPath $manifest | Where-Object { $_ -and -not $_.TrimStart().StartsWith('#') }
  foreach ($url in $urls) {
    if (-not (Test-UrlCached $url.Trim())) {
      return $false
    }
  }
  return $true
}

function Invoke-MacroPit([string[]]$arguments) {
  $output = & $python @arguments 2>&1
  $exitCode = $LASTEXITCODE
  foreach ($line in $output) {
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ([string]$line)
  }
  if ($exitCode -ne 0) {
    throw "macro_pit exited with code $exitCode"
  }
}

Write-RunLog 'NBS bounded daily run started.'

if (-not (Test-ManifestCached $batch1)) {
  Write-RunLog 'Fetching historical release index pages 1-50.'
  Invoke-MacroPit @(
    '-m', 'macro_pit', '--db-path', $database,
    'discover-index', '--source', 'NBS', '--url-manifest', $batch1, '--allow-network'
  )
  Write-RunLog 'Index batch 1 completed; stopping for today.'
  exit 0
}

$releaseLimit = 300
if (-not (Test-ManifestCached $batch2)) {
  Write-RunLog 'Fetching historical release index pages 51-66.'
  Invoke-MacroPit @(
    '-m', 'macro_pit', '--db-path', $database,
    'discover-index', '--source', 'NBS', '--url-manifest', $batch2, '--allow-network'
  )
  Write-RunLog 'Index batch 2 completed; continuing with the finite release queue.'
}

Write-RunLog ("Historical indexes complete; processing up to {0} release pages." -f $releaseLimit)
Invoke-MacroPit @(
  '-m', 'macro_pit', '--db-path', $database,
  'history-backfill', '--source', 'NBS',
  '--candidates', (Join-Path $projectRoot 'data\discovery\nbs_candidates.parquet'),
  '--start-period', '2005-01',
  '--state-path', (Join-Path $projectRoot 'data\history_backfill\nbs_release_2005_state.json'),
  '--log-path', (Join-Path $projectRoot 'logs\nbs_history_backfill.jsonl'),
  '--max-network-urls', ([string]$releaseLimit), '--allow-network'
)
Write-RunLog 'NBS bounded daily run completed.'
