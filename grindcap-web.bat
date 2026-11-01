@echo off
rem Browser test of grindcap: exports your item data for the page, serves the repo on localhost and opens it.
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist %PY% set PY=python
%PY% scripts\export_web_data.py
start "" http://localhost:8765/web/
%PY% scripts\serve_web.py
