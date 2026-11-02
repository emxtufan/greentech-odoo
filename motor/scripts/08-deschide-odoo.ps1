$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$accessFile = Join-Path $root 'config\acces-local.json'
if (-not (Test-Path -LiteralPath $accessFile)) { throw 'Nu exista config\acces-local.json. Foloseste contul creat in Odoo.' }
$access = Get-Content -LiteralPath $accessFile -Raw -Encoding UTF8 | ConvertFrom-Json
Set-Clipboard -Value $access.password
Write-Host "Baza de date: $($access.database)"
Write-Host "Utilizator: $($access.login)"
Write-Host 'Parola contului a fost copiata. Lipeste-o cu CTRL+V in campul Password.' -ForegroundColor Green
Write-Host 'Aceasta este parola de autentificare, nu Master Password.'
Write-Host 'Dupa autentificare, copiaza alt text pentru a inlocui parola din clipboard.'
Start-Process $access.url
