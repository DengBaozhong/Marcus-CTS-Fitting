param(
    [string]$PythonVersion = "3.12.10",
    [string]$PackageName = "MarcusCT_WebUI_Portable"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $Root "dist"
$PackageDir = Join-Path $DistRoot $PackageName
$RuntimeDir = Join-Path $PackageDir "runtime"
$AppDir = Join-Path $PackageDir "app"
$SitePackages = Join-Path $RuntimeDir "Lib\site-packages"
$ZipName = "python-$PythonVersion-embed-amd64.zip"
$ZipPath = Join-Path $DistRoot $ZipName
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/$ZipName"

Write-Host "Building portable Marcus CT WebUI..." -ForegroundColor Cyan
Write-Host "Package folder: $PackageDir"

if (Test-Path $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DistRoot, $RuntimeDir, $AppDir, $SitePackages | Out-Null

if (-not (Test-Path $ZipPath)) {
    Write-Host "Downloading portable Python $PythonVersion..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $PythonUrl -OutFile $ZipPath
} else {
    Write-Host "Using cached $ZipName"
}

Write-Host "Extracting Python runtime..." -ForegroundColor Cyan
Expand-Archive -LiteralPath $ZipPath -DestinationPath $RuntimeDir -Force

$PthPath = Join-Path $RuntimeDir ("python" + ($PythonVersion -replace "\.", "").Substring(0, 3) + "._pth")
if (-not (Test-Path $PthPath)) {
    $PthPath = Get-ChildItem -LiteralPath $RuntimeDir -Filter "python*._pth" | Select-Object -First 1 -ExpandProperty FullName
}
$Pth = Get-Content -LiteralPath $PthPath
$Pth = $Pth | ForEach-Object {
    if ($_ -match "^\s*#\s*import site\s*$") { "import site" } else { $_ }
}
if ($Pth -notcontains "Lib\site-packages") {
    $Pth = @($Pth[0], "Lib\site-packages") + $Pth[1..($Pth.Count - 1)]
}
Set-Content -LiteralPath $PthPath -Value $Pth -Encoding ASCII

Write-Host "Copying WebUI files..." -ForegroundColor Cyan
Copy-Item -LiteralPath (Join-Path $Root "marcus_ct_webui.py") -Destination $AppDir -Force
foreach ($sample in @("EQE.csv", "EL.csv")) {
    $samplePath = Join-Path $Root $sample
    if (Test-Path $samplePath) {
        Copy-Item -LiteralPath $samplePath -Destination $AppDir -Force
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "fit_results"), (Join-Path $AppDir "uploaded_spectra") | Out-Null

$HostPython = (Get-Command python -ErrorAction Stop).Source
Write-Host "Installing Python packages into the portable runtime..." -ForegroundColor Cyan
& $HostPython -m pip install `
    --upgrade `
    --target $SitePackages `
    --only-binary=:all: `
    --platform win_amd64 `
    --python-version 3.12 `
    --implementation cp `
    --abi cp312 `
    numpy pandas scipy plotly

$Launcher = @'
@echo off
setlocal
cd /d "%~dp0app"
..\runtime\python.exe marcus_ct_webui.py --port 8502
pause
'@
Set-Content -LiteralPath (Join-Path $PackageDir "start_webui.bat") -Value $Launcher -Encoding ASCII

$Readme = @"
Marcus CT WebUI portable package
================================

How to use
----------
1. Double-click start_webui.bat.
2. A browser window should open at http://localhost:8502.
3. Upload EQE/EL CSV files in the left panel.
4. Click Fit, then Save CSV when you want to export results.

Notes
-----
- This package uses the Python runtime in the local runtime folder.
- Users do not need to install Python, numpy, pandas, scipy, or plotly.
- This is not a PyInstaller exe; the WebUI source is still in app\marcus_ct_webui.py.
- Saved CSV files are written to app\fit_results.
- Uploaded spectra are copied to app\uploaded_spectra.
"@
Set-Content -LiteralPath (Join-Path $PackageDir "README.txt") -Value $Readme -Encoding UTF8

Write-Host ""
Write-Host "Portable package created:" -ForegroundColor Green
Write-Host $PackageDir
Write-Host "Send the whole '$PackageName' folder to classmates."
