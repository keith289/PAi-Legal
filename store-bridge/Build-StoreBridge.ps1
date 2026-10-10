$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Building PAiLegal.StoreBridge.exe..." -ForegroundColor Cyan

$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if ($dotnet) {
    & dotnet build -c Release
} else {
    Write-Host "dotnet SDK not found. Skipping compilation step." -ForegroundColor Yellow
}
