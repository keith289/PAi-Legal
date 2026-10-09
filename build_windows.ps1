param(
    [string]$Version = "1.0.0.0",
    [string]$IdentityName = $env:PAI_LEGAL_IDENTITY_NAME,
    [string]$Publisher = $env:PAI_LEGAL_PUBLISHER,
    [string]$TesseractDir = $env:PAI_LEGAL_TESSERACT_DIR,
    [string]$LlamaCppDir = $env:PAI_LEGAL_LLAMACPP_DIR
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path

$StoreBridgeBuild = Join-Path $Project "store-bridge\Build-StoreBridge.ps1"
if (-not (Test-Path $StoreBridgeBuild)) { throw "PAi Legal Store bridge build script is missing." }
& $StoreBridgeBuild
$StoreBridgeExe = Join-Path $Project "store-bridge\bin\PAiLegal.StoreBridge.exe"
if (-not (Test-Path $StoreBridgeExe)) { throw "PAi Legal Store bridge did not compile." }
$Venv = Join-Path $Project ".venv"
$Stage = Join-Path $Project "build\msix"
$Dist = Join-Path $Project "dist"

if (-not $IdentityName -or -not $Publisher) {
    throw "Reserve PAi Legal in Partner Center, then set PAI_LEGAL_IDENTITY_NAME and PAI_LEGAL_PUBLISHER from Product identity."
}

if (-not $TesseractDir) {
    $Candidates = @(
        "$env:ProgramFiles\Tesseract-OCR",
        "$env:LOCALAPPDATA\Programs\Tesseract-OCR"
    )
    $TesseractDir = $Candidates | Where-Object {
        Test-Path (Join-Path $_ "tesseract.exe")
    } | Select-Object -First 1
}
if (-not $TesseractDir -or -not (Test-Path (Join-Path $TesseractDir "tesseract.exe"))) {
    throw "Tesseract runtime not found. Install it for the build machine or pass -TesseractDir. It will be bundled inside PAi Legal."
}
if (-not (Test-Path (Join-Path $TesseractDir "tessdata\eng.traineddata"))) {
    throw "Tesseract English language data is missing: tessdata\eng.traineddata"
}
if (-not $LlamaCppDir) {
    $RuntimeCandidates = @(
        "$env:LOCALAPPDATA\PAiLegal\runtime\llamacpp",
        "$env:LOCALAPPDATA\PrivateAI\runtime\llamacpp",
        "$env:LOCALAPPDATA\PSiLegal\runtime\llamacpp"
    )
    $LlamaCppDir = $RuntimeCandidates | Where-Object { Test-Path (Join-Path $_ "llama-server.exe") } | Select-Object -First 1
}
if (-not $LlamaCppDir -or -not (Test-Path (Join-Path $LlamaCppDir "llama-server.exe"))) {
    throw "llama.cpp runtime not found. Pass -LlamaCppDir containing llama-server.exe and its companion DLLs. The complete directory is bundled inside PAi Legal."
}

if (-not (Test-Path $Venv)) {
    py -3.12 -m venv $Venv
}
& "$Venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -e "${Project}[build]"
& "$Venv\Scripts\python.exe" -m unittest discover -s "$Project\tests" -v

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item $Stage -ItemType Directory -Force | Out-Null

# PerMonitorV2 keeps Windows from bitmap-scaling the UI at 125-200%, and clears
# the WACK DPIAwarenessValidation warning that PSi Legal hit.
$DpiManifest = Join-Path $Project "build\PAiLegal.exe.manifest"
New-Item (Split-Path $DpiManifest) -ItemType Directory -Force | Out-Null
@"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="PAiLegal" version="$Version" processorArchitecture="amd64" />
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
    </windowsSettings>
  </application>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false" /></requestedPrivileges></security>
  </trustInfo>
</assembly>
"@ | Set-Content -Path $DpiManifest -Encoding UTF8

# Tesseract ships an NSIS uninstaller that requests elevation. Bundling the
# install folder wholesale carries it in, which fails WACK "User account
# control run level" and adds a blocked-executable reference. Stage a copy
# with the uninstaller and man pages removed and bundle that instead.
$TessStage = Join-Path $Project "build\tesseract"
Remove-Item $TessStage -Recurse -Force -ErrorAction SilentlyContinue
New-Item $TessStage -ItemType Directory -Force | Out-Null
Copy-Item "$TesseractDir\*" $TessStage -Recurse -Force
Get-ChildItem $TessStage -Recurse -Include *uninstall*.exe,*uninst*.exe,*.html,*.1,*.5,*.nsi |
    Remove-Item -Force -ErrorAction SilentlyContinue
if (Get-ChildItem $TessStage -Recurse -Filter *uninstall*.exe) {
    throw "Tesseract uninstaller still present in the staged copy."
}
Write-Host "Staged Tesseract without its uninstaller: $TessStage"
& "$Venv\Scripts\pyinstaller.exe" `
    --noconfirm --clean --windowed --onedir `
    --name PAiLegal `
    --add-binary "$StoreBridgeExe;store-bridge" `
    --manifest "$DpiManifest" `
    --add-data "$TessStage;resources\tesseract" `
    --add-data "$LlamaCppDir;resources\llama" `
    --collect-all pymupdf `
    --collect-all openpyxl `
    --collect-all pptx `
    --collect-all striprtf `
    --collect-all extract_msg `
    --collect-all tkinterdnd2 `
    --collect-all reportlab `
    --distpath "$Project\build\pyinstaller" `
    "$Project\run_pai_legal.py"

Copy-Item "$Project\build\pyinstaller\PAiLegal\*" $Stage -Recurse -Force
Copy-Item "$Project\THIRD_PARTY_NOTICES.md" (Join-Path $Stage "THIRD_PARTY_NOTICES.md") -Force

$Manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap rescap">
  <Identity Name="$IdentityName" Publisher="$Publisher" Version="$Version" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>PAi Legal</DisplayName>
    <PublisherDisplayName>PAi Luton</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Resources><Resource Language="en-us" /></Resources>
  <Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" /></Dependencies>
  <Applications>
    <Application Id="PAiLegal" Executable="PAiLegal.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="PAi Legal" Description="Private legal case workspace" BackgroundColor="#0E1014"
          Square150x150Logo="Assets\Square150x150Logo.png" Square44x44Logo="Assets\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\Wide310x150Logo.png"
                         Square71x71Logo="Assets\Square71x71Logo.png"
                         Square310x310Logo="Assets\Square310x310Logo.png" />
        <uap:SplashScreen Image="Assets\SplashScreen.png" BackgroundColor="#0E1014" />
      </uap:VisualElements>
    </Application>
  </Applications>
  <Capabilities><rescap:Capability Name="runFullTrust" /></Capabilities>
</Package>
"@
Set-Content -Path (Join-Path $Stage "AppxManifest.xml") -Value $Manifest -Encoding UTF8

$Assets = Join-Path $Project "Assets"
if (-not (Test-Path $Assets)) {
    throw "Assets folder missing. Run New-PAiLegalAssets.ps1 -Source <1024px master>.png first."
}
$AssetCount = (Get-ChildItem $Assets -Filter *.png).Count
if ($AssetCount -lt 40) {
    throw "Assets holds only $AssetCount PNG(s). A one-size-per-slot set is what failed PSi Legal on 10.1.1.11. Run New-PAiLegalAssets.ps1 first."
}
foreach ($Required in @("StoreLogo.png","Square44x44Logo.png","Square71x71Logo.png","Square150x150Logo.png","Square310x310Logo.png","Wide310x150Logo.png","SplashScreen.png")) {
    if (-not (Test-Path (Join-Path $Assets $Required))) { throw "Assets is missing $Required" }
}
Copy-Item $Assets (Join-Path $Stage "Assets") -Recurse -Force

$SdkBin = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Directory |
    Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName "x64\makeappx.exe" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $SdkBin) { throw "makeappx.exe was not found. Install the Windows SDK." }

New-Item $Dist -ItemType Directory -Force | Out-Null
$Package = Join-Path $Dist "PAiLegal_$Version`_x64.msix"
& $SdkBin pack /d $Stage /p $Package /o
$Size = (Get-Item $Package).Length / 1GB
$Hash = (Get-FileHash $Package -Algorithm SHA256).Hash
Write-Host ""
Write-Host "Package creation succeeded: $Package" -ForegroundColor Green
Write-Host ("Size    : {0:N2} GB" -f $Size)
Write-Host "SHA-256 : $Hash"
Write-Host "Assets  : $AssetCount PNG(s)"
Write-Host ""
Write-Host "Next: run the Windows App Certification Kit against this package before uploading." -ForegroundColor Yellow

