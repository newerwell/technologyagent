[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupDirectory,
    [Parameter(Mandatory)][ValidatePattern('^technologyagent_test_[a-zA-Z0-9_]+$')][string]$TargetDatabase,
    [Parameter(Mandatory)][string]$TargetStorageDirectory,
    [switch]$MaintenanceConfirmed
)
$ErrorActionPreference = 'Stop'
if (-not $MaintenanceConfirmed) { throw 'Use -MaintenanceConfirmed only for an isolated test target after confirming no in-flight writes.' }
$backupRoot = [IO.Path]::GetFullPath($BackupDirectory)
$manifestPath = Join-Path $backupRoot 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Backup manifest is missing.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.format -ne 1 -or $manifest.database -notmatch '^technologyagent_test_[a-zA-Z0-9_]+$') { throw 'Unsupported or unsafe backup manifest.' }
$targetStorage = [IO.Path]::GetFullPath($TargetStorageDirectory)
if (Test-Path -LiteralPath $targetStorage) { throw 'Target storage directory already exists.' }
foreach ($item in $manifest.files) {
    $path = [IO.Path]::GetFullPath((Join-Path $backupRoot ($item.path -replace '/', '\')))
    if (-not $path.StartsWith($backupRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escapes backup root.' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Backup file missing: $($item.path)" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $item.sha256) { throw "Backup checksum mismatch: $($item.path)" }
}
$archive = Join-Path $backupRoot 'mongo.archive.gz'
if (-not ($manifest.files.path -contains 'mongo.archive.gz')) { throw 'Mongo archive is not listed in manifest.' }
$exists = [string](docker exec technologyagent-mongodb mongosh --port 27027 --quiet --eval "db.getSiblingDB('$TargetDatabase').getCollectionNames().length")
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect restore target database.' }
if ($exists.Trim() -ne '0') { throw 'Restore target is not empty or does not satisfy the new-target requirement.' }
$containerArchive = "/tmp/technologyagent-restore-$([guid]::NewGuid().ToString('N')).gz"
try {
    docker cp $archive "technologyagent-mongodb:$containerArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy archive to Mongo container.' }
    docker exec technologyagent-mongodb mongorestore --port 27027 --archive=$containerArchive --gzip --nsFrom="$($manifest.database).*" --nsTo="$TargetDatabase.*"
    if ($LASTEXITCODE -ne 0) { throw 'mongorestore failed.' }
    Copy-Item -LiteralPath (Join-Path $backupRoot 'storage') -Destination $targetStorage -Recurse
    Write-Host "Restore complete: database=$TargetDatabase storage=$targetStorage"
} finally {
    $null = docker exec technologyagent-mongodb rm -f $containerArchive 2>$null
}
