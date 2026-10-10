@echo off
rem Claude Talk voice picker.
rem   voice                 interactive picker (double-click this file)
rem   voice list|play|set|show|say ...   one-shot commands for a terminal
setlocal
set PYTHONUTF8=1
rem the project goes first on PYTHONPATH; no empty entry, which Python would read as the current folder
if defined PYTHONPATH set "PYTHONPATH=;%PYTHONPATH%"
set "PYTHONPATH=%~dp0%PYTHONPATH%"
chcp 65001 >nul
rem -P: the folder you run it from never shadows a module
"D:\2files\env_build\conda\conda\python.exe" -P -m claude_talk.cli %*
set RC=%ERRORLEVEL%
rem Double-clicked (no arguments) and Python died early: keep the window so the error is readable.
if "%~1"=="" if not "%RC%"=="0" pause
endlocal & exit /b %RC%
