param(
    [string]$TaskName = "Macro_Data_Daily_Web_Update",
    [string]$At = "22:00"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $Root "run_daily_web_update.cmd"
if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Runner not found: $Runner"
}

$time = [datetime]::ParseExact($At, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$cmd = Join-Path $env:SystemRoot "System32\cmd.exe"
$arguments = '/d /c "' + $Runner + '"'
$action = New-ScheduledTaskAction `
    -Execute $cmd `
    -Argument $arguments `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Daily -At $time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily China official-source macro update: NBS, PBOC, MOF, SAFE and OECD China; Wind excluded." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime

