$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$builtExe = Join-Path $projectRoot 'dist\TDMS-Viewer\TDMS-Viewer.exe'
$sourceLauncher = Get-ChildItem -LiteralPath $projectRoot -Filter '*TDMS*.cmd' -File |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $sourceLauncher) {
    throw 'No source launcher matching *TDMS*.cmd was found.'
}
$target = if (Test-Path -LiteralPath $builtExe) { $builtExe } else { $sourceLauncher }
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'TDMS Viewer.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = Split-Path -Parent $target
$shortcut.Description = 'STM TDMS data preview, local FFT, and candidate screening'
$icon = Join-Path $projectRoot 'build\app.ico'
if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = "$icon,0" }
$shortcut.Save()
Write-Host "Shortcut created: $shortcutPath"
