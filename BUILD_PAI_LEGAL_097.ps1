$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:PAI_LEGAL_IDENTITY_NAME) {
    $env:PAI_LEGAL_IDENTITY_NAME = "PAiLuton.PAiLegal"
}
if (-not $env:PAI_LEGAL_PUBLISHER) {
    $env:PAI_LEGAL_PUBLISHER = "CN=D7A83BB4-9693-4195-82DE-2A76C46F6F0F"
}

Write-Host "1/3 Verifying PAi Legal 0.9.7 source" -ForegroundColor Cyan
& "$PSScriptRoot\VERIFY_097.ps1"

Write-Host "2/3 Building PAi Legal 0.9.7 Store package" -ForegroundColor Cyan
& "$PSScriptRoot\build_windows.ps1" -Version "0.9.7.0"

$package = Join-Path $PSScriptRoot "dist\PAiLegal_0.9.7.0_x64.msix"
if (-not (Test-Path $package)) { throw "Expected package was not created: $package" }

Write-Host "3/3 Build complete" -ForegroundColor Green
Write-Host "Package: $package" -ForegroundColor Green
Write-Host "Upload this MSIX to the EXISTING PAi Legal product in Partner Center." -ForegroundColor Green
