@echo off
rem Same as grindcap.bat but keeps a console open, so startup errors are visible.
cd /d "%~dp0"
".venv\Scripts\grindcap.exe" gui
pause
