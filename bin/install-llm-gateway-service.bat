@echo off
:: Run this as Administrator to install llm-gateway as a Windows service via NSSM.
:: It will auto-restart on crash with a 5-second delay.

set NSSM=C:\Users\prana\bin\nssm.exe
set PYTHON=C:\Python310\python.exe
set SCRIPT=D:\MyData\Software\openclaw-config\bin\llm-gateway.py
set LOGDIR=%LOCALAPPDATA%\openclaw
set SERVICE=llm-gateway

echo Installing llm-gateway as Windows service...

:: Remove existing if present
%NSSM% stop %SERVICE% 2>nul
%NSSM% remove %SERVICE% confirm 2>nul

:: Install
%NSSM% install %SERVICE% "%PYTHON%" "%SCRIPT%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: NSSM install failed. Are you running as Administrator?
    pause
    exit /b 1
)

:: Working directory
%NSSM% set %SERVICE% AppDirectory D:\MyData\Software\openclaw-config\bin

:: Restart on crash: 5s delay, unlimited restarts
%NSSM% set %SERVICE% AppExit Default Restart
%NSSM% set %SERVICE% AppRestartDelay 5000

:: Throttle: if process dies within 1500ms of start, wait 30s before retry
%NSSM% set %SERVICE% AppThrottle 1500

:: Log stdout/stderr to file
mkdir "%LOGDIR%" 2>nul
%NSSM% set %SERVICE% AppStdout "%LOGDIR%\llm-gateway-service.log"
%NSSM% set %SERVICE% AppStderr "%LOGDIR%\llm-gateway-service.log"
%NSSM% set %SERVICE% AppStdoutCreationDisposition 4
%NSSM% set %SERVICE% AppStderrCreationDisposition 4
%NSSM% set %SERVICE% AppRotateFiles 1
%NSSM% set %SERVICE% AppRotateBytes 5242880

:: Start automatically
%NSSM% set %SERVICE% Start SERVICE_AUTO_START

:: Start now
%NSSM% start %SERVICE%
if %ERRORLEVEL% neq 0 (
    echo ERROR: Service failed to start. Check logs at %LOGDIR%\llm-gateway-service.log
    pause
    exit /b 1
)

echo.
echo llm-gateway service installed and started.
echo It will auto-restart within 5 seconds if it crashes.
echo Logs: %LOGDIR%\llm-gateway-service.log
echo.
echo To check status: nssm status llm-gateway
echo To stop: nssm stop llm-gateway
echo To uninstall: nssm remove llm-gateway confirm
pause
