# =============================================================================
#  run_alpha_sweep.ps1
#  Load Balancing Project -- Heavy-Tail (Alpha) Sweep  [Sweep 2]
#
#  USAGE:
#    powershell -ExecutionPolicy Bypass -File .\run_alpha_sweep.ps1
#
#  This script manages everything automatically:
#    - Edits ALPHA in config.py before each group
#    - Starts the servers (python main.py)
#    - Runs all 5 policies for that alpha
#    - Stops the servers
#    - Moves to the next alpha value
#    - Restores config.py to ALPHA = 1.3 when done
#
#  Do NOT start servers manually before running this script.
#
#  All CSVs  -> data\
#  All plots -> notebooks\figures\
# =============================================================================

$ErrorActionPreference = "Stop"
$PYTHON        = "python"
$DISPATCHER    = "src\dispatcher.py"
$CONFIG        = "config.py"
$MAIN          = "main.py"
$DEFAULT_ALPHA = 1.3

$POLICIES = @("random", "round_robin", "jsq", "lwl", "sita")

function Write-Header($msg) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}
function Write-Step($msg)  { Write-Host "  >> $msg" -ForegroundColor Yellow    }
function Write-OK($msg)    { Write-Host "  [OK]   $msg" -ForegroundColor Green    }
function Write-Skip($msg)  { Write-Host "  [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Warn($msg)  { Write-Host "  [WARN] $msg" -ForegroundColor DarkYellow }

$START_TIME = Get-Date
Write-Host ""
Write-Host "  Load Balancing -- Heavy-Tail (Alpha) Sweep" -ForegroundColor White
Write-Host "  Sweep 2: alpha in {1.1, 1.3, 1.5, 2.0, 3.0}  |  lam=10  |  bounded_pareto" -ForegroundColor DarkGray
Write-Host "  Started: $($START_TIME.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor DarkGray
Write-Host ""

New-Item -ItemType Directory -Force -Path "data" | Out-Null

$completed     = 0
$skipped       = 0
$failed        = 0
$serverProcess = $null

# ---------------------------------------------------------------------------
# Edit ALPHA in config.py
# ---------------------------------------------------------------------------
function Set-Alpha {
    param([double]$Alpha)
    $content = Get-Content $CONFIG -Raw
    $content = $content -replace '(?m)^ALPHA\s*=\s*[\d.]+', "ALPHA = $Alpha"
    Set-Content $CONFIG -Value $content -NoNewline
    Write-Step "config.py updated: ALPHA = $Alpha"
}

# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------
function Start-Servers {
    Write-Step "Starting servers (python $MAIN)..."
    $script:serverProcess = Start-Process -FilePath $PYTHON `
                                          -ArgumentList $MAIN `
                                          -PassThru `
                                          -WindowStyle Normal
    $ports   = @(5001, 5002, 5003)
    $timeout = 30
    $start   = Get-Date
    foreach ($port in $ports) {
        $ready = $false
        while (-not $ready) {
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" `
                                          -UseBasicParsing -TimeoutSec 1
                if ($resp.StatusCode -eq 200) { $ready = $true }
            } catch { }
            if (-not $ready) {
                if (((Get-Date) - $start).TotalSeconds -gt $timeout) {
                    throw "Server on port $port did not become ready within ${timeout}s"
                }
                Start-Sleep -Milliseconds 300
            }
        }
    }
    Write-OK "All 3 servers ready (ports 5001 5002 5003)"
}

function Stop-Servers {
    if ($null -ne $script:serverProcess -and -not $script:serverProcess.HasExited) {
        Write-Step "Stopping servers (PID $($script:serverProcess.Id))..."
        Stop-Process -Id $script:serverProcess.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Write-OK "Servers stopped"
    }
    $script:serverProcess = $null
}

# ---------------------------------------------------------------------------
# Run one dispatcher experiment
# ---------------------------------------------------------------------------
function Run-Experiment {
    param(
        [string]$Policy,
        [double]$Lam,
        [int]$N,
        [double]$Alpha,
        [string]$Tag = "alphasweep"
    )

    $fname   = "${Policy}_lam${Lam}_alpha${Alpha}_${Tag}.csv"
    $outPath = "data\$fname"

    if (Test-Path $outPath) {
        Write-Skip "$fname already exists -- delete to re-run"
        $script:skipped++
        return
    }

    Write-Step "policy=$Policy  lam=$Lam  n=$N  alpha=$Alpha"

    $cmdArgs = @(
        $DISPATCHER,
        "--policy",    $Policy,
        "--lam",       $Lam,
        "--n",         $N,
        "--alpha",     $Alpha,
        "--size-dist", "bounded_pareto",
        "--x-min",     1.0,
        "--x-max",     50.0,
        "--alpha-x",   1.5,
        "--out",       $outPath
    )

    try {
        & $PYTHON @cmdArgs
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        Write-OK "$fname"
        $script:completed++
    } catch {
        Write-Host "  [FAIL] $fname -- $_" -ForegroundColor Red
        $script:failed++
    }
}

# =============================================================================
# SWEEP 2 -- HEAVY-TAIL (ALPHA) SWEEP
# Goal   : Show how alpha changes tail behavior and policy rankings.
#          Answers "Different heavy-tail parameters" and
#                  "Analysis of tail behavior".
# Fixed  : lam=10, size_dist=bounded_pareto, x in [1,50]
# Varied : ALPHA in config.py
#
# alpha=1.1 -> very heavy tail; extreme stragglers frequent  (N=500, slow)
# alpha=1.3 -> project default
# alpha=1.5 -> moderately heavy tail
# alpha=2.0 -> light tail
# alpha=3.0 -> near-exponential; almost no stragglers
# =============================================================================

$alphaScenarios = @(
    @{ Alpha=1.1; N=500  },
    @{ Alpha=1.3; N=1000 },
    @{ Alpha=1.5; N=1000 },
    @{ Alpha=2.0; N=1000 },
    @{ Alpha=3.0; N=1000 }
)

foreach ($sc in $alphaScenarios) {
    Write-Header "SWEEP 2 -- alpha=$($sc.Alpha)  N=$($sc.N)  lam=10"
    Stop-Servers
    Set-Alpha -Alpha $sc.Alpha
    Start-Servers
    foreach ($pol in $POLICIES) {
        Run-Experiment -Policy $pol -Lam 10 -N $sc.N -Alpha $sc.Alpha
    }
}

# ---------------------------------------------------------------------------
# Cleanup: stop servers and restore config.py
# ---------------------------------------------------------------------------
Stop-Servers

Write-Step "Restoring config.py to ALPHA = $DEFAULT_ALPHA ..."
Set-Alpha -Alpha $DEFAULT_ALPHA
Write-OK "config.py restored to ALPHA = $DEFAULT_ALPHA"

# =============================================================================
# PLOTTING
# =============================================================================
Write-Header "Plotting Results"

Write-Step "Running plot_results.py..."
try {
    & $PYTHON "notebooks\plot_results.py" --data "data" --out "notebooks\figures"
    Write-OK "Plots saved to notebooks\figures\"
} catch {
    Write-Warn "plot_results.py failed: $_"
    Write-Host "         Run manually: python notebooks\plot_results.py" -ForegroundColor DarkGray
}

# =============================================================================
# SUMMARY
# =============================================================================
$END_TIME   = Get-Date
$ELAPSED    = $END_TIME - $START_TIME
$elapsedStr = "{0:D2}h {1:D2}m {2:D2}s" -f $ELAPSED.Hours, $ELAPSED.Minutes, $ELAPSED.Seconds

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  ALPHA SWEEP COMPLETE" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Completed : $completed" -ForegroundColor Green
Write-Host "  Skipped   : $skipped  (CSV already existed)" -ForegroundColor DarkGray
Write-Host "  Failed    : $failed"    -ForegroundColor $(if ($failed -gt 0) {"Red"} else {"Green"})
Write-Host "  Total time: $elapsedStr" -ForegroundColor White
Write-Host ""
Write-Host "  CSV files  -> data\" -ForegroundColor White
Write-Host "  PNG plots  -> notebooks\figures\" -ForegroundColor White
Write-Host "  config.py  -> ALPHA restored to $DEFAULT_ALPHA" -ForegroundColor DarkGray
Write-Host ""
