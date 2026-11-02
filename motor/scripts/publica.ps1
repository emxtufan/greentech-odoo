param([string]$Server = 'root@167.233.202.96')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$deployScript = '/opt/greentech-financiar/repo/motor/deploy/server/deploy.sh'

Push-Location $repo
try {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne 'main') {
        Write-Host "Esti pe branch-ul '$branch'. Treci pe 'main' (git checkout main) si ruleaza din nou." -ForegroundColor Red
        exit 1
    }

    $modificari = @(git status --porcelain)
    if ($modificari.Count -gt 0) {
        Write-Host 'Salveaza intai modificarile (commit):' -ForegroundColor Red
        $modificari | ForEach-Object { Write-Host "  $_" }
        exit 1
    }

    Write-Host 'Trimit modificarile in GitHub (git push origin main) ...'
    git push origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'EROARE: git push a esuat. Verifica mesajul de mai sus.' -ForegroundColor Red
        exit 1
    }

    Write-Host "Rulez deploy pe server ($Server) ..."
    ssh $Server $deployScript
    $cod = $LASTEXITCODE
    if ($cod -ne 0) {
        Write-Host "EROARE: deploy-ul pe server a esuat (cod $cod). Verifica mesajele de mai sus." -ForegroundColor Red
        exit $cod
    }

    Write-Host 'OK: modificarile sunt publicate pe server.' -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
