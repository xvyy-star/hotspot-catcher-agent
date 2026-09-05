param(
  [ValidateSet("Development", "ProductionLocal", "Production")]
  [string]$Target = "Development",
  [SecureString]$AdminPassword,
  [switch]$NonInteractive,
  [switch]$SkipE2E
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
. (Join-Path $PSScriptRoot "mysql-ops-common.ps1")
Import-HotspotLocalEnv -Root $Root

switch ($Target) {
  "Development" {
    $apiBaseUrl = "http://127.0.0.1:8000"
    $frontendUrl = "http://127.0.0.1:5173"
  }
  "ProductionLocal" {
    $apiBaseUrl = "http://127.0.0.1:8000"
    $frontendUrl = "http://127.0.0.1:4173"
  }
  "Production" {
    $frontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "8080" }
    $apiBaseUrl = "http://127.0.0.1:$frontendPort"
    $frontendUrl = $apiBaseUrl
  }
}

$plainPassword = $null
$passwordPointer = [IntPtr]::Zero
try {
  if ($AdminPassword) {
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($AdminPassword)
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
  } elseif ($env:CHECK_ADMIN_PASSWORD) {
    $plainPassword = $env:CHECK_ADMIN_PASSWORD
  } elseif ($NonInteractive) {
    Write-Host "[release] CHECK_ADMIN_PASSWORD is required in non-interactive mode." -ForegroundColor Red
    exit 2
  } else {
    $promptedPassword = Read-Host "Admin password for the login/logout delivery check" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($promptedPassword)
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
  }

  if ([string]::IsNullOrWhiteSpace($plainPassword)) {
    Write-Host "[release] Admin password is empty." -ForegroundColor Red
    exit 2
  }

  if (-not $SkipE2E) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
      Write-Host "[release] npm was not found; frontend E2E gate failed." -ForegroundColor Red
      exit 1
    }

    if (-not $env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
      $browserCandidates = @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
      )
      $systemBrowser = $browserCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
      if ($systemBrowser) {
        $env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = $systemBrowser
      }
    }

    $previousPlaywrightBaseUrl = [Environment]::GetEnvironmentVariable("PLAYWRIGHT_BASE_URL", "Process")
    $previousPlaywrightPassword = [Environment]::GetEnvironmentVariable("PLAYWRIGHT_ADMIN_PASSWORD", "Process")
    $previousPlaywrightUsername = [Environment]::GetEnvironmentVariable("PLAYWRIGHT_ADMIN_USERNAME", "Process")
    $mockE2EExitCode = $null
    $deploymentE2EExitCode = $null

    Push-Location (Join-Path $Root "frontend")
    try {
      Remove-Item Env:PLAYWRIGHT_BASE_URL -ErrorAction SilentlyContinue
      Remove-Item Env:PLAYWRIGHT_ADMIN_PASSWORD -ErrorAction SilentlyContinue
      Remove-Item Env:PLAYWRIGHT_ADMIN_USERNAME -ErrorAction SilentlyContinue

      Write-Host "[release] Running mocked frontend core E2E gate..." -ForegroundColor Cyan
      npm run test:e2e:mock
      $mockE2EExitCode = $LASTEXITCODE

      if ($mockE2EExitCode -eq 0) {
        $env:PLAYWRIGHT_BASE_URL = $frontendUrl
        $env:PLAYWRIGHT_ADMIN_PASSWORD = $plainPassword
        $env:PLAYWRIGHT_ADMIN_USERNAME = if ($env:ADMIN_USERNAME) { $env:ADMIN_USERNAME } else { "admin" }
        Write-Host "[release] Running deployed frontend E2E gate against $frontendUrl ..." -ForegroundColor Cyan
        npm run test:e2e:deployment
        $deploymentE2EExitCode = $LASTEXITCODE
      }
    } finally {
      Pop-Location
      if ($null -eq $previousPlaywrightBaseUrl) {
        Remove-Item Env:PLAYWRIGHT_BASE_URL -ErrorAction SilentlyContinue
      } else {
        $env:PLAYWRIGHT_BASE_URL = $previousPlaywrightBaseUrl
      }
      if ($null -eq $previousPlaywrightPassword) {
        Remove-Item Env:PLAYWRIGHT_ADMIN_PASSWORD -ErrorAction SilentlyContinue
      } else {
        $env:PLAYWRIGHT_ADMIN_PASSWORD = $previousPlaywrightPassword
      }
      if ($null -eq $previousPlaywrightUsername) {
        Remove-Item Env:PLAYWRIGHT_ADMIN_USERNAME -ErrorAction SilentlyContinue
      } else {
        $env:PLAYWRIGHT_ADMIN_USERNAME = $previousPlaywrightUsername
      }
    }
    if ($mockE2EExitCode -ne 0) {
      Write-Host "[release] Mocked frontend core E2E gate failed with exit code $mockE2EExitCode." -ForegroundColor Red
      exit $mockE2EExitCode
    }
    if ($deploymentE2EExitCode -ne 0) {
      Write-Host "[release] Deployed frontend E2E gate failed with exit code $deploymentE2EExitCode." -ForegroundColor Red
      exit $deploymentE2EExitCode
    }
  } else {
    Write-Host "[release] Frontend E2E gate skipped by -SkipE2E." -ForegroundColor Yellow
  }

  Write-Host "[release] Target=$Target API=$apiBaseUrl Frontend=$frontendUrl" -ForegroundColor Cyan
  & (Join-Path $Root "check.ps1") `
    -RequireReady `
    -AdminPassword $plainPassword `
    -ApiBaseUrl $apiBaseUrl `
    -FrontendUrl $frontendUrl
  $checkExitCode = $LASTEXITCODE
} finally {
  if ($passwordPointer -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
  }
  $plainPassword = $null
}

if ($checkExitCode -ne 0) {
  Write-Host "[release] Delivery gate failed with exit code $checkExitCode." -ForegroundColor Red
  exit $checkExitCode
}

Write-Host "[release] Delivery gate passed." -ForegroundColor Green
exit 0
