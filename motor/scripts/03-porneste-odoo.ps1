$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$odoo = Join-Path $root 'odoo\odoo-bin'
$conf = Join-Path $root 'config\odoo.conf'
if (-not (Test-Path $python)) { throw 'Lipseste .venv. Ruleaza 01-INSTALEAZA-SURSE.cmd.' }
if (-not (Test-Path $odoo)) { throw 'Lipsesc sursele Odoo. Ruleaza 01-INSTALEAZA-SURSE.cmd.' }
if (-not (Test-Path $conf)) { throw 'Lipseste config\odoo.conf. Ruleaza 02-CONFIGUREAZA-POSTGRES.cmd.' }
Set-Location $root
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'odoo.log'
$portLine = Get-Content -LiteralPath $conf | Where-Object { $_ -match '^\s*http_port\s*=' } | Select-Object -First 1
$httpPort = if ($portLine) { [int](($portLine -split '=', 2)[1].Trim()) } else { 8069 }
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if ($listeners | Where-Object { $_.Port -eq $httpPort }) {
    Write-Host "Portul $httpPort este deja folosit. Daca Odoo ruleaza, deschide http://127.0.0.1:$httpPort" -ForegroundColor Yellow
    Write-Host 'Nu pornesc o a doua instanta pe acelasi port.'
    exit 0
}
Write-Host "Pornesc Odoo 19 direct din surse, local la http://127.0.0.1:$httpPort"
Write-Host 'Lasa fereastra deschisa. Opreste serverul cu CTRL+C.'
Write-Host "Jurnalul de erori: $logFile"
& $python $odoo -c $conf --dev=xml --logfile $logFile
if ($LASTEXITCODE -ne 0) { throw "Odoo s-a incheiat cu codul $LASTEXITCODE. Vezi eroarea de mai sus." }
