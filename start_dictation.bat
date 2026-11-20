@echo off
cd /d "%~dp0"
call setup_env.bat || (pause & exit /b 1)
".venv\Scripts\python.exe" -m vaani.dictation
pause
