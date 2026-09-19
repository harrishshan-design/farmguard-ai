$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    py -m venv (Join-Path $ProjectDir ".venv")
}

Set-Location -LiteralPath $ProjectDir
& $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectDir "requirements.txt")
& $Python app.py
