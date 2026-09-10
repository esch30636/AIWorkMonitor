param(
    [Parameter(Mandatory = $true)][string]$RelayUrl,
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$DeviceName = $env:COMPUTERNAME
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"
python -m venv $venvPath
& (Join-Path $venvPath "Scripts\python.exe") -m pip install -e $repoRoot

$configPath = Join-Path $repoRoot ".agent.env.ps1"
@"
`$env:AIWM_RELAY_URL = "$RelayUrl"
`$env:AIWM_TOKEN = "$Token"
`$env:AIWM_DEVICE_NAME = "$DeviceName"
& "$venvPath\Scripts\aiwm-agent.exe"
"@ | Set-Content -LiteralPath $configPath -Encoding utf8

Write-Host "Agent installed. Review and run: $configPath"

