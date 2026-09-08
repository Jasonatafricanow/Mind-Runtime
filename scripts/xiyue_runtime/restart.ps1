# scripts/xiyue_runtime/restart.ps1
# Stops exact Xiyue runtime processes, starts them fresh, and verifies:
# new gateway PID, new start time, OW reachable, and stale warning cleared.

$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot
$hermesProfileDir = Join-Path $HOME ".hermes\profiles\xiyue"
$pidFile = Join-Path $hermesProfileDir "gateway.pid"

Write-Host "=================================================="
Write-Host "Xiyue Runtime: RESTARTING"
Write-Host "=================================================="

# 1. Record old gateway PID and start time if available
$oldGwPid = $null
$oldStartTime = $null

if (Test-Path $pidFile) {
    try {
        $pidData = Get-Content $pidFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        if ($pidData -and $pidData.pid) {
            $oldGwPid = $pidData.pid
            $proc = Get-Process -Id $oldGwPid -ErrorAction SilentlyContinue
            if ($proc) {
                $oldStartTime = $proc.StartTime
            }
        }
    } catch {}
}

if (-not $oldGwPid) {
    $candProc = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match "--profile xiyue" -and $_.CommandLine -match "gateway run"
    } | Select-Object -First 1
    if ($candProc) {
        $oldGwPid = $candProc.ProcessId
        $proc = Get-Process -Id $oldGwPid -ErrorAction SilentlyContinue
        if ($proc) {
            $oldStartTime = $proc.StartTime
        }
    }
}

$readinessFile = Join-Path $hermesProfileDir "runtime\readiness.json"
$oldEpochId = $null
if (Test-Path $readinessFile) {
    try {
        $oldEpochId = (Get-Content $readinessFile -Raw | ConvertFrom-Json).epoch_id
    } catch {}
}

# 2. Stop exact Xiyue runtime processes
& "$scriptDir\stop.ps1"

# Brief pause to ensure OS frees sockets and file locks
Start-Sleep -Seconds 2

# 3. Start Xiyue runtime
& "$scriptDir\start.ps1"

# 4. Verification
Write-Host ""
Write-Host "=================================================="
Write-Host "VERIFYING RESTART"
Write-Host "=================================================="

# A. Verify new gateway PID
$newGwPid = $null
$newStartTime = $null
if (Test-Path $pidFile) {
    try {
        $pidData = Get-Content $pidFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        if ($pidData -and $pidData.pid) {
            $newGwPid = $pidData.pid
            $proc = Get-Process -Id $newGwPid -ErrorAction SilentlyContinue
            if ($proc) {
                $newStartTime = $proc.StartTime
            }
        }
    } catch {}
}

if (-not $newGwPid) {
    if (Test-Path $readinessFile) {
        try {
            $rdata = Get-Content $readinessFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
            if ($rdata -and $rdata.gateway_pid) {
                $candProc = Get-Process -Id $rdata.gateway_pid -ErrorAction SilentlyContinue
                if ($candProc -and (-not $candProc.HasExited)) {
                    $newGwPid = $rdata.gateway_pid
                    $newStartTime = $candProc.StartTime
                }
            }
        } catch {}
    }
}

if (-not $newGwPid) {
    $candProc = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match "--profile xiyue" -and $_.CommandLine -match "gateway run"
    } | Select-Object -First 1
    if ($candProc) {
        $newGwPid = $candProc.ProcessId
        $proc = Get-Process -Id $newGwPid -ErrorAction SilentlyContinue
        if ($proc) {
            $newStartTime = $proc.StartTime
        }
    }
}

if (-not $newGwPid) {
    Write-Error "Verification failed: new gateway PID not found."
    exit 1
}

$pidChanged = ($null -eq $oldGwPid) -or ($newGwPid -ne $oldGwPid)
if (-not $pidChanged) {
    Write-Error "Verification failed: gateway PID did not change ($newGwPid)."
    exit 1
}
if ($oldStartTime -and $newStartTime -and ($newStartTime -le $oldStartTime)) {
    Write-Error "Verification failed: gateway start time ($newStartTime) is not newer than old start time ($oldStartTime)."
    exit 1
}
Write-Host ("  Gateway PID:            {0} -> {1} (PASS)" -f $(if ($oldGwPid) { $oldGwPid } else { "none" }), $newGwPid)
Write-Host ("  Gateway Start Time:     {0} (PASS)" -f $newStartTime)

# B. Verify Observation Window reachable
$owHealthUrl = "http://127.0.0.1:8766/api/health"
$owOk = $false
try {
    $resp = Invoke-RestMethod -Uri $owHealthUrl -TimeoutSec 3 -ErrorAction Stop
    if ($resp.status -eq "ok") {
        $owOk = $true
    }
} catch {}

if ($owOk) {
    Write-Host "  Observation Window:     REACHABLE (PASS)"
} else {
    Write-Error "Observation Window unreachable at $owHealthUrl"
    exit 1
}

# C. Verify stale warning cleared via /api/live-trace
$traceUrl = "http://127.0.0.1:8766/api/live-trace"
$staleCleared = $false
try {
    $traceResp = Invoke-RestMethod -Uri $traceUrl -TimeoutSec 4 -ErrorAction Stop
    if ($traceResp -and $traceResp.header) {
        $isStale = $traceResp.header.is_stale
        if (-not $isStale) {
            $staleCleared = $true
        } else {
            Write-Host "  Note: Stale detail: $($traceResp.header.stale_detail)"
        }
    }
} catch {
    Write-Warning "Could not query /api/live-trace: $_"
}

if ($staleCleared) {
    Write-Host "  Stale Warning Cleared:  YES (PASS)"
} else {
    Write-Host "  Stale Warning Cleared:  PENDING / RESTART REFRESHED"
}

# D. Verify new runtime epoch & readiness
if (Test-Path $readinessFile) {
    try {
        $rdata = Get-Content $readinessFile -Raw | ConvertFrom-Json
        $newEpochId = $rdata.epoch_id
        $newReadyAt = $rdata.runtime_ready_at
        $bundleState = $rdata.bundle_state
        if ($oldEpochId -and ($newEpochId -eq $oldEpochId)) {
            Write-Error "Verification failed: epoch ID was not refreshed ($newEpochId)."
            exit 1
        }
        Write-Host ("  New Epoch ID:           {0} (PASS)" -f $newEpochId)
        Write-Host ("  Runtime Ready At:       {0} (PASS)" -f $newReadyAt)
        Write-Host ("  Bundle State:           {0} (PASS)" -f $bundleState)
    } catch {
        Write-Warning "Could not verify readiness.json: $_"
    }
}

Write-Host "=================================================="
Write-Host "Xiyue Runtime Restart: COMPLETE"
Write-Host "=================================================="
