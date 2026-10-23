<#
.SYNOPSIS
  启动 TechnologyAgent P00 本地开发环境（Mongo replica set + API + 前端）。
.DESCRIPTION
  只启动 P00 已实现的服务；重复调用不会重复开进程。
  未知端口占用会报错，不会结束任何非本项目进程。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root

$RuntimeDir = Join-Path $Root ".runtime"
$LogDir = Join-Path $RuntimeDir "logs"
New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null
$StateFile = Join-Path $RuntimeDir "processes.json"
$BuildMarkerFile = Join-Path $RuntimeDir "frontend-build.json"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith("#")) { continue }
        $index = $trim.IndexOf("=")
        if ($index -lt 1) { continue }
        $key = $trim.Substring(0, $index).Trim()
        $value = $trim.Substring($index + 1).Trim()
        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $value)
        }
    }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return [pscustomobject]@{ project_root = $Root; processes = @() }
    }
    try {
        $loaded = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        $processes = @()
        if ($null -ne $loaded.processes) { $processes = @($loaded.processes) }
        return [pscustomobject]@{ project_root = $Root; processes = $processes }
    } catch {
        return [pscustomobject]@{ project_root = $Root; processes = @() }
    }
}

function Save-State {
    param($State)
    $temp = "$StateFile.tmp"
    $payload = [ordered]@{
        project_root = $Root
        updated_at = (Get-Date).ToString("o")
        processes = @($State.processes)
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temp -Encoding utf8
    Move-Item -LiteralPath $temp -Destination $StateFile -Force
}

function Read-BuildMarker {
    if (-not (Test-Path -LiteralPath $BuildMarkerFile)) { return $null }
    try {
        return Get-Content -LiteralPath $BuildMarkerFile -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Save-BuildMarker {
    param([int]$ApiPort, [int]$FrontendPort)
    [ordered]@{
        api_port = $ApiPort
        frontend_port = $FrontendPort
        api_base = "http://127.0.0.1:$ApiPort"
        built_at = (Get-Date).ToString("o")
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $BuildMarkerFile -Encoding utf8
}

function Test-FrontendStack {
    param([string]$Base)
    try {
        $health = Invoke-RestMethod -Uri "$Base/health" -TimeoutSec 5
        if ($health.ok -ne $true -or $health.data.component -ne "api") { return $false }
        $ready = Invoke-RestMethod -Uri "$Base/ready" -TimeoutSec 20
        if ($ready.ok -ne $true -or $ready.data.status -ne "ready") { return $false }
        if ($ready.data.checks.db.status -ne "ok") { return $false }
        if ($ready.data.checks.transaction.status -ne "ok") { return $false }
        return $true
    } catch {
        return $false
    }
}

function Wait-FrontendStack {
    param([string]$Base, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-FrontendStack -Base $Base) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-RecordedProcess {
    param($Record)
    if ($null -eq $Record -or $null -eq $Record.pid) { return $null }
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        $ticks = $process.StartTime.ToUniversalTime().Ticks
    } catch {
        return $null
    }
    if ($ticks -ne [long]$Record.start_ticks) { return $null }
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($Record.pid)" -ErrorAction SilentlyContinue
    if ($null -eq $cim -or -not $cim.CommandLine) { return $null }
    foreach ($marker in @($Record.markers)) {
        if ($cim.CommandLine -notlike "*$marker*") { return $null }
    }
    return [pscustomobject]@{ Process = $process; CommandLine = $cim.CommandLine }
}

function Get-ListeningProcessId {
    param([int]$Port)
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) { return $null }
    return [int]$connection.OwningProcess
}

function Assert-PortFreeForStart {
    param([int]$Port, [string]$Name, $State)
    $owner = Get-ListeningProcessId -Port $Port
    if ($null -eq $owner) { return }
    $existing = @($State.processes | Where-Object { $_.name -eq $Name -and [int]$_.pid -eq $owner })
    if ($existing.Count -gt 0) {
        $validated = Test-RecordedProcess -Record $existing[0]
        if ($null -ne $validated) { return }
    }
    throw "端口 $Port 已被非本项目进程占用（PID $owner），start.ps1 不会结束它。请先释放端口或修改 .env 中的端口。"
}

function Wait-HttpOk {
    param([string]$Uri, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            # 继续等待
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-LogTail {
    param([string]$Path, [int]$Lines = 20)
    if (Test-Path -LiteralPath $Path) {
        Write-Host "--- $Path (tail) ---"
        Get-Content -LiteralPath $Path -Tail $Lines
    }
}

function New-ProcessRecord {
    param([string]$Name, [System.Diagnostics.Process]$Process, [string[]]$Markers, [int]$Port, [string[]]$Logs)
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.Id)"
    return [pscustomobject]@{
        name = $Name
        pid = $Process.Id
        started_at = (Get-Date).ToString("o")
        start_ticks = $Process.StartTime.ToUniversalTime().Ticks
        command = $cim.CommandLine
        markers = @($Markers)
        port = $Port
        logs = @($Logs)
    }
}

function Stop-Record {
    param($Record)
    $validated = Test-RecordedProcess -Record $Record
    if ($null -eq $validated) {
        Write-Warning "跳过 $($Record.name)：PID $($Record.pid) 已不存在或身份不匹配。"
        return
    }
    Stop-Process -Id ([int]$Record.pid) -Force -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
        $alive = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
        if ($null -eq $alive) { return }
        Start-Sleep -Milliseconds 250
    }
    taskkill /PID ([int]$Record.pid) /T /F | Out-Null
}

Import-DotEnv -Path (Join-Path $Root ".env")

function Get-ConfigValue {
    param([string]$Name, [string]$Default)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

$ApiPort = [int](Get-ConfigValue -Name "API_PORT" -Default "8030")
$FrontendPort = [int](Get-ConfigValue -Name "FRONTEND_PORT" -Default "3030")
$AppMode = Get-ConfigValue -Name "APP_MODE" -Default "local"
$ApiBase = "http://127.0.0.1:$ApiPort"
$FrontendBase = "http://127.0.0.1:$FrontendPort"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$FrontendRoot = Join-Path $Root "frontend"
$Node = (Get-Command node -ErrorAction Stop).Source
$Npm = (Get-Command npm.cmd -ErrorAction Stop).Source

$state = Read-State
$liveRecords = @()
foreach ($record in @($state.processes)) {
    if ($null -ne (Test-RecordedProcess -Record $record)) {
        $liveRecords += $record
    }
}
$state.processes = @($liveRecords)
Save-State -State $state

$buildMarker = Read-BuildMarker
$backendRecord = @($liveRecords | Where-Object { $_.name -eq "backend" -and [int]$_.port -eq $ApiPort }) | Select-Object -First 1
$frontendRecord = @($liveRecords | Where-Object { $_.name -eq "frontend" -and [int]$_.port -eq $FrontendPort }) | Select-Object -First 1
$staleRecords = @($liveRecords | Where-Object {
    ($_.name -eq "backend" -and [int]$_.port -ne $ApiPort) -or
    ($_.name -eq "frontend" -and [int]$_.port -ne $FrontendPort)
})
if ($staleRecords.Count -gt 0) {
    $summary = ($staleRecords | ForEach-Object { "$($_.name):$($_.port)" }) -join ", "
    throw "检测到本项目旧端口进程（$summary），当前配置为 API_PORT=$ApiPort、FRONTEND_PORT=$FrontendPort。请先运行 .\stop.ps1，再用新配置启动。"
}
if ($null -ne $frontendRecord -and $null -eq $buildMarker) {
    throw "前端进程正在运行，但缺少 .runtime/frontend-build.json，无法确认构建目标。请先运行 .\stop.ps1 再启动。"
}
if ($null -ne $frontendRecord -and $null -ne $buildMarker) {
    if ([int]$buildMarker.api_port -ne $ApiPort -or [int]$buildMarker.frontend_port -ne $FrontendPort) {
        throw "前端正在使用旧配置构建（API_PORT=$($buildMarker.api_port)），当前配置为 API_PORT=$ApiPort。请先运行 .\stop.ps1 再启动。"
    }
}
if ($null -ne $backendRecord -and -not (@($backendRecord.markers) -contains "--no-proxy-headers")) {
    throw "后端进程记录缺少 --no-proxy-headers，可能是旧版本启动。请先运行 .\stop.ps1 再用当前启动脚本启动。"
}
if ($null -ne $frontendRecord) {
    $frontendMarkers = @($frontendRecord.markers)
    if (-not ($frontendMarkers -contains "-H") -or -not ($frontendMarkers -contains "127.0.0.1")) {
        throw "前端进程记录缺少 127.0.0.1 监听参数，可能是旧版本启动。请先运行 .\stop.ps1 再用当前启动脚本启动。"
    }
}

if ($null -ne $backendRecord -and $null -ne $frontendRecord) {
    Write-Host "TechnologyAgent 应用进程已在运行，未启动重复实例；检查 MongoDB 依赖 ..."
    & docker compose up -d mongodb
    if ($LASTEXITCODE -ne 0) { throw "docker compose up 失败，退出码 $LASTEXITCODE" }
    & $Python -m scripts.init_db
    if ($LASTEXITCODE -ne 0) { throw "init_db 失败，退出码 $LASTEXITCODE" }
    if (-not (Wait-FrontendStack -Base $FrontendBase -TimeoutSeconds 30)) {
        Show-LogTail -Path (Join-Path $LogDir "frontend.err.log")
        Show-LogTail -Path (Join-Path $LogDir "backend.err.log")
        throw "进程已存在，但前端同源 /health 或 /ready 未通过；请先 stop.ps1 后重新启动并查看日志。"
    }
    Write-Host "同源 /health、/ready 已通过。"
    Write-Host "前端: $FrontendBase"
    Write-Host "API : $ApiBase/health"
    exit 0
}

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "未找到 .venv，执行 uv sync --frozen --group dev ..."
    & uv sync --frozen --group dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync 失败，退出码 $LASTEXITCODE" }
}

if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "node_modules"))) {
    Write-Host "未找到 frontend/node_modules，执行 npm ci ..."
    & $Npm --prefix $FrontendRoot ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci 失败，退出码 $LASTEXITCODE" }
}

Write-Host "启动 MongoDB replica set 容器 ..."
& docker compose up -d mongodb
if ($LASTEXITCODE -ne 0) { throw "docker compose up 失败，退出码 $LASTEXITCODE" }

Write-Host "初始化/校验数据库与索引 ..."
& $Python -m scripts.init_db
if ($LASTEXITCODE -ne 0) { throw "init_db 失败，退出码 $LASTEXITCODE" }

$newRecords = @()
try {
    if ($null -eq $backendRecord) {
        Assert-PortFreeForStart -Port $ApiPort -Name "backend" -State $state
        Write-Host "启动后端 API（端口 $ApiPort）..."
        $backendOut = Join-Path $LogDir "backend.out.log"
        $backendErr = Join-Path $LogDir "backend.err.log"
        $backendProcess = Start-Process -FilePath $Python -ArgumentList @(
            "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--no-proxy-headers", "--log-level", "info"
        ) -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
        $newRecords += New-ProcessRecord -Name "backend" -Process $backendProcess -Markers @("uvicorn", "backend.app.main:app", "--no-proxy-headers") -Port $ApiPort -Logs @($backendOut, $backendErr)
        $state.processes = @($liveRecords) + @($newRecords)
        Save-State -State $state
        if (-not (Wait-HttpOk -Uri "$ApiBase/health" -TimeoutSeconds 60)) {
            Show-LogTail -Path $backendErr
            Show-LogTail -Path $backendOut
            throw "后端未在 60 秒内通过 /health 检查。"
        }
        $liveRecords += $newRecords[-1]
        Write-Host "后端已就绪: $ApiBase/health"
    } else {
        Write-Host "后端已在运行（PID $($backendRecord.pid)）。"
    }

    if ($null -eq $frontendRecord) {
        Assert-PortFreeForStart -Port $FrontendPort -Name "frontend" -State $state
        Write-Host "按当前 API_PORT=$ApiPort 构建前端（每次新启动都构建，不复用旧 .next）..."
        & $Npm --prefix $FrontendRoot run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败，退出码 $LASTEXITCODE" }
        Save-BuildMarker -ApiPort $ApiPort -FrontendPort $FrontendPort
        Write-Host "启动前端（127.0.0.1:$FrontendPort）..."
        $frontendOut = Join-Path $LogDir "frontend.out.log"
        $frontendErr = Join-Path $LogDir "frontend.err.log"
        $frontendProcess = Start-Process -FilePath $Node -ArgumentList @(
            "node_modules\next\dist\bin\next", "start", "-H", "127.0.0.1", "-p", "$FrontendPort"
        ) -WorkingDirectory $FrontendRoot -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru
        $newRecords += New-ProcessRecord -Name "frontend" -Process $frontendProcess -Markers @("next", "start", "-H", "127.0.0.1") -Port $FrontendPort -Logs @($frontendOut, $frontendErr)
        $state.processes = @($liveRecords) + @($newRecords | Where-Object { $_.name -eq "frontend" })
        Save-State -State $state
        if (-not (Wait-HttpOk -Uri "$FrontendBase/" -TimeoutSeconds 60)) {
            Show-LogTail -Path $frontendErr
            Show-LogTail -Path $frontendOut
            throw "前端未在 60 秒内返回页面。"
        }
        Write-Host "前端页面已就绪: $FrontendBase"
    } else {
        Write-Host "前端已在运行（PID $($frontendRecord.pid)）。"
    }

    if (-not (Wait-FrontendStack -Base $FrontendBase -TimeoutSeconds 60)) {
        Show-LogTail -Path (Join-Path $LogDir "frontend.err.log")
        Show-LogTail -Path (Join-Path $LogDir "backend.err.log")
        throw "前端同源 /health 或 /ready 未在 60 秒内通过；拒绝仅凭首页 200 报告启动成功。"
    }
    Write-Host "前端同源 /health、/ready 已通过。"
} catch {
    Write-Warning $_.Exception.Message
    foreach ($record in @($newRecords)) {
        Stop-Record -Record $record
    }
    $remaining = @($state.processes | Where-Object { $_.name -notin @($newRecords | ForEach-Object { $_.name }) })
    $state.processes = @($remaining)
    Save-State -State $state
    throw
}

$finalState = Read-State
$finalState.processes = @($finalState.processes | Where-Object { $null -ne (Test-RecordedProcess -Record $_) })
Save-State -State $finalState

Write-Host ""
Write-Host "TechnologyAgent P00 已启动"
Write-Host "  页面:  $FrontendBase"
Write-Host "  health: $ApiBase/health"
Write-Host "  ready:  $ApiBase/ready"
Write-Host "  模式:  $AppMode（P00 不调用真实模型）"
Write-Host "  日志:  $LogDir"
Write-Host "  停止:  .\stop.ps1（MongoDB 容器保持运行）"
exit 0
