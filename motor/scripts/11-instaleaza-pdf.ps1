$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$downloadDir = Join-Path $root 'tools\downloads'
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
$installer = Join-Path $downloadDir 'wkhtmltox-0.12.6-1.msvc2015-win64.exe'
$url = 'https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.msvc2015-win64.exe'
$expectedHash = '1EFCFAF8472871268FD399865A3E62B435B91D4413009B80830EAAFF7A57D088'
Write-Host 'Descarc motorul PDF oficial wkhtmltopdf 0.12.6 pentru Windows.'
if (-not (Test-Path -LiteralPath $installer)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Hash diferit de manifestul Microsoft winget. Nu execut instalatorul.' }
Write-Host 'Integritatea este verificata. Finalizeaza instalarea in fereastra afisata.'
Start-Process -FilePath $installer -Wait
Write-Host 'Dupa instalare, reporneste serverul financiar pentru a detecta motorul PDF.'
Write-Host 'Ruleaza 12-REPORNESTE-FINANCIAR.cmd, apoi testeaza Print pe o factura.'
