@echo off
rem Claude Talk voice picker.
rem   voice                 interactive picker (double-click this file)
rem   voice list|play|set|show|say ...   one-shot commands for a terminal
setlocal
set PYTHONUTF8=1
chcp 65001 >nul
"D:\2files\env_build\conda\conda\python.exe" "%~dp0voice.py" %*
set RC=%ERRORLEVEL%
rem Double-clicked (no arguments) and Python died early: keep the window so the error is readable.
if "%~1"=="" if not "%RC%"=="0" pause
endlocal & exit /b %RC%
