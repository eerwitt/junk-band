param([switch]$Check, [switch]$Start)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

Invoke-Checked -Program 'npm.cmd' -Arguments @('ci', '--offline', '--cache', '.npm-cache', '--ignore-scripts', '--no-audit', '--no-fund')
Invoke-Checked -Program 'uv' -Arguments @('sync', '--cache-dir', '.uv-cache', '--extra', 'dev')
Invoke-Checked -Program 'uv' -Arguments @('run', 'python', 'scripts/build_web.py')
if ($Check) {
    Invoke-Checked -Program 'npm.cmd' -Arguments @('run', 'check')
    Invoke-Checked -Program 'npm.cmd' -Arguments @('run', 'format:check')
    Invoke-Checked -Program 'uv' -Arguments @('run', 'ruff', 'check', 'services', 'scripts')
    Invoke-Checked -Program 'uv' -Arguments @('run', 'ruff', 'format', '--check', 'services', 'scripts')
    Invoke-Checked -Program 'uv' -Arguments @('run', 'mypy')
    Invoke-Checked -Program 'uv' -Arguments @('run', 'pytest')
    Invoke-Checked -Program 'uv' -Arguments @('run', 'playwright', 'install', 'chromium')
}
if ($Start) {
    Invoke-Checked -Program 'uv' -Arguments @('run', 'python', 'scripts/dev.py')
}
