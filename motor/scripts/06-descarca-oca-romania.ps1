$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'third_party_addons\l10n-romania'
$conf = Join-Path $root 'config\odoo.conf'
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Git nu este in PATH.' }
if (-not (Test-Path $target)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    & git.exe clone --branch 19.0 --single-branch --depth 1 https://github.com/OCA/l10n-romania.git $target
    if ($LASTEXITCODE -ne 0) { throw 'Nu am putut descarca OCA/l10n-romania (19.0).' }
} else { Write-Host 'Repo OCA este deja prezent. Nu il suprascriu.' }
if (Test-Path $conf) {
    $lines = [IO.File]::ReadAllLines($conf)
    $updated = @()
    foreach ($line in $lines) {
        if ($line -match '^addons_path\s*=') {
            if ($line -notlike "*$target*") { $line = $line.TrimEnd() + ',' + $target }
        }
        $updated += $line
    }
    [IO.File]::WriteAllLines($conf, $updated, [Text.UTF8Encoding]::new($false))
}
Write-Host 'OCA Romania a fost descarcat. Repo adaugat in addons_path (daca odoo.conf exista).'
Write-Host 'Repornieste Odoo, activeaza modul developer, Update Apps List.'
Write-Host 'Nu instala toate modulele automat: unele au dependinte suplimentare.'
