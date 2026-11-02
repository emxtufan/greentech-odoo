$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $root 'config'
$configFile = Join-Path $configDir 'odoo.conf'
$role = 'greentech_odoo'
$port = 5432

function New-Secret {
    $b = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($b) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($b).TrimEnd('=').Replace('+', 'A').Replace('/', 'B')
}
function Unprotect-SecureString([System.Security.SecureString]$secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

Write-Host '=== PostgreSQL local pentru Odoo / GreenTech ==='
if (Test-Path $configFile) {
    throw 'config\odoo.conf exista deja. Nu resetez parola automat. Pastreaza-l; ruleaza 03-PORNESTE-ODOO.cmd.'
}
$psqlCmd = Get-Command 'psql.exe' -ErrorAction SilentlyContinue
$psql = $null
if ($psqlCmd) { $psql = $psqlCmd.Source }
if (-not $psql) {
    $pgRoot = Join-Path $env:ProgramFiles 'PostgreSQL'
    if (Test-Path $pgRoot) {
        $candidates = @(Get-ChildItem $pgRoot -Directory | Sort-Object { try { [int]$_.Name } catch { 0 } } -Descending)
        foreach ($candidate in $candidates) {
            $possible = Join-Path $candidate.FullName 'bin\psql.exe'
            if (Test-Path $possible) { $psql = $possible; break }
        }
    }
}
if (-not $psql) { throw 'Nu gasesc psql.exe. Instaleaza PostgreSQL 16 x64 cu psql si pgAdmin.' }

$secureAdmin = Read-Host 'Parola utilizatorului postgres setata la instalarea PostgreSQL' -AsSecureString
$adminPassword = Unprotect-SecureString $secureAdmin
$rolePassword = New-Secret
$masterPassword = New-Secret
$safeRolePassword = $rolePassword.Replace("'", "''")

$sqlTemplate = @'
DO $greentech$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'greentech_odoo') THEN
        CREATE ROLE greentech_odoo WITH LOGIN CREATEDB PASSWORD '__ROLE_PASSWORD__';
    ELSE
        ALTER ROLE greentech_odoo WITH LOGIN CREATEDB PASSWORD '__ROLE_PASSWORD__';
    END IF;
END
$greentech$;
'@
$sql = $sqlTemplate.Replace('__ROLE_PASSWORD__', $safeRolePassword)
$tmp = Join-Path $env:TEMP ("greentech-pg-" + [guid]::NewGuid().ToString('N') + '.sql')
[IO.File]::WriteAllText($tmp, $sql, [Text.UTF8Encoding]::new($false))
try {
    $env:PGPASSWORD = $adminPassword
    & $psql -X -h 127.0.0.1 -p $port -U postgres -d postgres --no-password -v ON_ERROR_STOP=1 -f $tmp
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL nu a acceptat comanda. Verifica parola, serviciul si portul 5432.' }
    $env:PGPASSWORD = $rolePassword
    & $psql -X -h 127.0.0.1 -p $port -U $role -d postgres --no-password -v ON_ERROR_STOP=1 -c 'SELECT current_user;'
    if ($LASTEXITCODE -ne 0) { throw 'Autentificarea utilizatorului greentech_odoo a esuat.' }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
    $adminPassword = $null
}

New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$dataDir = Join-Path $root 'data'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$paths = @((Join-Path $root 'odoo\addons'), (Join-Path $root 'custom_addons'))
$oca = Join-Path $root 'third_party_addons\l10n-romania'
if (Test-Path $oca) { $paths += $oca }
$addonsPath = $paths -join ','
$conf = @"
[options]
admin_passwd = $masterPassword
db_host = 127.0.0.1
db_port = $port
db_user = $role
db_password = $rolePassword
; Keep LC_COLLATE and LC_CTYPE consistent on PostgreSQL 18 / Windows.
db_template = template1
addons_path = $addonsPath
data_dir = $dataDir
http_interface = 127.0.0.1
http_port = 8069
list_db = True
proxy_mode = False
workers = 0
"@
[IO.File]::WriteAllText($configFile, $conf, [Text.UTF8Encoding]::new($false))
Write-Host ''
Write-Host 'GATA: rolul PostgreSQL a fost creat si config\odoo.conf a fost generat.' -ForegroundColor Green
Write-Host 'Parola master Odoo si parola DB sunt salvate local in config\odoo.conf. Nu publica acest fisier.'
Write-Host 'Porneste acum 03-PORNESTE-ODOO.cmd.'
