$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$logDir = Join-Path $Root "output\watchdog"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "watchdog.log"

function Write-WatchdogLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
  Write-Host $line
}

function Test-Ready {
  try {
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/readyz" -TimeoutSec 8
    return ($ready.status -eq "ready")
  } catch {
    return $false
  }
}

if (Test-Ready) {
  Write-WatchdogLog "ready"
  exit 0
}

Write-WatchdogLog "not ready, restarting stack"
try {
  & (Join-Path $Root "start.ps1") *>> $logFile
  if (Test-Ready) {
    Write-WatchdogLog "restart success"
    exit 0
  }
  Write-WatchdogLog "restart finished but readiness still failed"
  exit 1
} catch {
  Write-WatchdogLog ("restart error: " + $_.Exception.Message)
  exit 1
}
