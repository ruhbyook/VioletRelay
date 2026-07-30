$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run scripts\bootstrap.ps1 first."
}

& .venv\Scripts\python.exe -m violetrelay
