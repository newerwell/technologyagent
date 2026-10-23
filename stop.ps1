<#
.SYNOPSIS
  停止由 start.ps1 登记并验证过身份的本项目进程。
.DESCRIPTION
  只处理 .runtime/processes.json 中 PID、启动时间和命令行均匹配的记录；
  不结束未知进程，不停止 MongoDB 容器。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
$StateFile = Join-Path $Root ".runtime\processes.json"
$BuildMarkerFile = Join-Path $Root ".runtime\frontend-build.json"

if (-not (Test-Path -LiteralPath $StateFile)) {
    if (Test-Path -LiteralPath $BuildMarkerFile) { Remove-Item -LiteralPath $BuildMarkerFile -Force }
    Write-Host "没有找到 .runtime/processes.json，未发现本项目登记进程。"
    exit 0
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
    return $process
}

$state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
$processes = @()
if ($null -ne $state.processes) { $processes = @($state.processes) }

$remaining = @()
foreach ($record in $processes) {
    $process = Test-RecordedProcess -Record $record
    if ($null -eq $process) {
        Write-Warning "跳过 $($record.name)：PID $($record.pid) 已退出或身份不匹配。"
        continue
    }
    Write-Host "停止 $($record.name)（PID $($record.pid)）..."
    Stop-Process -Id ([int]$record.pid) -Force -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(8)
    $stopped = $false
    while ((Get-Date) -lt $deadline) {
        if ($null -eq (Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue)) {
            $stopped = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $stopped) {
        taskkill /PID ([int]$record.pid) /T /F | Out-Null
    }
}

if (Test-Path -LiteralPath $StateFile) {
    Remove-Item -LiteralPath $StateFile -Force
}
if (Test-Path -LiteralPath $BuildMarkerFile) {
    Remove-Item -LiteralPath $BuildMarkerFile -Force
}
Write-Host "TechnologyAgent 应用进程已停止。MongoDB 容器未关闭（如需关闭: docker compose stop mongodb）。"
exit 0
