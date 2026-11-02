$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$expectedPython = Join-Path $root '.venv\Scripts\python.exe'
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -like '*config\odoo-financiar.conf*'
}
$approvedIds = @()
foreach ($process in $processes) {
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)" -ErrorAction SilentlyContinue
    if ($process.ExecutablePath -eq $expectedPython -or ($parent -and $parent.ExecutablePath -eq $expectedPython)) {
        $approvedIds += $process.ProcessId
    }
}
if ($approvedIds.Count -gt 0) { Stop-Process -Id $approvedIds -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
& (Join-Path $PSScriptRoot '10-financiar-demo.ps1') -StartOnly
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'financial_verify.py')
if ($LASTEXITCODE -ne 0) { throw 'Verificarea financiara nu a trecut. Vezi eroarea de mai sus.' }
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'financial_guide.py')
& (Join-Path $PSScriptRoot '10-financiar-demo.ps1')
