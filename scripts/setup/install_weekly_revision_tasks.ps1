param(
    [string]$WebTaskName = "Macro_Data_Weekly_Web_Revision",
    [string]$GlobalTaskName = "Macro_Data_Weekly_Global_Revision",
    [string]$DayOfWeek = "Sunday",
    [string]$WebAt = "02:00",
    [string]$GlobalAt = "04:00"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$cmd = Join-Path $env:SystemRoot "System32\cmd.exe"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$definitions = @(
    @{
        Name = $WebTaskName
        Runner = Join-Path $Root "run_weekly_web_revision.cmd"
        At = $WebAt
        Description = "Weekly China macro revision audit: latest three official pages, full OECD China revisions and PBOC robots-policy probe."
    },
    @{
        Name = $GlobalTaskName
        Runner = Join-Path $Root "run_weekly_global_revision.cmd"
        At = $GlobalAt
        Description = "Weekly complete OECD and RTDSM macro revision audit; waits for the shared database lock."
    }
)

foreach ($definition in $definitions) {
    if (-not (Test-Path -LiteralPath $definition.Runner)) {
        throw "Runner not found: $($definition.Runner)"
    }
    $time = [datetime]::ParseExact($definition.At, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $time
    $arguments = '/d /c "' + $definition.Runner + '"'
    $action = New-ScheduledTaskAction -Execute $cmd -Argument $arguments -WorkingDirectory $Root
    Register-ScheduledTask `
        -TaskName $definition.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $definition.Description `
        -Force | Out-Null
}

Get-ScheduledTask -TaskName $WebTaskName,$GlobalTaskName | Select-Object TaskName, State
$WebTaskName,$GlobalTaskName | ForEach-Object { $name = $_; $info = Get-ScheduledTaskInfo -TaskName $name; [pscustomobject]@{ TaskName = $name; LastRunTime = $info.LastRunTime; LastTaskResult = $info.LastTaskResult; NextRunTime = $info.NextRunTime } }


