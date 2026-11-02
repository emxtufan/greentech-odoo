param([string]$Database = '', [string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (!$Database) { $Database = Join-Path $root 'logs\saga-migration\source\cont_baza.fdb' }
if (!$OutputDirectory) { $OutputDirectory = Join-Path $root 'logs\saga-migration\extracted' }
$allowed = [IO.Path]::GetFullPath((Join-Path $root 'logs\saga-migration')) + [IO.Path]::DirectorySeparatorChar
if (![IO.Path]::GetFullPath($Database).StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Only a migration working copy may be opened.' }
Add-Type -Path 'C:\SAGA C.3.0\FirebirdSql.Data.FirebirdClient.dll'
$builder = New-Object FirebirdSql.Data.FirebirdClient.FbConnectionStringBuilder
$builder.Database = [IO.Path]::GetFullPath($Database)
$builder.UserID = 'SYSDBA'
$builder.ServerType = [FirebirdSql.Data.FirebirdClient.FbServerType]::Embedded
$builder.ClientLibrary = 'C:\Program Files\Firebird\Firebird30_Saga\fbclient.dll'
$builder.Charset = 'UTF8'
$builder.Pooling = $false
$builder.NoDatabaseTriggers = $true
$builder.NoGarbageCollect = $true
$connection = New-Object FirebirdSql.Data.FirebirdClient.FbConnection($builder.ConnectionString)
$utf8 = New-Object Text.UTF8Encoding($false)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
function Read-Rows([string]$sql) {
    $cmd = $connection.CreateCommand()
    $cmd.Transaction = $script:transaction
    $cmd.CommandText = $sql
    $reader = $cmd.ExecuteReader()
    try {
        while ($reader.Read()) {
            $row = [ordered]@{}
            for ($i=0; $i -lt $reader.FieldCount; $i++) {
                $value = $reader.GetValue($i)
                if ($value -is [DBNull]) { $value = $null }
                elseif ($value -is [DateTime]) { $value = $value.ToString('yyyy-MM-ddTHH:mm:ss.fffffff',[Globalization.CultureInfo]::InvariantCulture) }
                elseif ($value -is [decimal]) { $value = $value.ToString([Globalization.CultureInfo]::InvariantCulture) }
                elseif ($value -is [byte[]]) { $value = @{base64=[Convert]::ToBase64String($value)} }
                $row[$reader.GetName($i)] = $value
            }
            [pscustomobject]$row
        }
    } finally { $reader.Dispose(); $cmd.Dispose() }
}
try {
    $connection.Open()
    $options = New-Object FirebirdSql.Data.FirebirdClient.FbTransactionOptions
    $options.TransactionBehavior = [FirebirdSql.Data.FirebirdClient.FbTransactionBehavior]::Read -bor [FirebirdSql.Data.FirebirdClient.FbTransactionBehavior]::Concurrency -bor [FirebirdSql.Data.FirebirdClient.FbTransactionBehavior]::Wait
    $script:transaction = $connection.BeginTransaction($options)
    $tables = @(Read-Rows 'SELECT TRIM(RDB$RELATION_NAME) AS NAME FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG,0)=0 AND RDB$VIEW_BLR IS NULL ORDER BY RDB$RELATION_NAME')
    $schema = @(Read-Rows 'SELECT TRIM(RF.RDB$RELATION_NAME) AS TABLE_NAME, TRIM(RF.RDB$FIELD_NAME) AS FIELD_NAME, RF.RDB$FIELD_POSITION AS FIELD_POSITION, F.RDB$FIELD_TYPE AS FIELD_TYPE, F.RDB$FIELD_SUB_TYPE AS SUB_TYPE, F.RDB$FIELD_SCALE AS FIELD_SCALE, F.RDB$FIELD_LENGTH AS FIELD_LENGTH, F.RDB$CHARACTER_SET_ID AS CHARSET_ID FROM RDB$RELATION_FIELDS RF JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME=RF.RDB$FIELD_SOURCE JOIN RDB$RELATIONS R ON R.RDB$RELATION_NAME=RF.RDB$RELATION_NAME WHERE COALESCE(R.RDB$SYSTEM_FLAG,0)=0 AND R.RDB$VIEW_BLR IS NULL ORDER BY RF.RDB$RELATION_NAME, RF.RDB$FIELD_POSITION')
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'schema.json'), (ConvertTo-Json -InputObject $schema -Depth 8), $utf8)
    $counts = [ordered]@{}
    foreach ($table in $tables) {
        $name = $table.NAME
        if ($name -notmatch '^[A-Z0-9_]+$') { throw "Unexpected table identifier: $name" }
        $writer = New-Object IO.StreamWriter((Join-Path $OutputDirectory ($name + '.jsonl')), $false, $utf8)
        $count = 0
        try { Read-Rows ('SELECT * FROM "' + $name + '"') | ForEach-Object { $writer.WriteLine((ConvertTo-Json -InputObject $_ -Depth 12 -Compress)); $count++ } }
        finally { $writer.Dispose() }
        $expected = @(Read-Rows ('SELECT COUNT(*) AS N FROM "' + $name + '"'))[0].N
        if ($expected -ne $count) { throw "Row count mismatch: $name expected=$expected extracted=$count" }
        $counts[$name] = $count
    }
    $script:transaction.Rollback()
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'counts.json'), (ConvertTo-Json -InputObject $counts), $utf8)
    $manifest = @(Get-ChildItem -LiteralPath $OutputDirectory -File | Where-Object Name -ne 'sha256.json' | ForEach-Object { [ordered]@{name=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash} })
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'sha256.json'), (ConvertTo-Json -InputObject $manifest -Depth 4), $utf8)
    Write-Output ('EXTRACT_OK tables=' + $counts.Count + ' rows=' + (($counts.Values | Measure-Object -Sum).Sum))
} finally { if ($connection) { $connection.Dispose() } }

