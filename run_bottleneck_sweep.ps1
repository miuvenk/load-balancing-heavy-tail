# =============================================================================
#  run_bottleneck_sweep.ps1
#  Load Balancing Project -- Bottleneck / Saturation Sweep
#
#  USAGE:
#    1. Start the servers:   python main.py
#    2. Open a new terminal and run:
#       powershell -ExecutionPolicy Bypass -File .\run_bottleneck_sweep.ps1
#    3. When done, stop the servers with Ctrl+C.
#
#  WHY THIS SWEEP EXISTS:
#    The main sweep (lam=2..30) only reaches rho~0.20 utilization.
#    The theoretical system capacity is ~147 req/s (3 servers x ~49 req/s each,
#    derived from mean service time ~20ms observed at low load).
#    This sweep drives lambda from rho=0.5 up through saturation to find
#    the exact point where each policy breaks down.
#
#  ESTIMATED DURATIONS (per run, N=2000):
#    lam=40-75   -> ~45-60s each   (light-moderate queue)
#    lam=100     -> ~30-40s each   (heavy queue starting)
#    lam=120     -> ~25-35s each   (near saturation)
#    lam=135-147 -> may be slow for random/round_robin/sita
#
#  All CSVs  -> data\
#  All plots -> notebooks\figures\
# =============================================================================

$ErrorActionPreference = "Stop"
$PYTHON     = "python"
$DISPATCHER = "src\dispatcher.py"

$POLICIES = @("random", "round_robin", "jsq", "lwl", "sita")

function Write-Header($msg) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}
function Write-Step($msg)  { Write-Host "  >> $msg" -ForegroundColor Yellow   }
function Write-OK($msg)    { Write-Host "  [OK]   $msg" -ForegroundColor Green   }
function Write-Skip($msg)  { Write-Host "  [SKIP] $msg" -ForegroundColor DarkGray }

$START_TIME = Get-Date
Write-Host ""
Write-Host "  Load Balancing -- Bottleneck Sweep" -ForegroundColor White
Write-Host "  System capacity: ~147 req/s  |  alpha=1.3  |  bounded_pareto" -ForegroundColor DarkGray
Write-Host "  lambda range: 40 -> 147  (rho: 0.27 -> ~1.0)" -ForegroundColor DarkGray
Write-Host "  Started: $($START_TIME.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor DarkGray
Write-Host ""

New-Item -ItemType Directory -Force -Path "data" | Out-Null

$completed = 0
$skipped   = 0
$failed    = 0

function Run-Experiment {
    param(
        [string]$Policy,
        [double]$Lam,
        [int]$N,
        [double]$Alpha    = 1.3,
        [string]$SizeDist = "bounded_pareto",
        [double]$XMin     = 1.0,
        [double]$XMax     = 50.0,
        [double]$AlphaX   = 1.5,
        [string]$Tag      = "bottleneck"
    )

    $fname   = "${Policy}_lam${Lam}_alpha${Alpha}_${Tag}.csv"
    $outPath = "data\$fname"

    if (Test-Path $outPath) {
        Write-Skip "$fname already exists -- delete to re-run"
        $script:skipped++
        return
    }

    Write-Step "policy=$Policy  lam=$Lam  n=$N  rho~$([math]::Round($Lam/147.0, 2))"

    $cmdArgs = @(
        $DISPATCHER,
        "--policy",    $Policy,
        "--lam",       $Lam,
        "--n",         $N,
        "--alpha",     $Alpha,
        "--size-dist", $SizeDist,
        "--x-min",     $XMin,
        "--x-max",     $XMax,
        "--alpha-x",   $AlphaX,
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
# BOTTLENECK SWEEP
#
# Theoretical background:
#   Mean service time  ~ 20ms  (observed at lam=2, negligible queue)
#   Capacity per server (mu)   ~ 49 req/s
#   Total system capacity      ~ 147 req/s  (3 x mu)
#   Utilization  rho = lam / 147
#
# Lambda selection:
#   lam=40   rho=0.27  -> low utilization, stable for all policies
#   lam=60   rho=0.41  -> moderate load
#   lam=75   rho=0.51  -> half capacity
#   lam=100  rho=0.68  -> high load, queues grow noticeably
#   lam=120  rho=0.82  -> heavy load, random/sita start struggling
#   lam=135  rho=0.92  -> near saturation (90% target)
#   lam=147  rho=1.00  -> theoretical saturation point
#
# N=2000 throughout for reliable p99 (20 data points above p99).
# =============================================================================

Write-Header "BOTTLENECK SWEEP  (alpha=1.3, bounded_pareto, N=2000)"
Write-Host "  Theoretical saturation: lam=147 req/s  (rho=1.0)" -ForegroundColor DarkGray
Write-Host "  90pct utilization at:   lam=132 req/s  (rho=0.90)" -ForegroundColor DarkGray
Write-Host ""

$bottleneckScenarios = @(
    @{ Lam=40;  Rho="0.27" },   # low-moderate  -- first step above existing data
    @{ Lam=60;  Rho="0.41" },   # moderate
    @{ Lam=75;  Rho="0.51" },   # half capacity
    @{ Lam=100; Rho="0.68" },   # high load
    @{ Lam=120; Rho="0.82" },   # heavy load -- random/sita likely degrading
    @{ Lam=135; Rho="0.92" },   # near saturation
    @{ Lam=147; Rho="~1.0" }    # theoretical saturation point
)

foreach ($sc in $bottleneckScenarios) {
    Write-Host ""
    Write-Host "  --- lam=$($sc.Lam)  rho=$($sc.Rho) ---" -ForegroundColor DarkGray
    foreach ($pol in $POLICIES) {
        Run-Experiment -Policy $pol -Lam $sc.Lam -N 2000
    }
}

# =============================================================================
# PLOTTING
# =============================================================================
Write-Header "Plotting Results"

Write-Step "Running plot_results.py..."
try {
    & $PYTHON "notebooks\plot_results.py" --data "data" --out "notebooks\figures"
    Write-OK "Plots saved to notebooks\figures\"
} catch {
    Write-Host "  [WARN] plot_results.py failed: $_" -ForegroundColor DarkYellow
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
Write-Host "  BOTTLENECK SWEEP COMPLETE" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Completed : $completed" -ForegroundColor Green
Write-Host "  Skipped   : $skipped  (CSV already existed)" -ForegroundColor DarkGray
Write-Host "  Failed    : $failed"    -ForegroundColor $(if ($failed -gt 0) {"Red"} else {"Green"})
Write-Host "  Total time: $elapsedStr" -ForegroundColor White
Write-Host ""
Write-Host "  CSV files -> data\          PNG plots -> notebooks\figures\" -ForegroundColor White
Write-Host ""
