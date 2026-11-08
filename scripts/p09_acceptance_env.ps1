[CmdletBinding()]
param(
    [string]$Mode,
    [switch]$Restore
)

$ErrorActionPreference = "Stop"
$managedNames = @(
    "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "MONGODB_URI", "MONGODB_TEST_URI",
    "MONGODB_DATABASE", "INVENTORY_DATA_SOURCE", "PARTS_DATA_SOURCE",
    "SUPPLIERS_DATA_SOURCE", "ORDERS_DATA_SOURCE", "INVENTORY_SNAPSHOT_PATH",
    "MODEL_MODE", "RUN_LIVE_MODEL"
)
$snapshotVariable = "TechnologyAgentP09AcceptanceEnvironmentSnapshot"

if (-not (Get-Variable -Name $snapshotVariable -Scope Global -ErrorAction SilentlyContinue)) {
    $snapshot = @{}
    foreach ($name in $managedNames) {
        $entry = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        $snapshot[$name] = if ($null -eq $entry) {
            @{ present = $false; value = $null }
        } else {
            @{ present = $true; value = [string]$entry.Value }
        }
    }
    Set-Variable -Name $snapshotVariable -Scope Global -Value $snapshot
}

if ($Restore) {
    $original = Get-Variable -Name $snapshotVariable -Scope Global -ValueOnly -ErrorAction SilentlyContinue
    if ($null -eq $original) { return }
    foreach ($name in $managedNames) {
        $value = $original[$name]
        if ($value.present) {
            [Environment]::SetEnvironmentVariable($name, [string]$value.value, "Process")
        } else {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
    }
    Remove-Variable -Name $snapshotVariable -Scope Global -Force
    return
}

if (-not $PSBoundParameters.ContainsKey("Mode")) {
    throw "Specify -Mode offline, browser, or live; use -Restore to restore the original process environment."
}
if ($Mode -notin @("offline", "browser", "live")) {
    throw "Unsupported P09 acceptance mode. Use offline, browser, or live."
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$composePath = Join-Path $repositoryRoot "compose.p09-acceptance.yaml"
if (-not (Test-Path -LiteralPath $composePath)) {
    throw "P09 isolated compose file is missing from this checkout."
}
$database = switch ($Mode) {
    "offline" { "technologyagent_test_p09_verify" }
    "browser" { "technologyagent_test_p09_browser" }
    "live" { "technologyagent_test_p09_live" }
}
$mongoUri = "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true"
$values = @{
    COMPOSE_FILE = $composePath
    COMPOSE_PROJECT_NAME = "technologyagent-p09-acceptance"
    MONGODB_URI = $mongoUri
    MONGODB_TEST_URI = $mongoUri
    MONGODB_DATABASE = $database
    INVENTORY_DATA_SOURCE = "local_seed"
    PARTS_DATA_SOURCE = "local_seed"
    SUPPLIERS_DATA_SOURCE = "local_seed"
    ORDERS_DATA_SOURCE = "local_seed"
    INVENTORY_SNAPSHOT_PATH = ""
    MODEL_MODE = if ($Mode -eq "live") { "live" } else { "fake" }
    RUN_LIVE_MODEL = if ($Mode -eq "live") { "1" } else { "0" }
}
foreach ($name in $values.Keys) {
    [Environment]::SetEnvironmentVariable($name, [string]$values[$name], "Process")
}
