@echo off
rem Double-click to open the grindcap control window.
rem Runs from this folder so config.yaml and snapshots\ are found.
cd /d "%~dp0"
if not exist ".venv\Scripts\grindcap-gui.exe" (
  echo No .venv found in %~dp0
  echo Set it up once: python -m venv .venv ^&^& .venv\Scripts\pip install -e .[ocr,dev]
  pause
  exit /b 1
)
start "" ".venv\Scripts\grindcap-gui.exe"
