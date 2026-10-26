[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^technologyagent_test_[a-zA-Z0-9_]+$')][string]$DatabaseName,
    [Parameter(Mandatory)][string]$Destination,
    [string]$StorageRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'storage'),
    [switch]$MaintenanceConfirmed
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $MaintenanceConfirmed) { throw 'Use -MaintenanceConfirmed only after stopping app/MCP processes and confirming no in-flight writes.' }
$statePath = Join-Path $Root '.runtime\processes.json'
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if (@($state.processes).Count -gt 0) { throw 'Application process registry is not empty; stop the app before backup.' }
}
$backupRoot = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $backupRoot) { throw 'Destination already exists; choose a new empty backup directory.' }
$storage = [IO.Path]::GetFullPath($StorageRoot)
$metadataScript = "const d=db.getSiblingDB('$DatabaseName'); print(JSON.stringify({collections:d.getCollectionNames().sort(),artifact_refs:d.artifacts.find({}, {_id:1,owner_id:1,run_id:1,status:1,storage_key:1,size_bytes:1}).toArray().map(a=>({_id:a._id,owner_id:a.owner_id,run_id:a.run_id,status:a.status,storage_key:a.storage_key,size_bytes:a.size_bytes}))}));"
$metadataLines = docker exec technologyagent-mongodb mongosh --port 27027 --quiet --eval $metadataScript
if ($LASTEXITCODE -ne 0) { throw 'Could not read collection and ready artifact metadata.' }
try { $metadata = ($metadataLines | Select-Object -Last 1) | ConvertFrom-Json }
catch { throw 'Database metadata response was not valid JSON; backup aborted.' }
$artifactRefs = @($metadata.artifact_refs)
if (@($artifactRefs | Where-Object { $_.status -ne 'ready' -or -not $_.storage_key }).Count -gt 0) {
    throw 'Database contains an artifact that is not ready or has no storage_key.'
}
$expectedStorageKeys = @($artifactRefs | ForEach-Object { [string]$_.storage_key } | Sort-Object -Unique)
if ($expectedStorageKeys.Count -ne $artifactRefs.Count) { throw 'Duplicate artifact storage_key found.' }
if (-not (Test-Path -LiteralPath $storage -PathType Container)) {
    if ($expectedStorageKeys.Count -gt 0) { throw 'StorageRoot is missing while database has ready artifact records.' }
    $storageFiles = @()
} else {
    $storageFiles = @(Get-ChildItem -LiteralPath $storage -File -Recurse -Force | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Storage contains a reparse point.' }
        [IO.Path]::GetRelativePath($storage, $_.FullName).Replace('\','/')
    } | Sort-Object -Unique)
}
foreach ($key in $expectedStorageKeys) {
    if ([IO.Path]::IsPathRooted($key) -or $key.Split('/') -contains '..' -or $key.Contains('\')) { throw 'Artifact storage_key is unsafe.' }
    $path = [IO.Path]::GetFullPath((Join-Path $storage ($key -replace '/', '\')))
    if (-not $path.StartsWith($storage + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Artifact storage_key escapes StorageRoot.' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Ready artifact content is missing: $key" }
}
if ((Compare-Object $expectedStorageKeys $storageFiles) -or $expectedStorageKeys.Count -ne $storageFiles.Count) {
    throw 'storage files differ from ready artifact records.'
}
New-Item -ItemType Directory -Path $backupRoot | Out-Null
$archiveName = 'mongo.archive.gz'
$containerArchive = "/tmp/technologyagent-backup-$([guid]::NewGuid().ToString('N')).gz"
try {
    docker exec technologyagent-mongodb mongodump --port 27027 --db $DatabaseName --archive=$containerArchive --gzip
    if ($LASTEXITCODE -ne 0) { throw 'mongodump failed.' }
    docker cp "technologyagent-mongodb:$containerArchive" (Join-Path $backupRoot $archiveName)
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy database archive from Mongo container.' }
    if ($storageFiles.Count -gt 0) { Copy-Item -LiteralPath $storage -Destination (Join-Path $backupRoot 'storage') -Recurse }
    else { New-Item -ItemType Directory -Path (Join-Path $backupRoot 'storage') | Out-Null }
    $files = @(Get-ChildItem -LiteralPath $backupRoot -File -Recurse -Force | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Backup contains a reparse point.' }
        [pscustomobject]@{ path = [IO.Path]::GetRelativePath($backupRoot, $_.FullName).Replace('\','/'); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); size_bytes = $_.Length }
    } | Sort-Object path)
    [ordered]@{
        format = 2; created_at = (Get-Date).ToUniversalTime().ToString('o'); database = $DatabaseName
        database_namespaces = @($metadata.collections | ForEach-Object { "$DatabaseName.$_" } | Sort-Object)
        storage_root = 'storage'; artifact_refs = $artifactRefs; files = $files
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backupRoot 'manifest.json') -Encoding utf8
    Write-Host "Backup complete: $backupRoot"
} finally {
    $null = docker exec technologyagent-mongodb rm -f $containerArchive 2>$null
}
