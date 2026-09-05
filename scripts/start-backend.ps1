$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Import-DotEnv {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $parts = $line.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name) { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
  }
}

Import-DotEnv (Join-Path $Root ".env")

if (-not $env:ADMIN_PASSWORD_BCRYPT -and -not $env:ADMIN_PASSWORD_SHA256) {
  throw "Admin password hash is missing. Run 'python scripts/hash_password.py' first."
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
  $python = Get-Command python -ErrorAction Stop
  & $python.Source -m venv .venv
}

Write-Host "[1/5] Starting MySQL, Redis and Qdrant..." -ForegroundColor Cyan
docker compose --env-file .env up -d --wait mysql redis qdrant
if ($LASTEXITCODE -ne 0) { throw "Docker dependencies failed to start." }

Write-Host "[2/5] Installing backend dependencies..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }

Write-Host "[3/5] Applying database migrations..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe scripts\prepare_database.py
if ($LASTEXITCODE -ne 0) { throw "Database preparation failed." }

Write-Host "[4/5] Python runtime" -ForegroundColor Cyan
.\.venv\Scripts\python.exe --version

Write-Host "[5/5] Starting FastAPI on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
