$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$conf = Join-Path $root 'config\odoo.conf'
if (-not (Test-Path -LiteralPath $conf)) { throw 'Lipseste config\odoo.conf. Ruleaza mai intai pasul 02.' }
$line = Get-Content -LiteralPath $conf -Encoding UTF8 | Where-Object { $_ -match '^\s*admin_passwd\s*=' } | Select-Object -First 1
if (-not $line) { throw 'Nu gasesc admin_passwd in configuratie.' }
$secret = ($line -split '=', 2)[1].Trim()
if (-not $secret) { throw 'Parola master nu este configurata.' }
if ($secret.StartsWith('$')) { throw 'Configuratia contine un hash, nu parola originala. Nu il folosi in formular. Este necesara resetarea parolei master Odoo.' }
Set-Clipboard -Value $secret
$secret = $null
Write-Host 'Parola MASTER Odoo a fost copiata in clipboard.' -ForegroundColor Green
Write-Host 'In formularul Odoo, click in Master Password si apasa CTRL+V.'
Write-Host 'La Password alege o parola pentru contul tau de utilizator Odoo.'
Write-Host 'Dupa folosire, copiaza un alt text pentru a inlocui parola din clipboard.'
