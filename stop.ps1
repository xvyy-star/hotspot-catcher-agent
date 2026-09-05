$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Stop-PortProcess {
  param([int]$Port, [string]$Name)
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $connections) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Host "Stopping $Name PID=$($proc.Id) $($proc.ProcessName)" -ForegroundColor Yellow
      Stop-Process -Id $proc.Id -Force
    }
  }
}

Stop-PortProcess -Port 8000 -Name "FastAPI"
Stop-PortProcess -Port 5173 -Name "Vite"

if ($args -contains "--docker") {
  Write-Host "Stopping docker compose services..." -ForegroundColor Yellow
  docker compose --env-file .env.example down
}

Write-Host "Stopped project runtime processes." -ForegroundColor Green
