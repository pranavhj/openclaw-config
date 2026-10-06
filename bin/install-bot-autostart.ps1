#Requires -RunAsAdministrator
<#
install-bot-autostart.ps1 -- start the Discord bot at boot, without anyone logging in (OC-042).

Run ONCE from an elevated PowerShell (Run as administrator):
    powershell -ExecutionPolicy Bypass -File D:\MyData\Software\openclaw-config\bin\install-bot-autostart.ps1
Remove:
    powershell -ExecutionPolicy Bypass -File D:\MyData\Software\openclaw-config\bin\install-bot-autostart.ps1 -Uninstall

Creates Task Scheduler task "OpenclawDiscordBot":
  trigger  : at system startup (+30s delay for networking)
  runs as  : this Windows account, "run whether user is logged on or not" (password stored by
             Task Scheduler, so ~/.claude login, PATH and settings are available)
  action   : bin\run-bot.cmd (restart loop, logs to %LOCALAPPDATA%\openclaw\bot.log)
  limits   : no execution time limit; restarted by Task Scheduler if it fails to start
Also disables the broken NSSM service "discord-bot" (OC-027) so the two can never race.

PASSWORD: this account is a Microsoft account. Enter the MICROSOFT ACCOUNT password,
not the Windows Hello PIN. A wrong/PIN password is what caused the NSSM logon failure.
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'  # never continue past a failed step (2026-10-05: a failed
                                 # registration went on to stop the running bot)
$TaskName = 'OpenclawDiscordBot'
$Wrapper  = 'D:\MyData\Software\openclaw-config\bin\run-bot.cmd'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task $TaskName"
    return
}

if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }

$user = "$env:COMPUTERNAME\$env:USERNAME"

$action   = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$Wrapper`"" -WorkingDirectory $env:USERPROFILE
$trigger  = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
              -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
              -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

$registered = $false
for ($attempt = 1; $attempt -le 3 -and -not $registered; $attempt++) {
    $cred = Get-Credential -UserName $user -Message "Attempt $attempt/3: password for $user (Microsoft account password, NOT your PIN)"
    if (-not $cred) { throw 'No credentials entered - nothing was changed.' }
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
            -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
        $registered = $true
    } catch {
        Write-Warning "Registration failed: $($_.Exception.Message)"
    }
}
if (-not $registered) {
    throw 'Could not register the task (wrong user name or password). Nothing else was changed; the running bot was not touched.'
}
Write-Host "Registered task $TaskName (runs at startup as $($cred.UserName))"

# Retire the broken NSSM service so it can never start a second bot.
sc.exe config discord-bot start= disabled | Out-Null
Write-Host 'NSSM service discord-bot set to Disabled'

# Replace any manually started bot (and run-bot.cmd loop) with the task-managed one.
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -like '*run-bot.cmd*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped manual run-bot loop pid $($_.ProcessId)" }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*discord-bot.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped manual bot pid $($_.ProcessId)" }
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 20

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Task state: $((Get-ScheduledTask -TaskName $TaskName).State)  last result: $($info.LastTaskResult)"
Write-Host 'Last bot.log lines:'
Get-Content "$env:LOCALAPPDATA\openclaw\bot.log" -Tail 5
