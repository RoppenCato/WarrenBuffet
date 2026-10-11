# Registers the hourly pull as a Windows scheduled task for the current user.
#   powershell -ExecutionPolicy Bypass -File tools\register-pull.ps1
# It runs python -m pipeline.pull at 7 minutes past every hour while you are logged on, with
# pythonw so no console window flashes up. One line per run goes to data\pull.log.
# Remove it again with:  Unregister-ScheduledTask -TaskName "ForeverAH pull" -Confirm:$false

$repo = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute (Join-Path $repo ".venv\Scripts\pythonw.exe") `
    -Argument "-m pipeline.pull" -WorkingDirectory $repo
$start = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes(7)
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 1)
# StartWhenAvailable: a run missed while the PC slept happens once it wakes.
# Priority 6: below-normal CPU but normal disk priority. The default (7) also lowers disk
# priority, and the very first run under it sat for over a minute without getting anywhere.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -Priority 6
Register-ScheduledTask -TaskName "ForeverAH pull" -Action $action -Trigger $trigger -Settings $settings `
    -Description "ForeverAH: hourly AHledger price tables and Wowhead news into C:\dev\WarrenBuffet\data" -Force
