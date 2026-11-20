@echo off
rem Shared setup: creates .venv and installs packages. Re-runs pip until an install succeeds.
if exist ".venv\installed.ok" exit /b 0
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python was not found. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo then open a new window and try again.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || (echo Could not create the .venv folder. & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (
  echo Installing packages failed. Check your internet connection and run this again.
  exit /b 1
)
echo ok> ".venv\installed.ok"
exit /b 0
