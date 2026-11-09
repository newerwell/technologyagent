[CmdletBinding()]
param(
    [string]$Mode,
    [switch]$Restore,
    [int]$ApiPort,
    [int]$FrontendPort,
    [int]$McpPort
)

$ErrorActionPreference = "Stop"
$managedNames = @(
    "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "MONGODB_URI", "MONGODB_TEST_URI",
    "MONGODB_DATABASE", "INVENTORY_DATA_SOURCE", "PARTS_DATA_SOURCE",
    "SUPPLIERS_DATA_SOURCE", "ORDERS_DATA_SOURCE", "INVENTORY_SNAPSHOT_PATH",
    "MODEL_MODE", "RUN_LIVE_MODEL", "API_PORT", "FRONTEND_PORT", "MCP_PORT",
    "P09_BROWSER_BASE_URL", "LIVE_API_URL", "STORAGE_ROOT", "UV_CACHE_DIR", "P06_REQUIRED",
    "P09_ACCEPTANCE_BUSINESS_NOW"
)
$snapshotVariable = "TechnologyAgentP09AcceptanceEnvironmentSnapshot"

if ($Restore) {
    $original = Get-Variable -Name $snapshotVariable -Scope Global -ValueOnly -ErrorAction SilentlyContinue
    if ($null -eq $original) { return }
    foreach ($name in $managedNames) {
        if (-not $original.ContainsKey($name)) {
            throw 'Incomplete old P09 environment snapshot; restore the C00 private baseline before using this helper.'
        }
    }
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
$portNames = @('ApiPort', 'FrontendPort', 'McpPort')
$provided = @($portNames | Where-Object { $PSBoundParameters.ContainsKey($_) })
if ($provided.Count -notin @(0, 3)) { throw 'Supply ApiPort, FrontendPort and McpPort together.' }
$original = Get-Variable -Name $snapshotVariable -Scope Global -ValueOnly -ErrorAction SilentlyContinue
if ($null -ne $original) {
    foreach ($name in $managedNames) {
        if (-not $original.ContainsKey($name)) { throw 'Incomplete old P09 environment snapshot; restore the C00 private baseline first.' }
    }
}
$selectedPorts = if ($provided.Count -eq 3) { @($ApiPort, $FrontendPort, $McpPort) }
    elseif ($null -ne $original -and $original.ContainsKey('_ports')) { @($original['_ports']) }
    else { @(8131, 3131, 9131) }
if (@($selectedPorts | Where-Object { $_ -lt 1 -or $_ -gt 65535 }).Count -gt 0 -or
    @($selectedPorts | Select-Object -Unique).Count -ne 3) { throw 'Ports must be distinct integers between 1 and 65535.' }

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$composePath = Join-Path $repositoryRoot "compose.p09-acceptance.yaml"
if (-not (Test-Path -LiteralPath $composePath)) {
    throw "P09 isolated compose file is missing from this checkout."
}
if ($null -eq $original) {
    $original = @{}
    foreach ($name in $managedNames) {
        $entry = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        $original[$name] = if ($null -eq $entry) { @{ present = $false; value = $null } }
            else { @{ present = $true; value = [string]$entry.Value } }
    }
    Set-Variable -Name $snapshotVariable -Scope Global -Value $original
}
$original['_ports'] = $selectedPorts
$database = switch ($Mode) {
    "offline" { "technologyagent_test_p09_verify" }
    "browser" { "technologyagent_test_p09_browser" }
    "live" { "technologyagent_test_p09_live" }
}
$mongoUri = "mongodb://127.0.0.1:27028/?replicaSet=ta-rs&directConnection=true"
$fixtureManifestPath = Join-Path $repositoryRoot 'fixtures/v1/manifest.json'
$fixtureManifestJson = [System.Text.Json.JsonDocument]::Parse(
    (Get-Content -LiteralPath $fixtureManifestPath -Raw)
)
try {
    $fixedBusinessNow = $fixtureManifestJson.RootElement.GetProperty('fixed_now').GetString()
} finally {
    $fixtureManifestJson.Dispose()
}
if ([string]::IsNullOrWhiteSpace($fixedBusinessNow)) {
    throw 'Fixture manifest must declare its fixed business clock.'
}
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
    API_PORT = [string]$selectedPorts[0]
    FRONTEND_PORT = [string]$selectedPorts[1]
    MCP_PORT = [string]$selectedPorts[2]
    P09_BROWSER_BASE_URL = "http://127.0.0.1:$($selectedPorts[1])"
    LIVE_API_URL = "http://127.0.0.1:$($selectedPorts[0])"
    P09_ACCEPTANCE_BUSINESS_NOW = if ($Mode -eq 'offline') { '' } else { $fixedBusinessNow }
}
foreach ($name in $values.Keys) {
    [Environment]::SetEnvironmentVariable($name, [string]$values[$name], "Process")
}
