@echo off
REM CLI Windows: hook-merge.bat <thu_muc_clip | clip1 clip2 clip3> [--hook "..."] [--speed 1.2]
setlocal
set "ROOT=%~dp0.."
set PYTHONIOENCODING=utf-8
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%ROOT%\hook_merge.py" %*
