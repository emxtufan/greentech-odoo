@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
".venv\Scripts\python.exe" "scripts\d300_finish_demo.py"
if errorlevel 1 (
 echo.
 echo Instalarea sau validarea D300 nu s-a finalizat. Cititi mesajul de mai sus.
)
pause
