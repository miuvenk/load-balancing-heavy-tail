# =============================================================================
#  run_experiments.ps1
#  Load Balancing Project -- Main Experiment Suite (Sweeps 1, 3, 4, 5)
#
#  USAGE:
#    1. Set ALPHA = 1.3 in config.py  (should already be the default)
#    2. Start the servers:   python main.py
#    3. Open a new terminal and run:   powershell -ExecutionPolicy Bypass -File .\run_experiments.ps1
#    4. When done, stop the servers with Ctrl+C.
#
#  NOTE: The heavy-tail (alpha) sweep is in run_alpha_sweep.ps1
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
Write-Host "  Load Balancing -- Main Experiment Suite" -ForegroundColor White
Write-Host "  Sweeps: 1 (Load)  3 (Size dist)  4 (Saturation) " -ForegroundColor DarkGray
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
        [string]$Tag      = ""
    )

    $fname   = "${Policy}_lam${Lam}_alpha${Alpha}"
    if ($Tag -ne "") { $fname += "_${Tag}" }
    $fname  += ".csv"
    $outPath = "data\$fname"

    if (Test-Path $outPath) {
        Write-Skip "$fname already exists -- delete to re-run"
        $script:skipped++
        return
    }

    Write-Step "policy=$Policy  lam=$Lam  n=$N  alpha=$Alpha  dist=$SizeDist  tag=$Tag"

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
# SWEEP 1 -- LOAD SWEEP
# Goal   : Compare policy performance across a wide range of arrival rates.
#          Directly answers "Low vs high system load".
# Fixed  : alpha=1.3, size_dist=bounded_pareto, x in [1,50]
# Varied : lambda (requests/second)
# =============================================================================
Write-Header "SWEEP 1 -- Load Sweep  (alpha=1.3, bounded_pareto, x in [1,50])"

$loadScenarios = @(
    @{ Lam=2;  N=500  },
    @{ Lam=5;  N=500  },
    @{ Lam=8;  N=1000 },
    @{ Lam=12; N=1000 },
    @{ Lam=15; N=2000 },
    @{ Lam=18; N=2000 },
    @{ Lam=22; N=2000 }
)

foreach ($sc in $loadScenarios) {
    foreach ($pol in $POLICIES) {
        Run-Experiment -Policy $pol -Lam $sc.Lam -N $sc.N
    }
}

# =============================================================================
# SWEEP 3 -- SIZE DISTRIBUTION SWEEP
# Goal   : Isolate the effect of x variability on policy performance.
#          Answers "Why do heavy-tailed tasks make load balancing difficult?"
# Fixed  : lam=10, alpha=1.3, N=1000
# Varied : size_dist
# =============================================================================
Write-Header "SWEEP 3 -- Size Distribution Sweep  (lam=10, alpha=1.3, N=1000)"

$distScenarios = @(
    @{ Dist="bounded_pareto"; XMin=1.0; XMax=50.0; AlphaX=1.5 },
    @{ Dist="uniform";        XMin=1.0; XMax=50.0; AlphaX=1.5 },
    @{ Dist="exponential";    XMin=1.0; XMax=50.0; AlphaX=1.5 },
    @{ Dist="fixed";          XMin=1.0; XMax=50.0; AlphaX=1.5 }
)

foreach ($sc in $distScenarios) {
    foreach ($pol in $POLICIES) {
        Run-Experiment -Policy $pol -Lam 10 -N 1000 -Alpha 1.3 `
                       -SizeDist $sc.Dist -XMin $sc.XMin -XMax $sc.XMax -AlphaX $sc.AlphaX `
                       -Tag $sc.Dist
    }
}

# =============================================================================
# SWEEP 4 -- SATURATION STRESS TEST
# Goal   : Push the system beyond capacity, observe policy degradation.
#          Answers "How do stragglers affect system performance?"
# Fixed  : alpha=1.3, bounded_pareto, N=2000
# Varied : lambda (very high)
# WARNING: Can take a very long time. Ctrl+C is safe if needed.
# =============================================================================
Write-Header "SWEEP 4 -- Saturation Stress Test  (alpha=1.3, bounded_pareto, N=2000)"

$satScenarios = @(25, 30)

foreach ($lam in $satScenarios) {
    foreach ($pol in $POLICIES) {
        Run-Experiment -Policy $pol -Lam $lam -N 2000 -Tag "stress"
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
Write-Host "  MAIN SUITE COMPLETE" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Completed : $completed" -ForegroundColor Green
Write-Host "  Skipped   : $skipped  (CSV already existed)" -ForegroundColor DarkGray
Write-Host "  Failed    : $failed"    -ForegroundColor $(if ($failed -gt 0) {"Red"} else {"Green"})
Write-Host "  Total time: $elapsedStr" -ForegroundColor White
Write-Host ""
Write-Host "  CSV files -> data\          PNG plots -> notebooks\figures\" -ForegroundColor White
Write-Host ""
Write-Host "  Next step: run run_alpha_sweep.ps1 for the heavy-tail sweep." -ForegroundColor DarkGray
Write-Host ""
