param(
    [string]$TaskName = "LocalAI Desktop Scheduler",
    [int]$IntervalSeconds = 30
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Pythonw)) {
    throw "LocalAI virtualenv pythonw.exe not found: $Pythonw"
}

$User = "$env:USERDOMAIN\$env:USERNAME"
$Argument = "-m app.scheduler_runner --loop --interval $IntervalSeconds"

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument $Argument -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Runs LocalAI Desktop scheduled tasks while the user session is active."

Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Registered and started: $TaskName"
