@echo off
rem run-bot.cmd -- keep discord-bot.py running (OC-042).
rem Started at boot by Task Scheduler task "OpenclawDiscordBot" (see install-bot-autostart.ps1).
rem Restarts the bot 15s after it exits; appends all output to %LOCALAPPDATA%\openclaw\bot.log.

set "LOGDIR=%LOCALAPPDATA%\openclaw"
set "LOG=%LOGDIR%\bot.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:loop
rem rotate bot.log at ~5 MB
for %%F in ("%LOG%") do if %%~zF GTR 5000000 move /y "%LOG%" "%LOG%.1" > nul
echo [%date% %time%] run-bot: starting discord-bot.py>> "%LOG%"
"C:\Python310\python.exe" "D:\MyData\Software\openclaw-config\bin\discord-bot.py" >> "%LOG%" 2>&1
echo [%date% %time%] run-bot: discord-bot.py exited with code %errorlevel%, restarting in 15s>> "%LOG%"
rem ping instead of timeout: timeout fails when there is no console (task runs without login)
ping -n 16 127.0.0.1 > nul
goto loop
