#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Manage the openclaw discord-bot NSSM service.

.DESCRIPTION
    Configures and controls the discord-bot Windows service via NSSM.
    Must be run as Administrator.

.PARAMETER Action
    What to do: install | start | stop | restart | status | uninstall
    Default: restart

.EXAMPLE
    .\manage-service.ps1              # restart (default)
    .\manage-service.ps1 install      # install + start fresh
    .\manage-service.ps1 status       # show current status
    .\manage-service.ps1 stop         # stop only
    .\manage-service.ps1 restart      # apply env changes + restart
#>

param(
    [ValidateSet('install','start','stop','restart','status','uninstall','grant-user')]
    [string]$Action = 'restart'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Paths ──────────────────────────────────────────────────────────────────────
$Nssm        = "C:\Users\prana\bin\nssm.exe"
$Python      = "C:\Python310\python.exe"
$BotScript   = "D:\MyData\Software\openclaw-config\bin\discord-bot.py"
$LogDir      = "C:\Users\prana\AppData\Local\openclaw"
$LogFile     = "$LogDir\bot.log"
$ServiceName = "discord-bot"

$ClaudeDir   = "C:\Users\prana\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe"
# NSSM AppEnvironmentExtra is a REG_MULTI_SZ — each var must be a separate array entry
$ExtraEnv    = @(
    "USERPROFILE=C:\Users\prana",
    "HOMEPATH=\Users\prana",
    "HOMEDRIVE=C:",
    "LOCALAPPDATA=C:\Users\prana\AppData\Local",
    "PATH=$ClaudeDir;C:\Python310;C:\Windows\System32;C:\Windows"
)

# ── Helpers ────────────────────────────────────────────────────────────────────
function Nssm { & $Nssm @args }

function Apply-Config {
    Write-Host "Configuring $ServiceName..."
    Nssm set $ServiceName Application      $Python
    Nssm set $ServiceName AppParameters    $BotScript
    Nssm set $ServiceName AppDirectory     "C:\Users\prana"
    Nssm set $ServiceName AppStdout        $LogFile
    Nssm set $ServiceName AppStderr        $LogFile
    Nssm set $ServiceName AppRotateFiles   1
    Nssm set $ServiceName AppRotateOnline  1
    Nssm set $ServiceName AppRotateBytes   5000000
    Nssm set $ServiceName Start            SERVICE_AUTO_START
    # AppEnvironmentExtra is REG_MULTI_SZ — write directly to registry
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
    Set-ItemProperty -Path $regPath -Name AppEnvironmentExtra -Value $ExtraEnv -Type MultiString
    Write-Host "Config applied."
}

function Show-Status {
    Write-Host ""
    Write-Host "=== Service status ==="
    Nssm status $ServiceName
    Write-Host ""
    Write-Host "=== Last 10 log lines ==="
    if (Test-Path $LogFile) {
        Get-Content $LogFile -Tail 10
    } else {
        Write-Host "(no log file yet)"
    }
}

# ── Actions ────────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

switch ($Action) {

    'install' {
        Write-Host "Installing $ServiceName..."
        Nssm install $ServiceName $Python $BotScript
        Apply-Config
        Nssm start $ServiceName
        Write-Host "Installed and started."
        Show-Status
    }

    'start' {
        Nssm start $ServiceName
        Write-Host "Started."
        Show-Status
    }

    'stop' {
        Nssm stop $ServiceName
        Write-Host "Stopped."
    }

    'restart' {
        Write-Host "Applying config and restarting $ServiceName..."
        Apply-Config
        Nssm restart $ServiceName
        Write-Host "Restarted."
        Show-Status
    }

    'status' {
        Show-Status
    }

    'uninstall' {
        Write-Host "Stopping and removing $ServiceName..."
        Nssm stop  $ServiceName
        Nssm remove $ServiceName confirm
        Write-Host "Uninstalled."
    }

    'grant-user' {
        # Modify the service DACL so the current user can start/stop/restart
        # discord-bot without admin elevation. One-time setup.
        $User = $env:USERNAME
        $Sid  = ([System.Security.Principal.NTAccount]$User).Translate(
                    [System.Security.Principal.SecurityIdentifier]).Value

        Write-Host "Granting '$User' ($Sid) start/stop rights on '$ServiceName'..."

        # Read current SDDL (sc sdshow returns multiple lines; grab the D: line)
        $RawSddl = & sc.exe sdshow $ServiceName
        $Sddl    = ($RawSddl | Where-Object { $_ -match 'D:' }) -replace '^\s+', ''

        if (-not $Sddl) {
            Write-Error "Could not read SDDL for $ServiceName - is the service installed?"
            exit 1
        }

        # ACE: query_config (CC), query_status (LC), enum_deps (SW),
        #      start (RP), stop (WP), pause_continue (DT), interrogate (LO),
        #      user_defined (CR), read_control (RC)
        $Ace = "(A;;CCLCSWRPWPDTLOCRRC;;;$Sid)"

        if ($Sddl -match [regex]::Escape($Ace)) {
            Write-Host "ACE already present - '$User' already has service control rights."
            exit 0
        }

        $NewSddl = $Sddl -replace 'D:', "D:$Ace"
        $Result  = & sc.exe sdset $ServiceName $NewSddl
        Write-Host $Result
        Write-Host ""
        Write-Host "Done. '$User' can now restart '$ServiceName' without admin elevation."
        Write-Host "Run: python D:\MyData\Software\openclaw-config\bin\restart-bot.py"
    }
}
