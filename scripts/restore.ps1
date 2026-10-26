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
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Backup manifest is missing.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.format -ne 2 -or $manifest.database -notmatch '^technologyagent_test_[a-zA-Z0-9_]+$') { throw 'Unsupported or unsafe backup manifest.' }
$expectedNamespaces = @($manifest.database_namespaces | ForEach-Object { [string]$_ } | Sort-Object -Unique)
if ($expectedNamespaces.Count -eq 0 -or @($expectedNamespaces | Where-Object { -not $_.StartsWith("$($manifest.database).", [StringComparison]::Ordinal) }).Count -gt 0) {
    throw 'Manifest namespaces do not belong exclusively to its source test database.'
}
$archive = Join-Path $backupRoot 'mongo.archive.gz'
if (-not ($manifest.files.path -contains 'mongo.archive.gz')) { throw 'Mongo archive is not listed in manifest.' }
$listedPaths = @($manifest.files | ForEach-Object { [string]$_.path } | Sort-Object -Unique)
if ($listedPaths.Count -ne @($manifest.files).Count) { throw 'Manifest contains duplicate paths.' }
$backupEntries = @(Get-ChildItem -LiteralPath $backupRoot -Recurse -Force)
if (@($backupEntries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) {
    throw 'Backup contains a reparse point.'
}
$actualPaths = @($backupEntries | Where-Object { $_.PSIsContainer -eq $false -and $_.FullName -ne $manifestPath } | ForEach-Object {
    [IO.Path]::GetRelativePath($backupRoot, $_.FullName).Replace('\','/')
} | Sort-Object -Unique)
if ((Compare-Object $listedPaths $actualPaths) -or $listedPaths.Count -ne $actualPaths.Count) { throw 'Backup contains an unexpected storage file or a missing manifest file.' }
foreach ($item in $manifest.files) {
    if ([IO.Path]::IsPathRooted($item.path) -or $item.path.Split('/') -contains '..' -or $item.path.Contains('\')) { throw 'Manifest path is unsafe.' }
    $path = [IO.Path]::GetFullPath((Join-Path $backupRoot ($item.path -replace '/', '\')))
    if (-not $path.StartsWith($backupRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escapes backup root.' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Backup file missing: $($item.path)" }
    $file = Get-Item -LiteralPath $path
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $item.sha256 -or $file.Length -ne $item.size_bytes) { throw "Backup checksum or size mismatch: $($item.path)" }
}
$artifactRefs = @($manifest.artifact_refs)
$expectedStorageKeys = @($artifactRefs | ForEach-Object { [string]$_.storage_key } | Sort-Object -Unique)
if ($expectedStorageKeys.Count -ne $artifactRefs.Count) { throw 'Manifest contains duplicate artifact storage keys.' }
if (@($artifactRefs | Where-Object { $_.status -ne 'ready' -or -not $_._id -or -not $_.owner_id -or -not $_.run_id }).Count -gt 0) {
    throw 'Manifest artifact association is incomplete or not ready.'
}
$manifestStoragePaths = @($listedPaths | Where-Object { $_.StartsWith('storage/', [StringComparison]::Ordinal) } | ForEach-Object { $_.Substring(8) } | Sort-Object -Unique)
if ((Compare-Object $expectedStorageKeys $manifestStoragePaths) -or $expectedStorageKeys.Count -ne $manifestStoragePaths.Count) {
    throw 'Storage manifest files differ from artifact storage_key references.'
}
$targetStorage = [IO.Path]::GetFullPath($TargetStorageDirectory)
if (Test-Path -LiteralPath $targetStorage) { throw 'Target storage directory already exists.' }
$exists = [string](docker exec technologyagent-mongodb mongosh --port 27027 --quiet --eval "db.getSiblingDB('$TargetDatabase').getCollectionNames().length")
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect restore target database.' }
if ($exists.Trim() -ne '0') { throw 'Restore target is not empty or does not satisfy the new-target requirement.' }
$containerArchive = "/tmp/technologyagent-restore-$([guid]::NewGuid().ToString('N')).gz"
try {
    docker cp $archive "technologyagent-mongodb:$containerArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy archive to Mongo container.' }
    $inspection = @(docker exec technologyagent-mongodb mongorestore --port 27027 --dryRun --verbose --archive=$containerArchive --gzip 2>&1)
    if ($LASTEXITCODE -ne 0) { throw 'Archive namespace inspection failed.' }
    $inspectionText = $inspection -join "`n"
    $matches = [regex]::Matches($inspectionText, 'found collection `([^`]+)` bson to restore to `([^`]+)`')
    $archiveNamespaces = @($matches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
    if ($archiveNamespaces.Count -eq 0) { throw 'Archive contains no inspectable namespaces.' }
    if ((Compare-Object $expectedNamespaces $archiveNamespaces) -or $expectedNamespaces.Count -ne $archiveNamespaces.Count) {
        throw "Archive namespaces differ from manifest.database_namespaces; no database write performed."
    }
    $nsInclude = "$($manifest.database).*"
    docker exec technologyagent-mongodb mongorestore --port 27027 --archive=$containerArchive --gzip --nsInclude=$nsInclude --nsFrom="$($manifest.database).*" --nsTo="$TargetDatabase.*"
    if ($LASTEXITCODE -ne 0) { throw 'mongorestore failed; target database may be partial.' }
    $artifactScript = "const d=db.getSiblingDB('$TargetDatabase'); print(JSON.stringify(d.artifacts.find({}, {_id:1,owner_id:1,run_id:1,status:1,storage_key:1,size_bytes:1}).toArray().map(a=>({_id:a._id,owner_id:a.owner_id,run_id:a.run_id,status:a.status,storage_key:a.storage_key,size_bytes:a.size_bytes})).sort((a,b)=>a._id.localeCompare(b._id))));"
    $targetArtifactsRaw = docker exec technologyagent-mongodb mongosh --port 27027 --quiet --eval $artifactScript
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify restored artifact associations; target database may be partial.' }
    $targetArtifacts = @(($targetArtifactsRaw | Select-Object -Last 1) | ConvertFrom-Json)
    $sourceArtifacts = @($artifactRefs | Sort-Object _id)
    $sourceCanonical = ConvertTo-Json -InputObject $sourceArtifacts -Depth 6 -Compress
    $targetCanonical = ConvertTo-Json -InputObject $targetArtifacts -Depth 6 -Compress
    if ($sourceCanonical -cne $targetCanonical) { throw 'Restored artifact records do not match manifest associations; target database may be partial.' }
    $storageSource = Join-Path $backupRoot 'storage'
    if ($expectedStorageKeys.Count -gt 0) {
        if (-not (Test-Path -LiteralPath $storageSource -PathType Container)) { throw 'Artifact storage directory is missing; target database was restored but storage is incomplete.' }
        Copy-Item -LiteralPath $storageSource -Destination $targetStorage -Recurse
        foreach ($reference in $artifactRefs) {
            $filePath = Join-Path $targetStorage ($reference.storage_key -replace '/', '\')
            if (-not (Test-Path -LiteralPath $filePath -PathType Leaf) -or (Get-Item -LiteralPath $filePath).Length -ne $reference.size_bytes) {
                throw "Restored artifact content is missing or has wrong size: $($reference._id)"
            }
        }
    } else {
        New-Item -ItemType Directory -Path $targetStorage | Out-Null
    }
    Write-Host "Restore complete: database=$TargetDatabase storage=$targetStorage"
} finally {
    $null = docker exec technologyagent-mongodb rm -f $containerArchive 2>$null
}
