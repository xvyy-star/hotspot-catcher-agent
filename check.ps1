param(
  [Parameter(Mandatory = $false)]
  [string]$AdminPassword,
  [switch]$RequireReady,
  [string]$ApiBaseUrl = "http://127.0.0.1:8000",
  [string]$FrontendUrl = "http://127.0.0.1:5173"
)

$ErrorActionPreference = "Continue"

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

Load-LocalEnv

function Get-NormalizedHttpUrl {
  param([string]$Value, [string]$Name)
  $parsed = $null
  if (-not [uri]::TryCreate($Value, [System.UriKind]::Absolute, [ref]$parsed)) {
    throw "$Name must be an absolute HTTP(S) URL: $Value"
  }
  if ($parsed.Scheme -notin @("http", "https")) {
    throw "$Name must use http or https: $Value"
  }
  return $Value.TrimEnd("/")
}

$ApiBaseUrl = Get-NormalizedHttpUrl -Value $ApiBaseUrl -Name "ApiBaseUrl"
$FrontendUrl = Get-NormalizedHttpUrl -Value $FrontendUrl -Name "FrontendUrl"
$apiUri = [uri]$ApiBaseUrl
$frontendUri = [uri]$FrontendUrl

$AdminToken = if ($env:ADMIN_TOKEN) { $env:ADMIN_TOKEN } else { "" }
$AdminUsername = if ($env:ADMIN_USERNAME) { $env:ADMIN_USERNAME } else { "admin" }
if (-not $AdminPassword -and $env:CHECK_ADMIN_PASSWORD) {
  $AdminPassword = $env:CHECK_ADMIN_PASSWORD
}
$script:CheckPassed = 0
$script:CheckFailed = 0
$script:CheckSkipped = 0

function Test-Port {
  param([string]$HostName, [int]$Port)
  $client = [System.Net.Sockets.TcpClient]::new()
  try {
    $async = $client.BeginConnect($HostName, $Port, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne(700, $false)) { return $false }
    $client.EndConnect($async)
    return $true
  } catch { return $false } finally { $client.Close() }
}

function Show-Check {
  param([string]$Name, [bool]$Ok, [string]$Hint = "")
  $color = if ($Ok) { "Green" } else { "Red" }
  $mark = if ($Ok) { "OK" } else { "FAIL" }
  if ($Ok) { $script:CheckPassed += 1 } else { $script:CheckFailed += 1 }
  Write-Host ("[{0}] {1} {2}" -f $mark, $Name, $Hint) -ForegroundColor $color
}

function Show-Skip {
  param([string]$Name, [string]$Hint = "")
  $script:CheckSkipped += 1
  Write-Host ("[SKIP] {0} {1}" -f $Name, $Hint) -ForegroundColor DarkYellow
}

$backend = Test-Port -HostName $apiUri.DnsSafeHost -Port $apiUri.Port
$frontend = Test-Port -HostName $frontendUri.DnsSafeHost -Port $frontendUri.Port
$checkDefaultPreview = $FrontendUrl -eq "http://127.0.0.1:5173"
$frontendPreview = $checkDefaultPreview -and (Test-Port -HostName "127.0.0.1" -Port 4173)
Show-Check "API endpoint port" $backend ("{0}:{1}" -f $apiUri.DnsSafeHost, $apiUri.Port)
Show-Check "Frontend endpoint port" $frontend ("{0}:{1}" -f $frontendUri.DnsSafeHost, $frontendUri.Port)
if ($frontendPreview) {
  Show-Check "Frontend preview port 4173" $frontendPreview
}

if ($RequireReady -and -not $AdminPassword) {
  Show-Check "Strict gate admin credential" $false "pass -AdminPassword or set CHECK_ADMIN_PASSWORD"
}

if ($RequireReady) {
  $qualityScript = Join-Path $Root "scripts\evaluate_ai_quality.py"
  $qualityReportPath = Join-Path $Root "reports\ai_quality_latest.json"
  $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
  $pythonCommand = $null
  if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonCommand = $venvPython
  } else {
    $pythonOnPath = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonOnPath) { $pythonCommand = $pythonOnPath.Source }
  }

  if (-not $pythonCommand) {
    Show-Check "AI quality regression gate" $false "Python interpreter was not found"
  } elseif (-not (Test-Path -LiteralPath $qualityScript -PathType Leaf)) {
    Show-Check "AI quality regression gate" $false "missing scripts/evaluate_ai_quality.py"
  } else {
    try {
      $qualityOutput = @(& $pythonCommand $qualityScript --output $qualityReportPath 2>&1)
      $qualityExitCode = $LASTEXITCODE
      $qualityHint = "exit=$qualityExitCode report=$qualityReportPath"
      if (Test-Path -LiteralPath $qualityReportPath -PathType Leaf) {
        try {
          $qualityReport = Get-Content -LiteralPath $qualityReportPath -Encoding UTF8 -Raw | ConvertFrom-Json
          $failedCases = @($qualityReport.failed_case_ids) -join ","
          $qualityHint += " passed=$($qualityReport.passed)"
          if ($failedCases) { $qualityHint += " failed_cases=$failedCases" }
          if ($qualityReport.error) { $qualityHint += " error=$($qualityReport.error)" }
        } catch {
          $qualityHint += " report_parse_error=$($_.Exception.Message)"
        }
      }
      Show-Check "AI quality regression gate" ($qualityExitCode -eq 0) $qualityHint
    } catch {
      Show-Check "AI quality regression gate" $false $_.Exception.Message
    }
  }
}

if ($backend) {
  try {
    $health = Invoke-RestMethod -Uri "$ApiBaseUrl/health" -TimeoutSec 5
    Show-Check "/health" ($health.status -eq "ok") ($health | ConvertTo-Json -Compress)
  } catch {
    Show-Check "/health" $false $_.Exception.Message
  }

  try {
    $ready = Invoke-RestMethod -Uri "$ApiBaseUrl/readyz" -TimeoutSec 8
    Show-Check "/readyz dependencies" ($ready.status -eq "ready") ($ready | ConvertTo-Json -Compress)
  } catch {
    Show-Check "/readyz dependencies" $false $_.Exception.Message
  }

  try {
    $status = Invoke-RestMethod -Uri "$ApiBaseUrl/api/system/status" -TimeoutSec 5
    Show-Check "/api/system/status" ($null -ne $status.data) ($status.data | ConvertTo-Json -Compress)
  } catch {
    Show-Check "/api/system/status" $false $_.Exception.Message
  }

  try {
    Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/events?limit=1" -TimeoutSec 5 | Out-Null
    Show-Check "Protected API rejects anonymous" $false "anonymous request unexpectedly succeeded"
  } catch {
    $code = $_.Exception.Response.StatusCode.value__
    Show-Check "Protected API rejects anonymous" ($code -eq 401) "HTTP $code"
  }

  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $events = Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/events?limit=3" -Headers $headers -TimeoutSec 8
    Show-Check "Protected API with token" ($null -ne $events.data) ("events=" + ($events.data.Count))
  } catch {
    Show-Check "Protected API with token" $false $_.Exception.Message
  }

  if ($AdminPassword) {
    $loginSessionToken = $null
    try {
      $loginBody = @{ username = $AdminUsername; password = $AdminPassword; remember = $false } | ConvertTo-Json -Compress
      $login = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/auth/login" -Body $loginBody -ContentType "application/json" -TimeoutSec 8
      $loginSessionToken = $login.data.token
      $loginOk = ($login.data.profile.username -eq $AdminUsername) -and (-not [string]::IsNullOrWhiteSpace($loginSessionToken))
      Show-Check "Auth password login API" $loginOk ("user=" + $login.data.profile.username)
    } catch {
      Show-Check "Auth password login API" $false $_.Exception.Message
    }

    if ($loginSessionToken) {
      $sessionRevoked = $false
      $sessionReuseRejected = $false
      $sessionHeaders = @{ Authorization = "Bearer $loginSessionToken"; "X-Admin-Token" = $loginSessionToken }
      try {
        $logout = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/auth/logout" -Headers $sessionHeaders -TimeoutSec 8
        $sessionRevoked = ($logout.ok -eq $true) -and ($logout.revoked -eq $true)
        Show-Check "Auth logout revokes session" $sessionRevoked ("revoked=" + $logout.revoked)
      } catch {
        Show-Check "Auth logout revokes session" $false $_.Exception.Message
      }

      try {
        $reusedSession = Invoke-RestMethod -Uri "$ApiBaseUrl/api/auth/me" -Headers $sessionHeaders -TimeoutSec 8
        $reusedUsername = if ($reusedSession.data.username) { $reusedSession.data.username } else { "unknown" }
        Show-Check "Revoked session rejects token reuse" $false ("unexpectedly authenticated user=" + $reusedUsername)
      } catch {
        $reuseStatusCode = $null
        if ($_.Exception.Response -and $null -ne $_.Exception.Response.StatusCode) {
          $reuseStatusCode = [int]$_.Exception.Response.StatusCode
        }
        $sessionReuseRejected = ($reuseStatusCode -eq 401)
        $reuseHint = if ($null -ne $reuseStatusCode) { "HTTP $reuseStatusCode" } else { $_.Exception.Message }
        Show-Check "Revoked session rejects token reuse" $sessionReuseRejected $reuseHint
      }

      if (-not ($sessionRevoked -and $sessionReuseRejected)) {
        try {
          Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/auth/logout" -Headers $sessionHeaders -TimeoutSec 8 | Out-Null
        } catch {
          # Best-effort cleanup only; the failed revocation is already reported above.
        }
      }
    } else {
      Show-Skip "Auth logout revokes session" "login did not issue a session token"
    }
  } else {
    Show-Skip "Auth password login/logout API" "pass -AdminPassword or set CHECK_ADMIN_PASSWORD"
  }


  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $me = Invoke-RestMethod -Uri "$ApiBaseUrl/api/auth/me" -Headers $headers -TimeoutSec 8
    Show-Check "Auth me API" ($null -ne $me.data.username) ("user=" + $me.data.username)
  } catch {
    Show-Check "Auth me API" $false $_.Exception.Message
  }

  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $logs = Invoke-RestMethod -Uri "$ApiBaseUrl/api/system/logs?limit=3" -Headers $headers -TimeoutSec 8
    Show-Check "System logs API" ($null -ne $logs.data) ("logs=" + ($logs.data.Count))
  } catch {
    Show-Check "System logs API" $false $_.Exception.Message
  }

  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $deleted = Invoke-RestMethod -Method Delete -Uri "$ApiBaseUrl/api/system/logs?module=check_delete" -Headers $headers -TimeoutSec 8
    Show-Check "System logs delete API" ($null -ne $deleted.data.deleted_count) ("deleted=" + $deleted.data.deleted_count)
  } catch {
    Show-Check "System logs delete API" $false $_.Exception.Message
  }

  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $metrics = Invoke-RestMethod -Uri "$ApiBaseUrl/api/system/metrics" -Headers $headers -TimeoutSec 12
    $metricsOk = ($null -ne $metrics.data.summary) -and `
      ($null -ne $metrics.data.summary.llm_cost_24h) -and `
      (@($metrics.data.trends.operations_7d).Count -eq 7)
    Show-Check "System metrics API" $metricsOk ("score=" + $metrics.data.summary.system_score + " cost24h=" + $metrics.data.summary.llm_cost_24h + " trendDays=" + @($metrics.data.trends.operations_7d).Count)
  } catch {
    Show-Check "System metrics API" $false $_.Exception.Message
  }

  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $readiness = Invoke-RestMethod -Uri "$ApiBaseUrl/api/system/readiness" -Headers $headers -TimeoutSec 12
    $readyOk = ($null -ne $readiness.data.categories) -and ($null -ne $readiness.data.readiness_score)
    Show-Check "Deployment readiness API" $readyOk ("level=" + $readiness.data.readiness_level + " score=" + $readiness.data.readiness_score + " blockers=" + $readiness.data.blockers)
    if ($RequireReady) {
      $deliveryReady = ($readiness.data.readiness_level -eq "READY") -and ([int]$readiness.data.blockers -eq 0)
      Show-Check "Deployment readiness gate" $deliveryReady ("level=" + $readiness.data.readiness_level + " blockers=" + $readiness.data.blockers)
    } else {
      Show-Skip "Deployment readiness gate" "pass -RequireReady for the production delivery gate"
    }
  } catch {
    Show-Check "Deployment readiness API" $false $_.Exception.Message
    if ($RequireReady) {
      Show-Check "Deployment readiness gate" $false "readiness API unavailable"
    }
  }

  $feedbackCreated = $false
  $feedbackSkipped = $false
  $feedbackKey = $null
  $feedbackAction = $null
  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $feedbackCandidates = Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/events?limit=20" -Headers $headers -TimeoutSec 8
    foreach ($candidate in @($feedbackCandidates.data)) {
      if (-not $candidate.event_key) { continue }
      $candidateKey = [uri]::EscapeDataString([string]$candidate.event_key)
      $existingFeedback = Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/events/$candidateKey/feedback" -Headers $headers -TimeoutSec 8
      $ownActions = @(
        $existingFeedback.data |
          Where-Object { $_.created_by -eq $AdminUsername } |
          ForEach-Object { [string]$_.action }
      )
      $unusedAction = @("USEFUL", "IRRELEVANT", "FAVORITE", "BLOCK") |
        Where-Object { $ownActions -notcontains $_ } |
        Select-Object -First 1
      if ($unusedAction) {
        $feedbackKey = [string]$candidate.event_key
        $feedbackAction = [string]$unusedAction
        break
      }
    }

    if (-not $feedbackKey) {
      $feedbackSkipped = $true
      Show-Skip "Event feedback API" "no real event has an unused feedback action"
    } else {
      $encodedFeedbackKey = [uri]::EscapeDataString($feedbackKey)
      $feedbackBody = @{
        action = $feedbackAction
        note = "check.ps1 smoke $([guid]::NewGuid().ToString('N').Substring(0, 8))"
      } | ConvertTo-Json -Compress
      $feedback = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/hotspots/events/$encodedFeedbackKey/feedback" -Headers $headers -Body $feedbackBody -ContentType "application/json" -TimeoutSec 8
      $feedbackCreated = $true
      $encodedAction = [uri]::EscapeDataString($feedbackAction)
      $feedbackRecords = Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/feedback?action=$encodedAction&keyword=$encodedFeedbackKey" -Headers $headers -TimeoutSec 8
      $actionCount = $feedback.data.summary.counts.PSObject.Properties[$feedbackAction].Value
      $matchingRecords = @($feedbackRecords.data.items | Where-Object {
        $_.event_key -eq $feedbackKey -and $_.action -eq $feedbackAction -and $_.created_by -eq $AdminUsername
      }).Count
      $feedbackOk = ($null -ne $feedback.data.summary) -and ($actionCount -ge 1) -and ($matchingRecords -ge 1)
      Show-Check "Event feedback API" $feedbackOk ("action=" + $feedbackAction + " records=" + $matchingRecords)
    }
  } catch {
    if (-not $feedbackSkipped) {
      Show-Check "Event feedback API" $false $_.Exception.Message
    }
  } finally {
    if ($feedbackCreated) {
      try {
        $encodedFeedbackKey = [uri]::EscapeDataString($feedbackKey)
        $encodedAction = [uri]::EscapeDataString($feedbackAction)
        $cleanup = Invoke-RestMethod -Method Delete -Uri "$ApiBaseUrl/api/hotspots/events/$encodedFeedbackKey/feedback/$encodedAction" -Headers $headers -TimeoutSec 8
        Show-Check "Event feedback cleanup" ($cleanup.data.deleted_count -eq 1) ("deleted=" + $cleanup.data.deleted_count)
      } catch {
        Show-Check "Event feedback cleanup" $false $_.Exception.Message
      }
    }
  }

  $providerId = $null
  $providerDeleted = $false
  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $providerCode = "check-delete-provider-" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $providerBody = @{
      code = $providerCode
      name = "Check Delete Provider"
      base_url = "http://127.0.0.1:18767/v1"
      api_key = ""
      model = "mimo-auto"
      priority = 999
      enabled = $false
      requires_api_key = $false
      timeout_seconds = 60
      max_tokens = 800
      temperature = 0.2
      note = "check.ps1 delete smoke"
    } | ConvertTo-Json -Compress
    $createdProvider = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/models/providers" -Headers $headers -Body $providerBody -ContentType "application/json" -TimeoutSec 8
    $providerId = $createdProvider.data.id
    $deletedProvider = Invoke-RestMethod -Method Delete -Uri "$ApiBaseUrl/api/models/providers/$providerId" -Headers $headers -TimeoutSec 8
    $providerDeleted = ($deletedProvider.ok -eq $true)
    $providersAfterDelete = Invoke-RestMethod -Uri "$ApiBaseUrl/api/models/providers" -Headers $headers -TimeoutSec 8
    $stillExists = @($providersAfterDelete.data | Where-Object { $_.code -eq $providerCode }).Count
    $deleteOk = $providerDeleted -and ($stillExists -eq 0)
    Show-Check "Model provider delete API" $deleteOk ("code=" + $providerCode + " existsAfter=" + $stillExists)
  } catch {
    Show-Check "Model provider delete API" $false $_.Exception.Message
  } finally {
    if ($providerId -and -not $providerDeleted) {
      try {
        $cleanup = Invoke-RestMethod -Method Delete -Uri "$ApiBaseUrl/api/models/providers/$providerId" -Headers $headers -TimeoutSec 8
        $providerDeleted = ($cleanup.ok -eq $true)
        Show-Check "Model provider cleanup" $providerDeleted ("id=" + $providerId)
      } catch {
        Show-Check "Model provider cleanup" $false $_.Exception.Message
      }
    }
  }

  try {
    $headers = @{ Authorization = "Bearer $AdminToken"; "X-Admin-Token" = $AdminToken }
    $runs = Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/runs?limit=1" -Headers $headers -TimeoutSec 8
    if ($runs.data.Count -gt 0) {
      $runId = $runs.data[0].run_id
      $runDetail = Invoke-RestMethod -Uri "$ApiBaseUrl/api/hotspots/runs/$runId" -Headers $headers -TimeoutSec 8
      Show-Check "Run detail API" ($runDetail.data.run_id -eq $runId) ("run_id=" + $runDetail.data.run_id + " status=" + $runDetail.data.status)
    } else {
      Show-Check "Run detail API" $true "no run yet"
    }
  } catch {
    Show-Check "Run detail API" $false $_.Exception.Message
  }
}

if ($frontend) {
  try {
    $resp = Invoke-WebRequest -Uri $FrontendUrl -TimeoutSec 5 -UseBasicParsing
    Show-Check "Frontend HTML" ($resp.StatusCode -eq 200) "HTTP $($resp.StatusCode)"
  } catch {
    Show-Check "Frontend HTML" $false $_.Exception.Message
  }
}

if ($frontendPreview) {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:4173" -TimeoutSec 5 -UseBasicParsing
    Show-Check "Frontend preview HTML" ($resp.StatusCode -eq 200) "HTTP $($resp.StatusCode)"
  } catch {
    Show-Check "Frontend preview HTML" $false $_.Exception.Message
  }

  try {
    $previewReady = Invoke-RestMethod -Uri "http://127.0.0.1:4173/readyz" -TimeoutSec 8
    Show-Check "Frontend preview /readyz proxy" ($previewReady.status -eq "ready") ($previewReady | ConvertTo-Json -Compress)
  } catch {
    Show-Check "Frontend preview /readyz proxy" $false $_.Exception.Message
  }
}

Write-Host ""
Write-Host ("Check summary: passed={0}, failed={1}, skipped={2}" -f $script:CheckPassed, $script:CheckFailed, $script:CheckSkipped) -ForegroundColor ($(if ($script:CheckFailed -eq 0) { "Green" } else { "Red" }))
if ($script:CheckFailed -gt 0) {
  exit 1
}
exit 0
