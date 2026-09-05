$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
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

Stop-PortProcess -Port 4173 -Name "Vite preview"
Write-Host "[prod-local] Frontend preview stopped. Backend/dev frontend can be stopped with .\stop.ps1" -ForegroundColor Green
