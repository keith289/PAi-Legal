$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "PAi Legal 0.9.7 verification" -ForegroundColor Cyan

$required = @(
    "pai_legal\app.py",
    "pai_legal\workspace.py",
    "pai_legal\commerce.py",
    "pai_legal\claims_handoff.py",
    "pai_legal\audit.py",
    "pai_legal\governance.py",
    "pai_legal\security.py",
    "store-bridge\Program.cs",
    "store-bridge\Build-StoreBridge.ps1",
    "Assets\StoreLogo.png",
    "Assets\Square150x150Logo.png",
    "Assets\Square44x44Logo.png"
)
foreach ($item in $required) {
    if (-not (Test-Path (Join-Path $PSScriptRoot $item))) { throw "Missing required 0.9.7 file: $item" }
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3.12 -m py_compile `
        "$PSScriptRoot\pai_legal\commerce.py" `
        "$PSScriptRoot\pai_legal\claims_handoff.py" `
        "$PSScriptRoot\pai_legal\workspace.py" `
        "$PSScriptRoot\pai_legal\app.py"
    if ($LASTEXITCODE -ne 0) { throw "Python syntax verification failed." }

    & py -3.12 -m unittest discover -s "$PSScriptRoot\tests" -p "test_*097.py" -v
    if ($LASTEXITCODE -ne 0) { throw "PAi Legal 0.9.7 commerce/handoff tests failed." }
} else {
    & python -m py_compile `
        "$PSScriptRoot\pai_legal\commerce.py" `
        "$PSScriptRoot\pai_legal\claims_handoff.py" `
        "$PSScriptRoot\pai_legal\workspace.py" `
        "$PSScriptRoot\pai_legal\app.py"
    if ($LASTEXITCODE -ne 0) { throw "Python syntax verification failed." }
    & python -m unittest discover -s "$PSScriptRoot\tests" -p "test_*097.py" -v
    if ($LASTEXITCODE -ne 0) { throw "PAi Legal 0.9.7 commerce/handoff tests failed." }
}

$workspaceText = Get-Content "$PSScriptRoot\pai_legal\workspace.py" -Raw
if ($workspaceText -notmatch 'begin_new_case') { throw "Commerce gate is not connected to Workspace.create_case." }
if ($workspaceText -notmatch 'open_claims_workspace') { throw "Claims Parliament handoff is not connected." }
if ($workspaceText -notmatch '_create_case_unmetered') { throw "0.9.6 create_case implementation was not preserved under the wrapper." }


$pyprojectText = Get-Content "$PSScriptRoot\pyproject.toml" -Raw
if ($pyprojectText -notmatch '(?m)^version\s*=\s*"0\.9\.7"\s*$') { throw "pyproject.toml was not bumped to 0.9.7." }

$releaseBuildText = Get-Content "$PSScriptRoot\BUILD_PAI_LEGAL_097.ps1" -Raw
if ($releaseBuildText -notmatch 'build_windows\.ps1"\s+-Version\s+"0\.9\.7\.0"') {
    throw "Release builder does not explicitly pass -Version 0.9.7.0."
}

$buildText = Get-Content "$PSScriptRoot\build_windows.ps1" -Raw
if ($buildText -notmatch '\$StoreBridgeExe;store-bridge') { throw "Store bridge is not included in build_windows.ps1." }

$handoffText = Get-Content "$PSScriptRoot\pai_legal\claims_handoff.py" -Raw
if ($handoffText -notmatch 'PAi Claims 1\.3\.2 or later') { throw "Stale Claims graph refusal guard is missing." }
$commerceText = Get-Content "$PSScriptRoot\pai_legal\commerce.py" -Raw
if ($commerceText -notmatch 'ANNUAL_CACHE_GRACE') { throw "Bounded annual cache grace is missing." }
if ($commerceText -notmatch 'annual_clock_floor_at') { throw "Clock rollback guard is missing." }

Write-Host "Source verification complete." -ForegroundColor Green
Write-Host "Next: .\BUILD_PAI_LEGAL_097.ps1" -ForegroundColor Green
Write-Host "Real Microsoft purchases must be tested from the installed packaged/Store build." -ForegroundColor Yellow
