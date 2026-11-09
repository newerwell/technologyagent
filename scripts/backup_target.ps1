# Shared target guard only; backup and restore retain their own data validation.
function Assert-BackupMongoTarget {
    param([string]$MongoContainer, [int]$MongoPort, [bool]$ExplicitContainer, [bool]$ExplicitPort)
    if ($env:COMPOSE_PROJECT_NAME -eq 'technologyagent-p09-acceptance' -or
        $MongoContainer -eq 'technologyagent-p09-acceptance-mongodb' -or $MongoPort -eq 27028) {
        if (-not $ExplicitContainer -or -not $ExplicitPort -or
            $MongoContainer -ne 'technologyagent-p09-acceptance-mongodb' -or $MongoPort -ne 27028) {
            throw 'Use an explicit isolated Mongo target: -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028.'
        }
    }
}

function Assert-BackupMongoPrimary {
    param([string]$MongoContainer, [int]$MongoPort)
    $probe = 'const h=db.hello(); print(JSON.stringify({setName:h.setName,isWritablePrimary:h.isWritablePrimary}));'
    $lines = docker exec $MongoContainer mongosh --port $MongoPort --quiet --eval $probe
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect selected Mongo primary.' }
    try { $hello = ($lines | Select-Object -Last 1) | ConvertFrom-Json }
    catch { throw 'Selected Mongo hello was not valid JSON.' }
    if ($hello.setName -ne 'ta-rs' -or $hello.isWritablePrimary -ne $true) {
        throw 'Selected Mongo must be a writable ta-rs PRIMARY; no backup/restore performed.'
    }
}
