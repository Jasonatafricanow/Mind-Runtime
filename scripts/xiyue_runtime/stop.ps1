# scripts/xiyue_runtime/stop.ps1
# Stops ONLY Xiyue gateway supervisor, Xiyue gateway child, and Xiyue Observation Window.
# Preserves all other unrelated python, services, and Hermes profiles.

$ErrorActionPreference = 'SilentlyContinue'

$hermesProfileDir = Join-Path $HOME ".hermes\profiles\xiyue"
$runtimeDir = Join-Path $hermesProfileDir "runtime"
$pidFile = Join-Path $hermesProfileDir "gateway.pid"
$lockFile = Join-Path $hermesProfileDir "gateway.lock"
$owPidFile = Join-Path $runtimeDir "ow.pid"

Write-Host "=================================================="
Write-Host "Xiyue Runtime: STOPPING"
Write-Host "=================================================="

# 1. Stop Xiyue Gateway Supervisor
$supervisorProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "Hermes_Gateway_xiyue\.ps1"
}

if ($supervisorProcesses) {
    foreach ($sp in $supervisorProcesses) {
        Write-Host "  Stopping Supervisor (PID: $($sp.ProcessId))..."
        Stop-Process -Id $sp.ProcessId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "  Supervisor: not running"
}

# 2. Stop Xiyue Gateway Child Process
$stoppedGw = $false

# First try PID file
if (Test-Path $pidFile) {
    try {
        $pidData = Get-Content $pidFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        if ($pidData -and $pidData.pid) {
            $candProc = Get-CimInstance Win32_Process -Filter "ProcessId = $($pidData.pid)" -ErrorAction SilentlyContinue
            if ($candProc -and $candProc.CommandLine -match "--profile xiyue" -and $candProc.CommandLine -match "gateway run") {
                Write-Host "  Stopping Gateway child (PID: $($candProc.ProcessId))..."
                Stop-Process -Id $candProc.ProcessId -Force -ErrorAction SilentlyContinue
                $stoppedGw = $true
            }
        }
    } catch {}
}

# Also verify via CIM strictly matching profile xiyue
$gatewayProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "--profile xiyue" -and $_.CommandLine -match "gateway run"
}

foreach ($gw in $gatewayProcesses) {
    Write-Host "  Stopping Gateway child (PID: $($gw.ProcessId))..."
    Stop-Process -Id $gw.ProcessId -Force -ErrorAction SilentlyContinue
    $stoppedGw = $true
}

if (-not $stoppedGw) {
    Write-Host "  Gateway: not running"
}

# Cleanup pid/lock/readiness files
if (Test-Path $pidFile) {
    Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
}
if (Test-Path $lockFile) {
    Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
}
$readinessFile = Join-Path $runtimeDir "readiness.json"
if (Test-Path $readinessFile) {
    Remove-Item -Force $readinessFile -ErrorAction SilentlyContinue
}

# 3. Stop Xiyue Observation Window
$stoppedOw = $false

if (Test-Path $owPidFile) {
    try {
        $candOw = [int](Get-Content $owPidFile -Raw -ErrorAction SilentlyContinue).Trim()
        $candProc = Get-CimInstance Win32_Process -Filter "ProcessId = $candOw" -ErrorAction SilentlyContinue
        if ($candProc -and $candProc.CommandLine -match "(observation_window\.web\.runtime|ow_bootstrap\.py)") {
            Write-Host "  Stopping Observation Window (PID: $candOw)..."
            Stop-Process -Id $candOw -Force -ErrorAction SilentlyContinue
            $stoppedOw = $true
        }
    } catch {}
    Remove-Item -Force $owPidFile -ErrorAction SilentlyContinue
}

# Also verify via CIM strictly matching port 8766
$owProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "(observation_window\.web\.runtime|ow_bootstrap\.py)" -and $_.CommandLine -match "8766"
}

foreach ($ow in $owProcesses) {
    Write-Host "  Stopping Observation Window (PID: $($ow.ProcessId))..."
    Stop-Process -Id $ow.ProcessId -Force -ErrorAction SilentlyContinue
    $stoppedOw = $true
}

if (-not $stoppedOw) {
    Write-Host "  Observation Window: not running"
}

# Release supervisor mutex lock if abandoned
try {
    [Threading.Mutex]::OpenExisting('Global\HermesGatewaySupervisorXiyue').Dispose()
} catch {}

Write-Host "=================================================="
Write-Host "Xiyue Runtime: STOPPED"
Write-Host "=================================================="
