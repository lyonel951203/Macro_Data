$ErrorActionPreference = 'Stop'
$root = 'E:\Macro_Data'
$logDir = Join-Path $root 'reports\v2\oecd_offvpn_probe'
$python = 'C:\Users\71871\AppData\Local\Programs\Python\Python311\python.exe'
$probe = Join-Path $root 'scripts\one_off\2026-09-21\probe_oecd_offvpn_20260921.py'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$launcherLog = Join-Path $logDir 'launcher.log'
$stdoutPath = Join-Path $logDir 'stdout.log'
$stderrPath = Join-Path $logDir 'stderr.log'
"START $(Get-Date -Format o)" | Add-Content -LiteralPath $launcherLog -Encoding UTF8
Set-Location -LiteralPath $root
try {
    & $python -u $probe 1>> $stdoutPath 2>> $stderrPath
    $resultCode = $LASTEXITCODE
} catch {
    $_ | Out-String | Add-Content -LiteralPath $stderrPath -Encoding UTF8
    $resultCode = 2
}
"END $(Get-Date -Format o) EXIT_CODE=$resultCode" | Add-Content -LiteralPath $launcherLog -Encoding UTF8
exit $resultCode
