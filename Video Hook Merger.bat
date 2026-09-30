@echo off
REM Mo app. Keo tha clip / thu muc clip vao file nay de dien san.
set "PYW=%~dp0app\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Chua cai dat. Hay bam dup Setup.bat truoc.
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0app\gui.py" %*
