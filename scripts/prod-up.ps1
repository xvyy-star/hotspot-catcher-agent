$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Load-LocalEnv {
  $envFile = Join-Path $Root ".env"
  if (-not (Test-Path $envFile)) { return }
  Get-Content $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $parts = $line.Split("=", 2)
    $key = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($key -and -not [Environment]::GetEnvironmentVariable($key, "Process")) {
      [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
  }
}

function Test-HttpOk {
  param([string]$Url, [int]$TimeoutSec = 5)
  try {
    $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
    return (($resp.StatusCode -ge 200) -and ($resp.StatusCode -lt 300))
  } catch {
    return $false
  }
}

function Wait-HttpOk {
  param([string]$Url, [int]$Seconds = 180)
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk $Url 5) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

if (!(Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "[env] created .env from .env.example" -ForegroundColor Yellow
}

Load-LocalEnv

if (!$env:ADMIN_PASSWORD_BCRYPT -and !$env:ADMIN_PASSWORD_SHA256) {
  throw "Admin password hash is missing. Run 'python scripts/hash_password.py' and set ADMIN_PASSWORD_BCRYPT in .env."
}

$weakValues = @("root123456", "hotspot123", "password", "changeme", "change-me")
$requiredSecrets = @(
  @{ Name = "MYSQL_ROOT_PASSWORD"; Value = $env:MYSQL_ROOT_PASSWORD; MinimumLength = 16; UrlSafe = $false },
  @{ Name = "MYSQL_PASSWORD"; Value = $env:MYSQL_PASSWORD; MinimumLength = 16; UrlSafe = $true },
  @{ Name = "ADMIN_TOKEN"; Value = $env:ADMIN_TOKEN; MinimumLength = 24; UrlSafe = $false },
  @{ Name = "APP_SECRET_KEY"; Value = $env:APP_SECRET_KEY; MinimumLength = 32; UrlSafe = $false }
)
foreach ($secret in $requiredSecrets) {
  $value = [string]$secret.Value
  if ([string]::IsNullOrWhiteSpace($value)) {
    throw "$($secret.Name) is required for production."
  }
  if ($value.Length -lt [int]$secret.MinimumLength -or $weakValues -contains $value.ToLowerInvariant()) {
    throw "$($secret.Name) must be a non-default value with at least $($secret.MinimumLength) characters."
  }
  if ($secret.UrlSafe -and $value -notmatch '^[A-Za-z0-9._~-]+$') {
    throw "$($secret.Name) must use URL-safe characters because it is embedded in DATABASE_URL."
  }
}

if ($env:MYSQL_ROOT_PASSWORD -eq $env:MYSQL_PASSWORD) {
  throw "MYSQL_ROOT_PASSWORD and MYSQL_PASSWORD must be different."
}

$frontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "8080" }

Write-Host "[prod] Validating production Compose configuration..." -ForegroundColor Cyan
docker compose --env-file .env -f docker-compose.prod.yml config --quiet
if ($LASTEXITCODE -ne 0) {
  throw "Production Compose configuration is invalid."
}

Write-Host "[prod] Building and starting production stack..." -ForegroundColor Cyan
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
if ($LASTEXITCODE -ne 0) {
  throw "Production Compose build/start failed."
}

Write-Host "[prod] Waiting for readiness..." -ForegroundColor Cyan
$readyUrl = "http://127.0.0.1:$frontendPort/readyz"
if (-not (Wait-HttpOk $readyUrl 180)) {
  Write-Host "[prod] Not ready. Container status:" -ForegroundColor Red
  docker compose --env-file .env -f docker-compose.prod.yml ps
  Write-Host "[prod] Backend logs:" -ForegroundColor Red
  docker compose --env-file .env -f docker-compose.prod.yml logs --tail=120 backend
  exit 1
}

docker compose --env-file .env -f docker-compose.prod.yml ps
Write-Host ""
Write-Host "[prod] Production stack is ready." -ForegroundColor Green
Write-Host "- App:   http://127.0.0.1:$frontendPort"
Write-Host "- Ready: $readyUrl"
