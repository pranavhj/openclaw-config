@echo off
rem run-gateway.cmd -- keep llm-gateway.py (triage, port 18789) running (OC-044).
rem Started by run-bot.cmd, so the "OpenclawDiscordBot" boot task covers both processes.
rem Restarts the gateway 15s after it exits; appends all output to %LOCALAPPDATA%\openclaw\llm-gateway-service.log.

set "LOGDIR=%LOCALAPPDATA%\openclaw"
set "LOG=%LOGDIR%\llm-gateway-service.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:loop
rem rotate the log at ~5 MB
for %%F in ("%LOG%") do if %%~zF GTR 5000000 move /y "%LOG%" "%LOG%.1" > nul
echo [%date% %time%] run-gateway: starting llm-gateway.py>> "%LOG%"
"C:\Python310\python.exe" "D:\MyData\Software\openclaw-config\bin\llm-gateway.py" >> "%LOG%" 2>&1
echo [%date% %time%] run-gateway: llm-gateway.py exited with code %errorlevel%, restarting in 15s>> "%LOG%"
rem ping instead of timeout: timeout fails when there is no console (task runs without login)
ping -n 16 127.0.0.1 > nul
goto loop
