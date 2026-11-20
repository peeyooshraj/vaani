@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)

set "SRC="
set /p "SRC=Paste a YouTube link or drag an audio file here: "
if not defined SRC (
  echo No link or file given.
  pause
  exit /b 1
)
rem Remove quotes added by drag-and-drop, then pass the value as ONE quoted argument.
rem Delayed expansion (!SRC!) keeps & | ^ in YouTube links from being run as commands.
set "SRC=!SRC:"=!"
.venv\Scripts\python -m vaani.transcribe "!SRC!"
pause
