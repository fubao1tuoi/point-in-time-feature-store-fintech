param(
    [ValidateSet("2GB", "4GB", "8GB", "16GB")]
    [string]$MemoryLimit = "4GB",
    [ValidateRange(1, 64)]
    [int]$Threads = 4,
    [switch]$SkipProfiling
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project .venv was not found. Create it and install the package first."
}

$RequiredRawFiles = @(
    "data\raw\train_transaction.csv",
    "data\raw\train_identity.csv",
    "data\raw\test_transaction.csv",
    "data\raw\test_identity.csv"
)
$MissingRawFiles = $RequiredRawFiles | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf)
}
if ($MissingRawFiles.Count -gt 0) {
    throw "Missing raw files: $($MissingRawFiles -join ', ')"
}

$ImmutableOrCanonicalOutputs = @(
    "data\bronze\train_transaction\data.parquet",
    "data\silver\transactions",
    "data\offline_store\transaction_features\v1",
    "artifacts\preprocessing\v1\preprocessor.json",
    "data\training\model_dataset\v1",
    "models\fraud_detection\v1",
    "reports\generated\model_evaluation\v1",
    "reports\generated\milestone_seven\v1",
    "reports\generated\hardening\v1"
)
$ExistingOutputs = $ImmutableOrCanonicalOutputs | Where-Object {
    Test-Path -LiteralPath (Join-Path $ProjectRoot $_)
}
if ($ExistingOutputs.Count -gt 0) {
    throw "This runner requires a clean workspace. Existing outputs: $($ExistingOutputs -join ', ')"
}

$script:Stage = 0
$TotalStages = if ($SkipProfiling) { 14 } else { 15 }

function Invoke-PythonStage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )
    $script:Stage += 1
    Write-Host "[$($script:Stage.ToString('00'))/$TotalStages] $Name" -ForegroundColor Cyan
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Stage failed ($LASTEXITCODE): $Name"
    }
}

if (-not $SkipProfiling) {
    Invoke-PythonStage "Dataset profiling" @("pipelines/profile_dataset.py")
}
Invoke-PythonStage "Entity-key analysis" @("pipelines/analyze_entity_keys.py")
Invoke-PythonStage "Bronze ingestion" @(
    "pipelines/ingest_bronze.py", "--progress-every-rows", "100000"
)
Invoke-PythonStage "Silver transformation" @(
    "pipelines/build_silver.py", "--memory-limit", $MemoryLimit, "--threads", "$Threads"
)
Invoke-PythonStage "Feature Registry validation" @(
    "pipelines/validate_feature_registry.py"
)
Invoke-PythonStage "Offline PIT feature materialization" @(
    "pipelines/materialize_offline_features.py", "--feature-table-version", "1"
)
Invoke-PythonStage "Temporal split audit" @("pipelines/analyze_temporal_split.py")
Invoke-PythonStage "Train-only preprocessing fit" @("pipelines/fit_preprocessor.py")
Invoke-PythonStage "Training dataset materialization" @(
    "pipelines/build_training_dataset.py"
)
Invoke-PythonStage "Raw and raw-plus-PIT model training" @(
    "pipelines/train_baseline_models.py"
)
Invoke-PythonStage "Model evaluation" @("pipelines/evaluate_baseline_models.py")
Invoke-PythonStage "Milestone 7 reproducibility release" @(
    "pipelines/complete_milestone_seven.py"
)
Invoke-PythonStage "Milestone 8 hardening audit" @("pipelines/run_hardening_audit.py")
Invoke-PythonStage "Full test suite" @("-m", "pytest")
Invoke-PythonStage "Ruff lint" @("-m", "ruff", "check", ".")

Write-Host "[end-to-end] success" -ForegroundColor Green
