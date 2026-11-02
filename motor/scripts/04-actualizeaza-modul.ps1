param([string]$Database)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Database) {
    $accessFile = Join-Path $root 'config\acces-local.json'
    if (Test-Path -LiteralPath $accessFile) {
        $Database = (Get-Content -LiteralPath $accessFile -Raw -Encoding UTF8 | ConvertFrom-Json).database
    } else { $Database = 'greentech_test' }
}
$python = Join-Path $root '.venv\Scripts\python.exe'
$odoo = Join-Path $root 'odoo\odoo-bin'
$conf = Join-Path $root 'config\odoo.conf'
if (-not (Test-Path $python) -or -not (Test-Path $odoo) -or -not (Test-Path $conf)) {
    throw 'Instaleaza Odoo si configureaza PostgreSQL mai intai.'
}
Write-Host 'IMPORTANT: Opreste mai intai serverul Odoo cu CTRL+C.' -ForegroundColor Yellow
$answer = Read-Host "Odoo este oprit si baza $Database exista? (da/nu)"
if ($answer -ne 'da') { Write-Host 'Anulat.'; exit 0 }
Set-Location $root
& $python $odoo -c $conf -d $Database -u greentech_demo --stop-after-init --no-http
if ($LASTEXITCODE -ne 0) { throw 'Actualizarea modulului a esuat. Vezi erorile de mai sus.' }
Write-Host 'Actualizare terminata. Porneste din nou 03-PORNESTE-ODOO.cmd.'
