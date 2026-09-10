$ErrorActionPreference = 'Stop'
$projectRoot = 'E:\Macro_Data'
$pythonExe = 'C:\Users\71871\AppData\Local\Programs\Python\Python311\python.exe'
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$env:PYTHONIOENCODING = 'utf-8'
$out = Join-Path $projectRoot 'reports\v2\pit_history_autorun'
$lockPath = Join-Path $projectRoot 'data\history_backfill\nbs_price_batch.lock'
$stopPath = Join-Path $projectRoot 'data\history_backfill\pit_history_autorun.stop'
if (Test-Path -LiteralPath $lockPath) { throw 'An NBS worker lock exists; inspect it before starting another worker.' }
if (Test-Path -LiteralPath $stopPath) { throw 'A stop marker exists; remove it only when intentionally resuming.' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$worker = Start-Process -FilePath $pythonExe -ArgumentList @('-u','scripts/run_pit_history_autorun.py','--allow-network') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $out "$stamp.stdout.log") -RedirectStandardError (Join-Path $out "$stamp.stderr.log") -PassThru
Write-Output "Started hidden PIT history worker PID=$($worker.Id); logs=$out"
