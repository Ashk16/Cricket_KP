# Registers a daily 1:00 AM (local / IST) Windows task for historical ingest.
# Runs even if Cursor is closed. Wakes the PC from sleep when Windows allows it.
# If the machine was off at 1 AM, the task runs at the next power-on (StartWhenAvailable).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\install_nightly_task.ps1
#
# Remove:
#   Unregister-ScheduledTask -TaskName "KP Cricket Nightly Backfill" -Confirm:$false

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$script = Join-Path $root "run_nightly_backfill.py"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument ("`"{0}`" --once" -f $script) `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At 1:00AM

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName "KP Cricket Nightly Backfill" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Ingest finished cricket matches into kp_cricket.db at 1:00 AM IST" `
    -Force | Out-Null

Write-Host "Scheduled daily 01:00 local for $env:USERNAME"
Write-Host "  python: $python"
Write-Host "  script: $script --once"
Write-Host "  cwd:    $root"
Write-Host "  log:    $(Join-Path $root 'data\nightly_backfill.log')"
