$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Verify-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step a esuat (cod $LASTEXITCODE)." }
}

Write-Host '=== GreenTech / Odoo 19 Community / Surse locale ==='
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    throw 'Instaleaza Git for Windows de la https://git-scm.com/download/win si reporneste terminalul.'
}
if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    throw 'Instaleaza Python 3.12 (64-bit) cu Python Launcher (py), de la https://www.python.org/downloads/windows/'
}
& py.exe -3.12 --version
Verify-Exit 'Python 3.12'

$source = Join-Path $root 'odoo'
if (-not (Test-Path (Join-Path $source 'odoo-bin'))) {
    if (Test-Path $source) { throw 'Folderul odoo exista, dar nu contine odoo-bin. Muta-l si reincearca.' }
    Write-Host 'Descarc sursele oficiale Odoo 19.0 (operatie cu acces la internet)...'
    & git.exe clone --branch 19.0 --single-branch --depth 1 https://github.com/odoo/odoo.git $source
    Verify-Exit 'Git clone'
} else {
    Write-Host 'Sursele Odoo exista deja; clone este omis.'
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'Creez mediul virtual Python 3.12...'
    & py.exe -3.12 -m venv (Join-Path $root '.venv')
    Verify-Exit 'Creare venv'
}

Write-Host 'Instalez dependentele Python oficiale (poate fi necesar Visual Studio C++ Build Tools)...'
& $python -m pip install --upgrade pip setuptools wheel
Verify-Exit 'Actualizare pip'
& $python -m pip install -r (Join-Path $source 'requirements.txt')
Verify-Exit 'Instalare requirements.txt'

Write-Host ''
Write-Host 'SURSE INSTALATE. Deschide 02-CONFIGUREAZA-POSTGRES.cmd dupa instalarea PostgreSQL.' -ForegroundColor Green
Write-Host 'Pentru Visual Studio Build Tools, vezi README.md.'
