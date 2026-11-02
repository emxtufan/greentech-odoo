param([switch]$StartOnly)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$access = Get-Content -LiteralPath (Join-Path $root 'config\acces-financiar-test.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($access.database -ne 'greentech_financiar_test') { throw 'Baza de test nu corespunde.' }
$pdfPaths = @((Join-Path $root 'tools\wkhtmltopdf\bin'), 'C:\Program Files\wkhtmltopdf\bin', 'C:\Program Files (x86)\wkhtmltopdf\bin')
foreach ($pdfPath in $pdfPaths) {
    if (Test-Path -LiteralPath (Join-Path $pdfPath 'wkhtmltopdf.exe')) { $env:PATH = $pdfPath + ';' + $env:PATH; break }
}
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if (-not ($listeners | Where-Object { $_.Port -eq 8070 })) {
    $financeProcess = Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList 'odoo\odoo-bin','-c','config\odoo-financiar.conf','--dev=xml' -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root 'logs\financial-server-out.log') -RedirectStandardError (Join-Path $root 'logs\financial-server-error.log')
    $financeProcess.Id | Set-Content -LiteralPath (Join-Path $root 'logs\financial-server.pid')
}
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8070/web/login' -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready) { throw 'Serverul financiar nu a raspuns. Vezi logs\odoo-financiar.log.' }
Write-Host 'Contabilitate Romania disponibila la http://127.0.0.1:8070' -ForegroundColor Green
if ($StartOnly) { exit 0 }
Set-Clipboard -Value $access.password
Write-Host 'Utilizator: admin. Parola a fost copiata: lipeste cu CTRL+V.'
Write-Host 'Baza contine si date contabile reale importate din SAGA. Are alta parola decat EMI.'
Start-Process $access.url
$currentGuide = Join-Path $root 'STARE-INSTALARE-OCA-RO.html'
if (-not (Test-Path -LiteralPath $currentGuide)) { $currentGuide = Join-Path $root 'GHID-FINANCIAR-DEMO.html' }
Start-Process $currentGuide
