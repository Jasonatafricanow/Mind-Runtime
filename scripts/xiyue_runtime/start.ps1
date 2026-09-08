# scripts/xiyue_runtime/start.ps1
# Operational entrypoint for Xiyue reactive runtime:
# Gateway Supervisor -> Hermes Gateway -> embedded MR + Observation Window

$ErrorActionPreference = 'Stop'

$repoRoot = if ($env:MR_REPO_ROOT) {
    $env:MR_REPO_ROOT
} else {
    Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$hermesProfileDir = Join-Path $HOME ".hermes\profiles\xiyue"
$supervisorScript = Join-Path $hermesProfileDir "gateway-service\Hermes_Gateway_xiyue.ps1"
$runtimeDir = Join-Path $hermesProfileDir "runtime"
$pidFile = Join-Path $hermesProfileDir "gateway.pid"
$owPidFile = Join-Path $runtimeDir "ow.pid"
$stateDbPath = Join-Path $runtimeDir "cognition_state.sqlite"
$agentLog = Join-Path $hermesProfileDir "logs\agent.log"

Write-Host "=================================================="
Write-Host "Xiyue Runtime: STARTING"
Write-Host "=================================================="

# ------------------------------------------------------------------
# A. Load/check required operational env
# ------------------------------------------------------------------
Write-Host "[1/5] Checking operational environment..."

# Try loading keys from User/Machine hive or .env if missing in current process
$envVars = @("MR_ENABLED", "MR_SEMANTIC_PROVIDER", "GLM_API_KEY", "APPRAISAL_API_KEY")
$profileEnv = Join-Path $hermesProfileDir ".env"
$fileEnv = @{}
if (Test-Path $profileEnv) {
    Get-Content $profileEnv -ErrorAction SilentlyContinue | ForEach-Object {
        $line = $_.Trim()
        if ($line -and (-not $line.StartsWith("#")) -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $fileEnv[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
}

foreach ($key in $envVars) {
    $val = [Environment]::GetEnvironmentVariable($key, 'Process')
    if (-not $val) {
        $val = [Environment]::GetEnvironmentVariable($key, 'User')
    }
    if (-not $val) {
        $val = [Environment]::GetEnvironmentVariable($key, 'Machine')
    }
    if (-not $val -and $fileEnv.ContainsKey($key)) {
        $val = $fileEnv[$key]
    }
    if ($val) {
        [Environment]::SetEnvironmentVariable($key, $val, 'Process')
    }
}

# Defaults for MR operational switches
if (-not $env:MR_ENABLED) {
    $env:MR_ENABLED = 'true'
}
if (-not $env:MR_SEMANTIC_PROVIDER) {
    $env:MR_SEMANTIC_PROVIDER = 'glm'
}

$statusEnv = @{}
foreach ($key in $envVars) {
    $val = [Environment]::GetEnvironmentVariable($key, 'Process')
    $statusEnv[$key] = if ($val) { "PRESENT" } else { "MISSING" }
    Write-Host ("  {0,-22}: {1}" -f $key, $statusEnv[$key])
}

if ($statusEnv["GLM_API_KEY"] -eq "MISSING") {
    Write-Warning "GLM_API_KEY is MISSING in environment."
}
if ($statusEnv["APPRAISAL_API_KEY"] -eq "MISSING") {
    Write-Warning "APPRAISAL_API_KEY is MISSING in environment."
}

# ------------------------------------------------------------------
# B. Start or verify existing supervisor
# ------------------------------------------------------------------
Write-Host "[2/5] Checking Gateway Supervisor..."

$supervisorProcess = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "Hermes_Gateway_xiyue\.ps1"
} | Select-Object -First 1

$supervisorPid = $null
if ($supervisorProcess) {
    $supervisorPid = $supervisorProcess.ProcessId
    Write-Host "  Supervisor: ALREADY RUNNING (PID: $supervisorPid)"
} else {
    if (-not (Test-Path $supervisorScript)) {
        Write-Error "Supervisor script not found: $supervisorScript"
        exit 1
    }
    Write-Host "  Starting supervisor ($supervisorScript)..."
    $spCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$supervisorScript`""
    $spRes = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $spCmd
    }
    $supervisorPid = $spRes.ProcessId
    Write-Host "  Supervisor: STARTED (PID: $supervisorPid)"
}

# ------------------------------------------------------------------
# C. Wait until gateway PID exists and process is alive
# ------------------------------------------------------------------
Write-Host "[3/5] Waiting for Gateway child process..."

$gwPid = $null
$maxWaitSec = 30
$swGw = [Diagnostics.Stopwatch]::StartNew()

while ($swGw.Elapsed.TotalSeconds -lt $maxWaitSec) {
    if (Test-Path $pidFile) {
        try {
            $pidData = Get-Content $pidFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
            if ($pidData -and $pidData.pid) {
                $candProc = Get-Process -Id $pidData.pid -ErrorAction SilentlyContinue
                if ($candProc -and (-not $candProc.HasExited)) {
                    $gwPid = $pidData.pid
                    break
                }
            }
        } catch {}
    }
    if (-not $gwPid) {
        $candProc = Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -match "--profile xiyue" -and $_.CommandLine -match "gateway run"
        } | Select-Object -First 1
        if ($candProc) {
            $gwPid = $candProc.ProcessId
            break
        }
    }
    Start-Sleep -Milliseconds 500
}

if (-not $gwPid) {
    Write-Error "Timed out waiting for gateway PID to become alive."
    exit 1
}
Write-Host "  Gateway PID: $gwPid (ALIVE)"

# ------------------------------------------------------------------
# D. Verify gateway startup/log evidence
# ------------------------------------------------------------------
Write-Host "[4/5] Verifying MR Adapter & Runtime availability..."

$adapterReady = $false
$readinessFile = Join-Path $runtimeDir "readiness.json"
$coreReady = $false
$epochId = $null
$runtimeReadyAt = $null

$swReadiness = [Diagnostics.Stopwatch]::StartNew()
while ($swReadiness.Elapsed.TotalSeconds -lt 20) {
    if (Test-Path $readinessFile) {
        try {
            $rdata = Get-Content $readinessFile -Raw | ConvertFrom-Json
            if ($rdata -and ($rdata.gateway_pid -eq $gwPid)) {
                $epochId = $rdata.epoch_id
                $runtimeReadyAt = $rdata.runtime_ready_at
                if ($rdata.core_ready -eq $true) {
                    $coreReady = $true
                    $adapterReady = $true
                    break
                }
            }
        } catch {}
    }
    # Fallback log check while gateway initializes
    if (Test-Path $agentLog) {
        $logTail = Get-Content $agentLog -Tail 100
        if ($logTail -match "XiyueMRAdapter initialized") {
            $adapterReady = $true
        }
    }
    Start-Sleep -Milliseconds 500
}

if ($coreReady) {
    Write-Host "  MR Adapter: INITIALIZED"
    Write-Host "  MR Core:    READY"
    Write-Host ("  Epoch ID:   {0}" -f $epochId)
    Write-Host ("  Ready At:   {0}" -f $runtimeReadyAt)
} elseif ($adapterReady) {
    Write-Host "  MR Adapter: INITIALIZED (readiness pending)"
} else {
    Write-Warning "MR Adapter initialization pending."
}

# ------------------------------------------------------------------
# E. Start Observation Window (independent process on port 8766)
# ------------------------------------------------------------------
Write-Host "[5/5] Managing Observation Window..."

$owPort = 8766
$owPid = $null

if (Test-Path $owPidFile) {
    try {
        $candOw = [int](Get-Content $owPidFile -Raw -ErrorAction SilentlyContinue).Trim()
        $candProc = Get-Process -Id $candOw -ErrorAction SilentlyContinue
        if ($candProc -and (-not $candProc.HasExited)) {
            $owPid = $candOw
        }
    } catch {}
}

if (-not $owPid) {
    $existingOw = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match "observation_window\.web\.runtime" -and $_.CommandLine -match "8766"
    } | Select-Object -First 1
    if ($existingOw) {
        $owPid = $existingOw.ProcessId
    }
}

$owOutLog = Join-Path $runtimeDir "ow_stdout.log"
$owErrLog = Join-Path $runtimeDir "ow_stderr.log"

if ($owPid) {
    Write-Host "  Observation Window: ALREADY RUNNING (PID: $owPid)"
    if (-not (Test-Path (Split-Path $owPidFile))) {
        New-Item -ItemType Directory -Force -Path (Split-Path $owPidFile) | Out-Null
    }
    Set-Content -Path $owPidFile -Value $owPid
} else {
    Write-Host "  Starting Observation Window on port $owPort..."
    $pyExe = (Get-Command python).Source
    # OW-MULTI-AGENT-BINDING-PHASE01-V1: production OW composes through
    # binding discovery (SingleBindingRegistryAdapter -> BindingResolver).
    # The runtime dir anchors binding.json / readiness.json lookups only.
    $owCmd = "`"$pyExe`" -m observation_window.web.runtime --runtime-dir `"$runtimeDir`" --port $owPort"
    $owRes = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $owCmd
        CurrentDirectory = $repoRoot
    }
    $owPid = $owRes.ProcessId
    if (-not (Test-Path (Split-Path $owPidFile))) {
        New-Item -ItemType Directory -Force -Path (Split-Path $owPidFile) | Out-Null
    }
    Set-Content -Path $owPidFile -Value $owPid
    Write-Host "  Observation Window: STARTED (PID: $owPid)"
}

# ------------------------------------------------------------------
# F. Verify Observation Window health check
# ------------------------------------------------------------------
$healthUrl = "http://127.0.0.1:$owPort/api/health"
$healthOk = $false
$swHealth = [Diagnostics.Stopwatch]::StartNew()
while ($swHealth.Elapsed.TotalSeconds -lt 15) {
    try {
        $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 -ErrorAction Stop
        if ($resp.status -eq "ok") {
            $healthOk = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if (-not $healthOk) {
    Write-Warning "Observation Window health check failed on $healthUrl"
} else {
    Write-Host "  Health check ($healthUrl): PASS"
}

# ------------------------------------------------------------------
# G. Compute Bundle State and Final Summary
# ------------------------------------------------------------------
$gwAlive = $false
if ($gwPid) {
    $gwProcCheck = Get-Process -Id $gwPid -ErrorAction SilentlyContinue
    if ($gwProcCheck -and (-not $gwProcCheck.HasExited)) {
        $gwAlive = $true
    }
}

$bundleState = "NOT_READY"
if ($gwAlive -and $coreReady) {
    if ($healthOk) {
        $bundleState = "READY"
    } else {
        $bundleState = "DEGRADED"
    }
}

Write-Host ""
Write-Host "=================================================="
Write-Host ("Xiyue Runtime: {0}" -f $bundleState)
Write-Host "=================================================="
Write-Host ("Bundle State:           {0}" -f $bundleState)
Write-Host ("Supervisor PID:         {0}" -f $supervisorPid)
Write-Host ("Gateway PID:            {0}" -f $(if ($gwPid) { $gwPid } else { "-" }))
Write-Host ("MR Core:                {0}" -f $(if ($coreReady) { "READY" } else { "NOT_READY" }))
Write-Host ("Epoch ID:               {0}" -f $(if ($epochId) { $epochId } else { "-" }))
Write-Host ("Runtime Ready:          {0}" -f $(if ($runtimeReadyAt) { $runtimeReadyAt } else { "-" }))
Write-Host ("Observation Window PID: {0}" -f $(if ($owPid) { $owPid } else { "-" }))
Write-Host ("Observation Window URL: http://127.0.0.1:{0}/live-trace" -f $owPort)
Write-Host ("Runtime DB path:        {0}" -f $stateDbPath)
Write-Host "=================================================="

if ($bundleState -eq "NOT_READY") {
    Write-Error "Bundle readiness failed: state is NOT_READY"
    exit 1
}
