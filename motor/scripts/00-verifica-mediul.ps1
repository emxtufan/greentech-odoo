$ErrorActionPreference = 'Continue'
Write-Host '=== GreenTech Odoo 19: verificare cerinte ==='
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    & py.exe -3.12 --version
    if ($LASTEXITCODE -ne 0) { Write-Host 'EROARE: Instaleaza Python 3.12 x64 + launcher.' -ForegroundColor Red }
} else { Write-Host 'EROARE: Python Launcher (py) nu este gasit.' -ForegroundColor Red }
if (Get-Command git.exe -ErrorAction SilentlyContinue) {
    & git.exe --version
} else { Write-Host 'EROARE: Instaleaza Git for Windows.' -ForegroundColor Red }
$psql = Get-Command psql.exe -ErrorAction SilentlyContinue
if (-not $psql) {
    $pgBase = Join-Path $env:ProgramFiles 'PostgreSQL'
    if (Test-Path $pgBase) {
        $psql = Get-ChildItem $pgBase -Filter psql.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
}
if ($psql) { Write-Host 'OK: psql.exe este disponibil.' -ForegroundColor Green }
else { Write-Host 'ATENTIE: PostgreSQL / psql.exe nu este inca instalat sau nu a fost gasit.' -ForegroundColor Yellow }
$root = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $root 'odoo\odoo-bin')) { Write-Host 'OK: Sursele Odoo sunt prezente.' }
else { Write-Host 'INFO: Sursele Odoo vor fi descarcate la pasul 01.' }
if (Test-Path (Join-Path $root 'config\odoo.conf')) { Write-Host 'OK: config\odoo.conf este prezent. Pastreaza parolele private.' }
else { Write-Host 'INFO: PostgreSQL trebuie configurat la pasul 02.' }
Write-Host 'Aceasta este o verificare preliminara, nu un test complet al instalarii.'
