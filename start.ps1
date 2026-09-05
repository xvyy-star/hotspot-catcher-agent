$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
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

function Assert-ComposeSafeBcryptEnv {
  $envFile = Join-Path $Root ".env"
  if (-not (Test-Path $envFile)) { return }
  $entry = Get-Content $envFile -Encoding UTF8 |
    Where-Object { $_.TrimStart().StartsWith("ADMIN_PASSWORD_BCRYPT=") } |
    Select-Object -First 1
  if (-not $entry) { return }
  $value = $entry.Split("=", 2)[1].Trim()
  $isSingleQuoted = $value.Length -ge 2 -and $value.StartsWith("'") -and $value.EndsWith("'")
  if ($value.Contains('$') -and -not $isSingleQuoted) {
    throw "ADMIN_PASSWORD_BCRYPT in .env must be wrapped in single quotes so Docker Compose does not interpolate bcrypt dollar signs."
  }
}

function Test-Port {
  param([int]$Port)
  $client = [System.Net.Sockets.TcpClient]::new()
  try {
    $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne(700, $false)) { return $false }
    $client.EndConnect($async)
    return $true
  } catch {
    return $false
  } finally {
    $client.Close()
  }
}

function Get-ContainerHostPort {
  param([string]$ContainerName, [int]$ContainerPort)
  try {
    $binding = docker port $ContainerName "$ContainerPort/tcp" 2>$null | Select-Object -First 1
  } catch {
    return $null
  }
  if ($binding -match ':(\d+)$') {
    return [int]$Matches[1]
  }
  return $null
}

function Get-UrlPort {
  param([string]$Url, [int]$Fallback)
  if ($Url) {
    try {
      $uri = [uri]$Url
      if ($uri.Port -gt 0) { return $uri.Port }
    } catch {
      # Invalid URLs are reported later by the application readiness check.
    }
  }
  return $Fallback
}

function Set-LocalUrlPort {
  param([string]$Url, [int]$Port)
  if (-not $Url) { return $Url }
  $pattern = '^(?<prefix>[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^/@]+@)?)(?<host>localhost|127\.0\.0\.1):\d+'
  $regex = [regex]::new($pattern)
  return $regex.Replace($Url, {
    param($match)
    "$($match.Groups['prefix'].Value)$($match.Groups['host'].Value):$Port"
  }, 1)
}

function Resolve-ServicePort {
  param(
    [int]$ConfiguredPort,
    [string]$ContainerName,
    [int]$ContainerPort,
    [string]$Name,
    [int[]]$ReservedPorts = @()
  )
  $containerHostPort = Get-ContainerHostPort $ContainerName $ContainerPort
  if ($containerHostPort) { return $containerHostPort }
  if ($ReservedPorts -notcontains $ConfiguredPort -and -not (Test-Port $ConfiguredPort)) { return $ConfiguredPort }

  for ($candidate = $ConfiguredPort + 1; $candidate -le $ConfiguredPort + 100; $candidate++) {
    if ($ReservedPorts -notcontains $candidate -and -not (Test-Port $candidate)) {
      Write-Host "[ports] $Name port $ConfiguredPort is occupied; using $candidate for this run." -ForegroundColor Yellow
      return $candidate
    }
  }
  throw "No free port found for $Name near $ConfiguredPort."
}

function Wait-Port {
  param([int]$Port, [int]$Seconds = 40, [string]$Name = "")
  for ($i = 0; $i -lt $Seconds; $i++) {
    if (Test-Port $Port) { return $true }
    Start-Sleep -Seconds 1
  }
  if ($Name) {
    Write-Host "[error] $Name did not listen on port $Port within ${Seconds}s." -ForegroundColor Red
  }
  return $false
}

function Test-HttpOk {
  param([string]$Url, [int]$TimeoutSec = 3)
  try {
    $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
    return (($resp.StatusCode -ge 200) -and ($resp.StatusCode -lt 300))
  } catch {
    return $false
  }
}

function Wait-HttpOk {
  param([string]$Url, [int]$Seconds = 60, [string]$Name = "")
  for ($i = 0; $i -lt $Seconds; $i++) {
    if (Test-HttpOk $Url 3) { return $true }
    Start-Sleep -Seconds 1
  }
  if ($Name) {
    Write-Host "[error] $Name is not ready: $Url" -ForegroundColor Red
  }
  return $false
}

function Stop-PortProcess {
  param([int]$Port, [string]$Name)
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Host "[restart] Stopping unhealthy $Name PID=$($proc.Id) $($proc.ProcessName)" -ForegroundColor Yellow
      Stop-Process -Id $proc.Id -Force
    }
  }
}

New-Item -ItemType Directory -Force -Path ".runtime" | Out-Null

if (!(Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "[env] created .env from .env.example" -ForegroundColor DarkCyan
}
if (!(Test-Path "frontend\.env") -and (Test-Path "frontend\.env.example")) {
  Copy-Item "frontend\.env.example" "frontend\.env"
  Write-Host "[env] created frontend/.env from frontend/.env.example" -ForegroundColor DarkCyan
}

Assert-ComposeSafeBcryptEnv
Load-LocalEnv

if (!$env:ADMIN_PASSWORD_BCRYPT -and !$env:ADMIN_PASSWORD_SHA256) {
  throw "Admin password hash is missing. Run 'python scripts/hash_password.py' and set ADMIN_PASSWORD_BCRYPT in .env."
}

$configuredMysqlPort = if ($env:MYSQL_PORT -match '^\d+$') { [int]$env:MYSQL_PORT } else { Get-UrlPort $env:DATABASE_URL 3307 }
$configuredRedisPort = if ($env:REDIS_PORT -match '^\d+$') { [int]$env:REDIS_PORT } else { Get-UrlPort $env:REDIS_URL 6380 }
$configuredQdrantPort = if ($env:QDRANT_PORT -match '^\d+$') { [int]$env:QDRANT_PORT } else { Get-UrlPort $env:QDRANT_URL 6333 }
$configuredQdrantGrpcPort = if ($env:QDRANT_GRPC_PORT -match '^\d+$') { [int]$env:QDRANT_GRPC_PORT } else { 6334 }

$mysqlPort = Resolve-ServicePort -ConfiguredPort $configuredMysqlPort -ContainerName "hotspot-agent-mysql" -ContainerPort 3306 -Name "MySQL"
$redisPort = Resolve-ServicePort -ConfiguredPort $configuredRedisPort -ContainerName "hotspot-agent-redis" -ContainerPort 6379 -Name "Redis"
$qdrantPort = Resolve-ServicePort -ConfiguredPort $configuredQdrantPort -ContainerName "hotspot-agent-qdrant" -ContainerPort 6333 -Name "Qdrant HTTP"
$qdrantGrpcPort = Resolve-ServicePort -ConfiguredPort $configuredQdrantGrpcPort -ContainerName "hotspot-agent-qdrant" -ContainerPort 6334 -Name "Qdrant gRPC" -ReservedPorts @($qdrantPort)

$env:MYSQL_PORT = "$mysqlPort"
$env:REDIS_PORT = "$redisPort"
$env:QDRANT_PORT = "$qdrantPort"
$env:QDRANT_GRPC_PORT = "$qdrantGrpcPort"
$env:DATABASE_URL = Set-LocalUrlPort $env:DATABASE_URL $mysqlPort
$env:REDIS_URL = Set-LocalUrlPort $env:REDIS_URL $redisPort
$qdrantUrl = if ($env:QDRANT_URL) { $env:QDRANT_URL } else { "http://127.0.0.1:6333" }
$env:QDRANT_URL = Set-LocalUrlPort $qdrantUrl $qdrantPort

Write-Host "[1/5] Starting MySQL / Redis / Qdrant..." -ForegroundColor Cyan
docker compose --env-file .env.example up -d mysql redis qdrant | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to start project dependencies." }

Write-Host "[2/5] Waiting for dependencies..." -ForegroundColor Cyan
if (-not (Wait-Port $mysqlPort 90 "MySQL")) { exit 1 }
if (-not (Wait-Port $redisPort 60 "Redis")) { exit 1 }
if (-not (Wait-HttpOk "http://127.0.0.1:$qdrantPort/" 60 "Qdrant")) { exit 1 }

Write-Host "[3/5] Checking backend dependencies..." -ForegroundColor Cyan
if (!(Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt | Out-Host

Write-Host "[3/5] Applying database migrations..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe scripts\prepare_database.py | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Database preparation failed." }

$backendReadyUrl = "http://127.0.0.1:8000/readyz"
if (Test-Port 8000) {
  if (Test-HttpOk $backendReadyUrl 5) {
    Write-Host "[4/5] Backend already ready on 8000, skipped." -ForegroundColor Yellow
  } else {
    Write-Host "[4/5] Backend process exists but is not ready, restarting..." -ForegroundColor Yellow
    Stop-PortProcess -Port 8000 -Name "FastAPI"
    Start-Sleep -Seconds 2
  }
}

if (-not (Test-Port 8000)) {
  Write-Host "[4/5] Starting backend http://127.0.0.1:8000 ..." -ForegroundColor Cyan
  Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--app-dir", "backend") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput ".runtime\backend.out.log" `
    -RedirectStandardError ".runtime\backend.err.log" `
    -WindowStyle Hidden
}

if (-not (Wait-HttpOk $backendReadyUrl 90 "Backend readiness")) {
  Write-Host "[error] Backend failed to become ready. stderr tail:" -ForegroundColor Red
  Get-Content ".runtime\backend.err.log" -Tail 100 -ErrorAction SilentlyContinue
  exit 1
}

Write-Host "[5/5] Checking frontend http://127.0.0.1:5173 ..." -ForegroundColor Cyan
if (!(Test-Path "frontend\node_modules")) {
  Push-Location "frontend"
  npm install | Out-Host
  Pop-Location
}
$isHotspotFrontend = $false
if (Test-Port 5173) {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 2 -UseBasicParsing
    if ($resp.Content -match "热点捕手") {
      $isHotspotFrontend = $true
    }
  } catch {}
}
if ($isHotspotFrontend) {
  Write-Host "[frontend] Hotspot frontend already listens on 5173, skipped." -ForegroundColor Yellow
} else {
  if (Test-Port 5173) {
    Write-Host "[frontend] Port 5173 is occupied by another process, restarting Hotspot frontend..." -ForegroundColor Yellow
    Stop-PortProcess -Port 5173 -Name "Frontend"
    Start-Sleep -Seconds 1
  }
  Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "npm run dev -- --host 127.0.0.1 --port 5173") `
    -WorkingDirectory (Join-Path $Root "frontend") `
    -RedirectStandardOutput (Join-Path $Root ".runtime\frontend.out.log") `
    -RedirectStandardError (Join-Path $Root ".runtime\frontend.err.log") `
    -WindowStyle Hidden
  if (-not (Wait-Port 5173 60 "Frontend")) {
    Write-Host "[error] Frontend failed to start. stderr tail:" -ForegroundColor Red
    Get-Content ".runtime\frontend.err.log" -Tail 80 -ErrorAction SilentlyContinue
    exit 1
  }
}

Write-Host ""
Write-Host "Started successfully:" -ForegroundColor Green
Write-Host "- Frontend: http://127.0.0.1:5173"
Write-Host "- Backend:  http://127.0.0.1:8000"
Write-Host "- Ready:    http://127.0.0.1:8000/readyz"
Write-Host "- Check:    .\check.ps1"
