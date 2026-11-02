@echo off
cd /d "%~dp0"
where code >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    code "%~dp0"
) else (
    echo Nu gasesc comanda VS Code 'code'. Deschide VS Code ^> File ^> Open Folder ^> acest folder.
)
pause
