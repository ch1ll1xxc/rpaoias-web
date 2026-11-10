@echo off
cd /d "%~dp0"
uv run python -m rpaoias.web %*
if errorlevel 1 pause
