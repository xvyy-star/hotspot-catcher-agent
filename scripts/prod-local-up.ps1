$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

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
  param([string]$Url, [int]$Seconds = 90)
  for ($i = 0; $i -lt $Seconds; $i++) {
    if (Test-HttpOk $Url 5) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

function Stop-PortProcess {
  param([int]$Port, [string]$Name)
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Host "[restart] Stopping $Name PID=$($proc.Id) $($proc.ProcessName)" -ForegroundColor Yellow
      Stop-Process -Id $proc.Id -Force
    }
  }
}

New-Item -ItemType Directory -Force -Path ".runtime" | Out-Null

Write-Host "[prod-local] Ensuring backend and dependencies..." -ForegroundColor Cyan
& (Join-Path $Root "start.ps1")

Write-Host "[prod-local] Building frontend production assets..." -ForegroundColor Cyan
Push-Location "frontend"
npm run build
Pop-Location

$previewUrl = "http://127.0.0.1:4173"
$readyUrl = "$previewUrl/readyz"

if (Test-Port 4173) {
  if (Test-HttpOk $readyUrl 5) {
    Write-Host "[prod-local] Frontend preview already ready on 4173." -ForegroundColor Yellow
  } else {
    Stop-PortProcess -Port 4173 -Name "Vite preview"
    Start-Sleep -Seconds 2
  }
}

if (-not (Test-Port 4173)) {
  Write-Host "[prod-local] Starting built frontend preview $previewUrl ..." -ForegroundColor Cyan
  Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "npm run preview -- --host 127.0.0.1 --port 4173") `
    -WorkingDirectory (Join-Path $Root "frontend") `
    -RedirectStandardOutput "..\.runtime\frontend-preview.out.log" `
    -RedirectStandardError "..\.runtime\frontend-preview.err.log" `
    -WindowStyle Hidden
}

if (-not (Wait-HttpOk $readyUrl 90)) {
  Write-Host "[prod-local] Preview is not ready. stderr tail:" -ForegroundColor Red
  Get-Content ".runtime\frontend-preview.err.log" -Tail 80 -ErrorAction SilentlyContinue
  exit 1
}

Write-Host ""
Write-Host "[prod-local] Ready." -ForegroundColor Green
Write-Host "- App:   $previewUrl"
Write-Host "- Ready: $readyUrl"
Write-Host "- Check: .\check.ps1"
