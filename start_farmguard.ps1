$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    py -m venv (Join-Path $ProjectDir ".venv")
    & $Python -m pip install -r (Join-Path $ProjectDir "requirements.txt")
}

Set-Location -LiteralPath $ProjectDir
& $Python app.py
