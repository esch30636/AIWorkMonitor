param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$specPath = Join-Path $repoRoot "packaging\windows\AIWorkMonitorAgent.spec"
$workPath = Join-Path $repoRoot "build\pyinstaller"
$distPath = Join-Path $repoRoot "dist"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv $venvPath
}

& $pythonPath -m pip install -e "$repoRoot[dev,windows-build]"
if (-not $SkipTests) {
    & $pythonPath -m pytest -q
}

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distPath `
    --workpath $workPath `
    $specPath

$exePath = Join-Path $distPath "AIWorkMonitorAgent.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Expected executable was not produced: $exePath"
}

Copy-Item `
    -LiteralPath (Join-Path $repoRoot "packaging\windows\aiworkmonitor.env.example") `
    -Destination (Join-Path $distPath "aiworkmonitor.env.example") `
    -Force

Get-Item -LiteralPath $exePath | Select-Object FullName, Length, LastWriteTime
Get-FileHash -LiteralPath $exePath -Algorithm SHA256 | Format-List Algorithm, Hash, Path
