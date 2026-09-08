# scripts/xiyue_runtime/status.ps1
# Shows real-time status of Xiyue reactive runtime components.

$ErrorActionPreference = 'SilentlyContinue'

$hermesProfileDir = Join-Path $HOME ".hermes\profiles\xiyue"
$runtimeDir = Join-Path $hermesProfileDir "runtime"
$pidFile = Join-Path $hermesProfileDir "gateway.pid"
$stateDbPath = Join-Path $runtimeDir "cognition_state.sqlite"
$agentLog = Join-Path $hermesProfileDir "logs\agent.log"

# 1. Supervisor Status
$spProc = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "Hermes_Gateway_xiyue\.ps1"
} | Select-Object -First 1

$spStatus = if ($spProc) { "RUNNING (PID: $($spProc.ProcessId))" } else { "STOPPED" }

# 2. Gateway Status
$gwPid = $null
$gwStartTime = $null
$gwStatus = "STOPPED"

if (Test-Path $pidFile) {
    try {
        $pidData = Get-Content $pidFile -Raw | ConvertFrom-Json
        if ($pidData -and $pidData.pid) {
            $candProc = Get-Process -Id $pidData.pid -ErrorAction SilentlyContinue
            if ($candProc -and (-not $candProc.HasExited)) {
                $gwPid = $pidData.pid
                $gwStartTime = $candProc.StartTime.ToString("yyyy-MM-dd HH:mm:ss")
                $gwStatus = "RUNNING"
            }
        }
    } catch {}
}

if (-not $gwPid) {
    $gwProcCim = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match "--profile xiyue" -and $_.CommandLine -match "gateway run"
    } | Select-Object -First 1
    if ($gwProcCim) {
        $gwPid = $gwProcCim.ProcessId
        $gwStatus = "RUNNING"
        $candProc = Get-Process -Id $gwPid -ErrorAction SilentlyContinue
        if ($candProc) {
            $gwStartTime = $candProc.StartTime.ToString("yyyy-MM-dd HH:mm:ss")
        }
    }
}

# 3. Observation Window Status
$owProc = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "(observation_window\.web\.runtime|ow_bootstrap\.py)" -and $_.CommandLine -match "8766"
} | Select-Object -First 1

$owStatus = if ($owProc) { "RUNNING (PID: $($owProc.ProcessId))" } else { "STOPPED" }
$owUrl = "http://127.0.0.1:8766/live-trace"

# Ensure env keys are available in current process for accurate checks
foreach ($k in @("GLM_API_KEY", "APPRAISAL_API_KEY", "MR_ENABLED", "MR_SEMANTIC_PROVIDER")) {
    if (-not [Environment]::GetEnvironmentVariable($k, 'Process')) {
        $val = [Environment]::GetEnvironmentVariable($k, 'User')
        if (-not $val) { $val = [Environment]::GetEnvironmentVariable($k, 'Machine') }
        if ($val) { [Environment]::SetEnvironmentVariable($k, $val, 'Process') }
    }
}

# 4. Gateway Readiness & Epoch info (pure read-only)
$readinessFile = Join-Path $runtimeDir "readiness.json"
$coreReady = $false
$owReady = $false
$runtimeReadyAt = $null
$epochId = $null
$rdata = $null
$authoritativeAvailable = $false
if (Test-Path $readinessFile) {
    try {
        $rdata = Get-Content $readinessFile -Raw | ConvertFrom-Json
        if ($rdata) {
            $epochId = $rdata.epoch_id
            $rPid = $rdata.gateway_pid
            if ($gwPid -and ($rPid -eq $gwPid) -and ($gwStatus -eq "RUNNING")) {
                $coreReady = [bool]$rdata.core_ready
                $owReady = [bool]$rdata.ow_ready
                $runtimeReadyAt = $rdata.runtime_ready_at
                $authoritativeAvailable = $true
            }
        }
    } catch {}
}

# 5. Live OW health is diagnostic only; it never writes readiness.json.
$owHealthOk = $false
if ($owProc) {
    try {
        $healthResp = Invoke-RestMethod -Uri "http://127.0.0.1:8766/api/health" -TimeoutSec 2 -ErrorAction Stop
        $owHealthOk = ($healthResp.status -eq "ok")
    } catch {}
}

# 6. Project authoritative bundle state and detect drift; do not recompute it.
$bundleState = if ($authoritativeAvailable) { [string]$rdata.bundle_state } else { "NOT_READY" }
$expectedBundleState = if ($gwStatus -ne "RUNNING" -or -not $coreReady) {
    "NOT_READY"
} elseif (-not $owHealthOk) {
    "DEGRADED"
} else {
    "READY"
}
$readinessConsistency = ($authoritativeAvailable -and
    ($rdata.bundle_state -eq $expectedBundleState) -and
    ($owReady -eq $owHealthOk) -and
    ([bool]$rdata.core_ready -eq $coreReady))

if ($authoritativeAvailable -and $rdata.bundle_state -eq "READY" -and
    (-not $owHealthOk -or -not $owReady)) {
    $readinessConsistency = $false
}

# 7. MR Component Details (prefer live OW API, fallback to direct collector)
$mrInfo = $null
if ($owProc) {
    try {
        $traceResp = Invoke-RestMethod -Uri "http://127.0.0.1:8766/api/live-trace" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($traceResp -and $traceResp.header) {
            $h = $traceResp.header
            $mrInfo = [pscustomobject]@{
                semantic = $h.semantic_provider_status
                appraisal = $h.appraisal_provider_status
                slow = $h.slow_writer_status
                stale = $(if ($h.is_stale) { "YES" } else { "NO" })
                db = $h.state_db_path
            }
        }
    } catch {}
}

if (-not $mrInfo) {
    $mrInfo = python -c "
import json
try:
    from observation_window.live_runtime_trace import LiveRuntimeTraceCollector
    c = LiveRuntimeTraceCollector()
    rep = c.collect()
    h = rep.header
    print(json.dumps({
        'semantic': h.semantic_provider_status,
        'appraisal': h.appraisal_provider_status,
        'slow': h.slow_writer_status,
        'stale': 'YES' if h.is_stale else 'NO',
        'db': h.state_db_path
    }))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" | ConvertFrom-Json
}

# MR Adapter status
$mrAdapterStatus = "UNKNOWN"
if ($gwStatus -eq "RUNNING") {
    if ($coreReady) {
        $mrAdapterStatus = "ACTIVE"
    } elseif (Test-Path $agentLog) {
        $logTail = Get-Content $agentLog -Tail 150
        if ($logTail -match "XiyueMRAdapter initialized" -or $logTail -match "phase=ADAPTER_CREATE" -or $logTail -match "BEGIN_TURN_ENTRY") {
            $mrAdapterStatus = "ACTIVE"
        } elseif ($logTail -match "XiyueMRAdapter init failed") {
            $mrAdapterStatus = "ERROR"
        }
    }
}

$semanticStatus = if ($mrInfo -and $mrInfo.semantic) { $mrInfo.semantic } else { "UNKNOWN" }
$appraisalStatus = if ($mrInfo -and $mrInfo.appraisal) { $mrInfo.appraisal } else { "UNKNOWN" }
$slowWriterStatus = if ($mrInfo -and $mrInfo.slow) { $mrInfo.slow } else { "UNKNOWN" }
$isStale = if ($mrInfo -and $mrInfo.stale) { $mrInfo.stale } else { "UNKNOWN" }
$actualDbPath = if ($mrInfo -and $mrInfo.db) { $mrInfo.db } else { $stateDbPath }

# Print authoritative projection plus explicit consistency diagnostics.
Write-Host "=================================================="
Write-Host ("XIYUE RUNTIME STATUS: {0}" -f $bundleState)
Write-Host "=================================================="
Write-Host ("Authoritative Bundle: {0}" -f $bundleState)
Write-Host ("MR Core:             {0}" -f $(if ($coreReady) { "READY" } else { "NOT_READY" }))
Write-Host ("OW Readiness:        {0}" -f $(if ($owReady) { "READY" } else { "NOT_READY" }))
Write-Host ("OW Health:           {0}" -f $(if ($owHealthOk) { "PASS" } else { "FAIL" }))
Write-Host ("Readiness Consistency: {0}" -f $(if ($readinessConsistency) { "PASS" } else { "FAIL" }))
Write-Host ("Epoch ID:            {0}" -f $(if ($epochId) { $epochId } else { "-" }))
Write-Host ("Runtime Ready:       {0}" -f $(if ($runtimeReadyAt) { $runtimeReadyAt } else { "-" }))
Write-Host ("Supervisor:          {0}" -f $spStatus)
Write-Host ("Gateway:             {0}" -f $gwStatus)
Write-Host ("Gateway PID:         {0}" -f $(if ($gwPid) { $gwPid } else { "-" }))
Write-Host ("Gateway start:       {0}" -f $(if ($gwStartTime) { $gwStartTime } else { "-" }))
Write-Host ("MR adapter:          {0}" -f $mrAdapterStatus)
Write-Host ("Semantic:            {0}" -f $semanticStatus)
Write-Host ("Appraisal:           {0}" -f $appraisalStatus)
Write-Host ("Slow writer:         {0}" -f $slowWriterStatus)
Write-Host ("Observation process: {0}" -f $owStatus)
Write-Host ("OW URL:              {0}" -f $owUrl)
Write-Host ("DB path:             {0}" -f $actualDbPath)
Write-Host ""
Write-Host ("Gateway stale vs current production source: {0}" -f $isStale)
Write-Host "=================================================="

if (-not $readinessConsistency) {
    Write-Host "READINESS CONSISTENCY: FAIL"
}
