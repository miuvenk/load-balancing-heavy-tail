# =============================================================================
#  generate_plots.ps1
#  Load Balancing Project -- Plot Generation per Sweep
#  Ca' Foscari University -- Software Performance and Scalability
#
#  USAGE:
#    powershell -ExecutionPolicy Bypass -File .\generate_plots.ps1
#
#  Organizes CSVs by sweep and generates separate plot sets for each:
#    notebooks\figures\sweep1_load\
#    notebooks\figures\sweep2_alpha\
#    notebooks\figures\sweep3_dist\
#    notebooks\figures\sweep4_stress\
#    notebooks\figures\sweep4_bottleneck\
#    notebooks\figures\sweep5_worstcase\
# =============================================================================

$ErrorActionPreference = "Stop"
$PYTHON  = "python"
$PLOTTER = "notebooks\plot_results.py"
$DATA    = "data"
$FIGS    = "notebooks\figures"

function Write-Header($msg) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}
function Write-Step($msg) { Write-Host "  >> $msg" -ForegroundColor Yellow }
function Write-OK($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor DarkYellow }

Write-Host ""
Write-Host "  Load Balancing -- Plot Generation" -ForegroundColor White
Write-Host "  Generating one figure set per sweep" -ForegroundColor DarkGray
Write-Host ""

# ---------------------------------------------------------------------------
# Helper: copy matching CSVs to a temp folder, run plotter, remove temp
# ---------------------------------------------------------------------------
function Plot-Sweep {
    param(
        [string]$SweepName,
        [string]$OutDir,
        [string[]]$Patterns     # filename glob patterns to include
    )

    Write-Header "Plotting $SweepName"

    # Create temp data dir
    $tmpDir = "data\_tmp_$SweepName"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

    # Copy matching files
    $copied = 0
    foreach ($pat in $Patterns) {
        $files = Get-ChildItem -Path $DATA -Filter $pat -File 2>$null
        foreach ($f in $files) {
            Copy-Item $f.FullName -Destination $tmpDir -Force
            $copied++
        }
    }

    if ($copied -eq 0) {
        Write-Warn "No CSV files matched for $SweepName -- skipping"
        Remove-Item $tmpDir -Recurse -Force
        return
    }

    Write-Step "$copied CSV files copied for $SweepName"

    # Create output dir
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

    # Run plotter
    try {
        & $PYTHON $PLOTTER --data $tmpDir --out $OutDir
        Write-OK "Plots saved to $OutDir"
    } catch {
        Write-Warn "plot_results.py failed for ${SweepName}: $_"
    }

    # Cleanup temp
    Remove-Item $tmpDir -Recurse -Force
}

# =============================================================================
# SWEEP 1 -- Load Sweep
# Files: *_lam{2,5,8,12,15,18,22}_alpha1.3.csv  (no tag suffix)
# =============================================================================
Plot-Sweep -SweepName "sweep1_load" `
           -OutDir "$FIGS\sweep1_load" `
           -Patterns @(
               "random_lam2_alpha1.3.csv",
               "round_robin_lam2_alpha1.3.csv",
               "jsq_lam2_alpha1.3.csv",
               "lwl_lam2_alpha1.3.csv",
               "sita_lam2_alpha1.3.csv",
               "random_lam5_alpha1.3.csv",
               "round_robin_lam5_alpha1.3.csv",
               "jsq_lam5_alpha1.3.csv",
               "lwl_lam5_alpha1.3.csv",
               "sita_lam5_alpha1.3.csv",
               "random_lam8_alpha1.3.csv",
               "round_robin_lam8_alpha1.3.csv",
               "jsq_lam8_alpha1.3.csv",
               "lwl_lam8_alpha1.3.csv",
               "sita_lam8_alpha1.3.csv",
               "random_lam12_alpha1.3.csv",
               "round_robin_lam12_alpha1.3.csv",
               "jsq_lam12_alpha1.3.csv",
               "lwl_lam12_alpha1.3.csv",
               "sita_lam12_alpha1.3.csv",
               "random_lam15_alpha1.3.csv",
               "round_robin_lam15_alpha1.3.csv",
               "jsq_lam15_alpha1.3.csv",
               "lwl_lam15_alpha1.3.csv",
               "sita_lam15_alpha1.3.csv",
               "random_lam18_alpha1.3.csv",
               "round_robin_lam18_alpha1.3.csv",
               "jsq_lam18_alpha1.3.csv",
               "lwl_lam18_alpha1.3.csv",
               "sita_lam18_alpha1.3.csv",
               "random_lam22_alpha1.3.csv",
               "round_robin_lam22_alpha1.3.csv",
               "jsq_lam22_alpha1.3.csv",
               "lwl_lam22_alpha1.3.csv",
               "sita_lam22_alpha1.3.csv"
           )

# =============================================================================
# SWEEP 2 -- Alpha Sweep (one sub-folder per alpha value)
# Files: *_lam10_alpha{1.1,1.3,1.5,2,3}_alphasweep.csv
# =============================================================================
$alphaValues = @("1.1", "1.3", "1.5", "2", "3")
foreach ($a in $alphaValues) {
    Plot-Sweep -SweepName "sweep2_alpha${a}" `
               -OutDir "$FIGS\sweep2_alpha\alpha${a}" `
               -Patterns @("*_lam10_alpha${a}_alphasweep.csv")
}

# Also one combined folder for all alphas together (cross-policy comparison)
Plot-Sweep -SweepName "sweep2_alpha_all" `
           -OutDir "$FIGS\sweep2_alpha\all" `
           -Patterns @("*_alphasweep.csv")

# =============================================================================
# SWEEP 3 -- Size Distribution Sweep
# Files: *_lam10_alpha1.3_{bounded_pareto,uniform,exponential,fixed}.csv
# =============================================================================
$distTags = @("bounded_pareto", "uniform", "exponential", "fixed")
foreach ($d in $distTags) {
    Plot-Sweep -SweepName "sweep3_dist_$d" `
               -OutDir "$FIGS\sweep3_dist\$d" `
               -Patterns @("*_lam10_alpha1.3_${d}.csv")
}

Plot-Sweep -SweepName "sweep3_dist_all" `
           -OutDir "$FIGS\sweep3_dist\all" `
           -Patterns @(
               "*_lam10_alpha1.3_bounded_pareto.csv",
               "*_lam10_alpha1.3_uniform.csv",
               "*_lam10_alpha1.3_exponential.csv",
               "*_lam10_alpha1.3_fixed.csv"
           )

# =============================================================================
# SWEEP 4 -- Bottleneck Sweep (one sub-folder per lambda)
# Files: *_lam{40,60,75,100,120,135,147}_alpha1.3_bottleneck.csv
# =============================================================================
$bottleneckLams = @("40", "60", "75", "100", "120", "135", "147")
foreach ($l in $bottleneckLams) {
    Plot-Sweep -SweepName "sweep4_bottleneck_lam$l" `
               -OutDir "$FIGS\sweep4_bottleneck\lam$l" `
               -Patterns @("*_lam${l}_alpha1.3_bottleneck.csv")
}

Plot-Sweep -SweepName "sweep4_bottleneck_all" `
           -OutDir "$FIGS\sweep4_bottleneck\all" `
           -Patterns @("*_bottleneck.csv")

# =============================================================================
# SWEEP 4 -- Saturation Stress Test (from run_experiments.ps1)
# Files: *_lam{25,30}_alpha1.3_stress.csv
# =============================================================================
Plot-Sweep -SweepName "sweep4_stress" `
           -OutDir "$FIGS\sweep4_stress" `
           -Patterns @("*_stress.csv")

# =============================================================================
# SWEEP 5 -- Worst Case
# Files: *_lam15_alpha1.3_worstcase.csv
# =============================================================================
Plot-Sweep -SweepName "sweep5_worstcase" `
           -OutDir "$FIGS\sweep5_worstcase" `
           -Patterns @("*_worstcase.csv")

# =============================================================================
# SUMMARY
# =============================================================================
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  ALL PLOTS GENERATED" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Output structure:" -ForegroundColor White
Write-Host "    notebooks\figures\sweep1_load\              <- load sweep"           -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep2_alpha\alpha1.1\    <- alpha=1.1"            -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep2_alpha\all\         <- all alphas combined"  -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep3_dist\uniform\      <- dist per type"        -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep3_dist\all\          <- all dists combined"   -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep4_stress\            <- lam=25,30 stress"     -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep4_bottleneck\lam100\ <- bottleneck per lam"   -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep4_bottleneck\all\    <- all lams combined"    -ForegroundColor DarkGray
Write-Host "    notebooks\figures\sweep5_worstcase\         <- worst case"           -ForegroundColor DarkGray
Write-Host ""
