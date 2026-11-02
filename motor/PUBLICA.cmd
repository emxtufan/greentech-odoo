@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publica.ps1"
if errorlevel 1 (
 echo.
 echo Publicarea nu s-a terminat. Cititi mesajul de mai sus.
)
echo.
pause
