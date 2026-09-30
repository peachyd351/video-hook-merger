@echo off
chcp 65001 >nul
REM Cai dat / kiem tra / sua loi Video Hook Merger. Bam lai bao nhieu lan cung duoc.
REM Tuy chon: Setup.bat -DryRun (chi kiem tra), Setup.bat -Torch cpu
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\setup.ps1" %*
echo.
pause
