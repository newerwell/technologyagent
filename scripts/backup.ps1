[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^technologyagent_test_[a-zA-Z0-9_]+$')][string]$DatabaseName,
    [Parameter(Mandatory)][string]$Destination,
    [string]$StorageRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'storage'),
    [switch]$MaintenanceConfirmed
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $MaintenanceConfirmed) { throw 'Use -MaintenanceConfirmed only after stopping application/MCP processes and confirming no in-flight writes.' }
$statePath = Join-Path $Root '.runtime\processes.json'
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if (@($state.processes).Count -gt 0) { throw 'Application process registry is not empty; stop the app before backup.' }
}
$backupRoot = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $backupRoot) { throw 'Destination already exists; choose a new empty backup directory.' }
New-Item -ItemType Directory -Path $backupRoot | Out-Null
$archiveName = 'mongo.archive.gz'
$containerArchive = "/tmp/technologyagent-backup-$([guid]::NewGuid().ToString('N')).gz"
try {
    docker exec technologyagent-mongodb mongodump --port 27027 --db $DatabaseName --archive=$containerArchive --gzip
    if ($LASTEXITCODE -ne 0) { throw 'mongodump failed.' }
    docker cp "technologyagent-mongodb:$containerArchive" (Join-Path $backupRoot $archiveName)
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy database archive from Mongo container.' }
    $null = docker exec technologyagent-mongodb rm -f $containerArchive
    $storage = [IO.Path]::GetFullPath($StorageRoot)
    if (Test-Path -LiteralPath $storage) { Copy-Item -LiteralPath $storage -Destination (Join-Path $backupRoot 'storage') -Recurse }
    else { New-Item -ItemType Directory -Path (Join-Path $backupRoot 'storage') | Out-Null }
    $files = Get-ChildItem -LiteralPath $backupRoot -File -Recurse | ForEach-Object {
        [pscustomobject]@{ path = [IO.Path]::GetRelativePath($backupRoot, $_.FullName).Replace('\','/'); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); size_bytes = $_.Length }
    }
    [ordered]@{ format = 1; created_at = (Get-Date).ToUniversalTime().ToString('o'); database = $DatabaseName; storage_root = 'storage'; files = @($files) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $backupRoot 'manifest.json') -Encoding utf8
    Write-Host "Backup complete: $backupRoot"
} finally {
    $null = docker exec technologyagent-mongodb rm -f $containerArchive 2>$null
}
