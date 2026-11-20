@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
call setup_env.bat || (pause & exit /b 1)

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
".venv\Scripts\python.exe" -m vaani.transcribe "!SRC!"
pause
