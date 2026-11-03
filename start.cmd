@echo off
setlocal
cd /d "%~dp0"
if defined GEN5_PYTHON (
  "%GEN5_PYTHON%" -X utf8 launch.py %*
) else (
  python -X utf8 launch.py %*
)
if errorlevel 1 pause
