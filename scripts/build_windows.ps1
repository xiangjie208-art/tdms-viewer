param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot

$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $python -m pip install -e '.[build]'
& $python packaging\make_icon.py --output build\app.ico

$buildPath = Join-Path $projectRoot 'build'
$distPath = Join-Path $projectRoot 'dist'
$releasePath = Join-Path $projectRoot 'release'
New-Item -ItemType Directory -Path $releasePath -Force | Out-Null

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name 'TDMS-Viewer' `
    --icon "$buildPath\app.ico" `
    --paths "$projectRoot\src" `
    --exclude-module PyQt5 `
    --exclude-module PyQt6 `
    --exclude-module PySide2 `
    --exclude-module matplotlib `
    --exclude-module scipy `
    packaging\pyinstaller_entry.py

$portableDir = Join-Path $distPath 'TDMS-Viewer'
Copy-Item -LiteralPath README.md, LICENSE, packaging\PORTABLE_README.txt -Destination $portableDir -Force
New-Item -ItemType Directory -Path (Join-Path $portableDir 'user_data') -Force | Out-Null

$version = (& $python -c "from tdms_fingerprint_viewer import __version__; print(__version__)").Trim()
$zipPath = Join-Path $releasePath 'TDMS-Viewer-Windows-x64.zip'
& $python packaging\create_portable_zip.py $portableDir $zipPath

if (-not $SkipInstaller) {
    $isccCandidates = @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    $iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($iscc) {
        & $iscc "/DMyAppVersion=$version" packaging\windows_installer.iss
    } else {
        Write-Warning 'Inno Setup 6 was not found; installer build skipped.'
    }
}

$releaseFiles = Get-ChildItem -LiteralPath $releasePath -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' }
$hashLines = $releaseFiles | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.Name
}
Set-Content -LiteralPath (Join-Path $releasePath 'SHA256SUMS.txt') -Value $hashLines -Encoding UTF8
Write-Host "Build complete: $releasePath"
