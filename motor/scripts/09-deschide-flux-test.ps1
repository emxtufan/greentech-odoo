$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$accessFile = Join-Path $root 'config\acces-workflow-test.json'
if (-not (Test-Path -LiteralPath $accessFile)) { throw 'Lipseste configuratia bazei de demonstratie.' }
$access = Get-Content -LiteralPath $accessFile -Raw -Encoding UTF8 | ConvertFrom-Json
Set-Clipboard -Value $access.password
Write-Host '=== FLUX COMPLET ODOO - DATE FICTIVE ===' -ForegroundColor Green
Write-Host "Baza: $($access.database)"
Write-Host "Email / utilizator: $($access.login)"
Write-Host 'Parola pentru TEST a fost copiata: lipeste cu CTRL+V.'
Write-Host 'Parola acestei baze este diferita de parola pentru EMI.'
Write-Host 'Daca Odoo este oprit, ruleaza mai intai 03-PORNESTE-ODOO.cmd.'
Write-Host 'Ghidul contine cele 10 etape si linkuri la documentele finalizate.'
Start-Process (Join-Path $root 'GHID-FLUX-COMPLET-ODOO.html')
Start-Process $access.url
