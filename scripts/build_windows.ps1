param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot

$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $python -m pip install -e '.[build]'
if ($LASTEXITCODE -ne 0) { throw 'Failed to install build dependencies.' }
& $python packaging\make_icon.py --output build\app.ico
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the application icon.' }

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
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

$portableDir = Join-Path $distPath 'TDMS-Viewer'
Copy-Item -LiteralPath README.md, LICENSE, packaging\PORTABLE_README.txt -Destination $portableDir -Force
New-Item -ItemType Directory -Path (Join-Path $portableDir 'user_data') -Force | Out-Null

$versionOutput = & $python -c "from tdms_fingerprint_viewer import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Failed to read the application version.' }
$version = $versionOutput.Trim()
$zipPath = Join-Path $releasePath 'TDMS-Viewer-Windows-x64.zip'
& $python packaging\create_portable_zip.py $portableDir $zipPath
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the portable ZIP.' }

if (-not $SkipInstaller) {
    $isccCandidates = @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    $iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($iscc) {
        $isccArguments = @("/DMyAppVersion=$version")
        $chineseLanguage = Join-Path (Split-Path -Parent $iscc) 'Languages\ChineseSimplified.isl'
        if (Test-Path -LiteralPath $chineseLanguage) {
            $isccArguments += '/DIncludeChineseLanguage=1'
        } else {
            Write-Warning 'ChineseSimplified.isl was not found; building the installer with the English UI.'
        }
        $isccArguments += 'packaging\windows_installer.iss'
        & $iscc @isccArguments
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compiler failed.' }
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
