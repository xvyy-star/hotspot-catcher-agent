param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [switch]$Prod,
  [switch]$AllowLegacyBackup
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
. (Join-Path $PSScriptRoot "mysql-ops-common.ps1")

$startedAt = Get-Date
$timestamp = $startedAt.ToString("yyyyMMdd_HHmmss")
$reportDir = Join-Path $Root "output\drills"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$reportFile = Join-Path $reportDir "mysql-recovery_${timestamp}.json"
$drillDatabase = "hotspot_recovery_drill_$($startedAt.ToString('yyyyMMdd_HHmmss'))_$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$containerTempFile = "/tmp/hotspot_mysql_drill_$([guid]::NewGuid().ToString('N')).sql"
$databaseCreated = $false
$success = $false
$cleanupOk = $true
$errorMessage = $null
$restoredTableCount = $null
$expectedTableCount = $null
$validation = $null
$context = $null

try {
  Import-HotspotLocalEnv -Root $Root
  Assert-HotspotDockerAvailable
  $context = Get-HotspotMySqlContext -Prod:$Prod
  $validation = Test-HotspotBackupFile `
    -BackupFile $BackupFile `
    -RequireMetadata:(-not $AllowLegacyBackup) `
    -RequireTargetMetadata:(-not $AllowLegacyBackup) `
    -ExpectedStack $context.Stack `
    -ExpectedDatabase $context.Database
  Write-HotspotBackupValidation -Validation $validation
  if (-not $validation.IsValid) {
    throw "Backup validation failed."
  }

  if (-not (Test-HotspotContainerRunning -Container $context.Container)) {
    throw "MySQL container is not running: $($context.Container)"
  }

  Write-Host "[drill] Creating disposable database $drillDatabase ..." -ForegroundColor Cyan
  $createSql = "CREATE DATABASE ``$drillDatabase`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
  $createOutput = @(Invoke-HotspotMySql -Context $context -Sql $createSql -AsRoot)
  $databaseCreated = $true

  $copyOutput = @(Invoke-HotspotDocker -Arguments @("cp", $validation.FilePath, "$($context.Container):$containerTempFile"))
  $restoreArguments = @(
    "exec", "-e", "MYSQL_PWD=$($context.RootPassword)", $context.Container,
    "sh", "-c",
    'exec mysql --binary-mode=1 --default-character-set=utf8mb4 --user="$1" --database="$2" < "$3"',
    "mysql-import", "root", $drillDatabase, $containerTempFile
  )
  $restoreOutput = @(Invoke-HotspotDocker -Arguments $restoreArguments)

  $restoredTableCount = Get-HotspotMySqlTableCount -Context $context -Database $drillDatabase -AsRoot
  if ($validation.Manifest -and $null -ne $validation.Manifest.table_count) {
    $expectedTableCount = [int]$validation.Manifest.table_count
    if ($restoredTableCount -ne $expectedTableCount) {
      throw "Restored table count mismatch: expected $expectedTableCount, actual $restoredTableCount."
    }
  } elseif ($restoredTableCount -lt 1) {
    throw "Recovery drill restored no base tables."
  }

  Write-Host "[drill] Running CHECK TABLE against $restoredTableCount restored tables ..." -ForegroundColor Cyan
  $tableNameSql = "SELECT table_name FROM information_schema.tables WHERE table_schema = '$drillDatabase' AND table_type = 'BASE TABLE' ORDER BY table_name;"
  $tableNames = @(Invoke-HotspotMySql -Context $context -Sql $tableNameSql -AsRoot)
  foreach ($tableNameValue in $tableNames) {
    $tableName = ([string]$tableNameValue).Trim()
    if (-not $tableName) { continue }
    $qualifiedTable = (ConvertTo-HotspotMySqlIdentifier -Value $drillDatabase) + "." + (ConvertTo-HotspotMySqlIdentifier -Value $tableName)
    $checkRows = @(Invoke-HotspotMySql -Context $context -Sql "CHECK TABLE $qualifiedTable;" -AsRoot)
    $tableOk = @($checkRows | Where-Object { ([string]$_) -match "\tstatus\tOK$" }).Count -gt 0
    if (-not $tableOk) {
      $checkDetail = ($checkRows | ForEach-Object { [string]$_ }) -join "; "
      throw "CHECK TABLE failed for ${tableName}: $checkDetail"
    }
  }
  $success = $true
} catch {
  $errorMessage = $_.Exception.Message
  Write-Host "[drill] FAIL: $errorMessage" -ForegroundColor Red
} finally {
  if ($context) {
    try {
      $tempCleanupOutput = @(Invoke-HotspotDocker -Arguments @("exec", $context.Container, "rm", "-f", $containerTempFile))
    } catch {
      $cleanupOk = $false
      Write-Host "[drill] WARN: failed to remove container temp file: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    if ($databaseCreated) {
      try {
        $dropSql = "DROP DATABASE IF EXISTS ``$drillDatabase``;"
        $dropOutput = @(Invoke-HotspotMySql -Context $context -Sql $dropSql -AsRoot)
        Write-Host "[drill] Disposable database removed." -ForegroundColor DarkGray
      } catch {
        $cleanupOk = $false
        Write-Host "[drill] FAIL: disposable database cleanup failed: $($_.Exception.Message)" -ForegroundColor Red
      }
    }
  }

  $finishedAt = Get-Date
  $report = [ordered]@{
    schema_version = 1
    drill = "mysql_recovery"
    started_at = $startedAt.ToUniversalTime().ToString("o")
    finished_at = $finishedAt.ToUniversalTime().ToString("o")
    duration_seconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
    success = ($success -and $cleanupOk)
    cleanup_ok = $cleanupOk
    stack = if ($context) { $context.Stack } elseif ($Prod) { "production" } else { "development" }
    container = if ($context) { $context.Container } else { $null }
    source_backup = if ($validation) { $validation.FilePath } else { $BackupFile }
    sha256 = if ($validation) { $validation.Sha256 } else { $null }
    expected_table_count = $expectedTableCount
    restored_table_count = $restoredTableCount
    error = $errorMessage
  }
  $report | ConvertTo-Json | Set-Content -LiteralPath $reportFile -Encoding UTF8
}

Write-Host "[drill] Report: $reportFile" -ForegroundColor Cyan
if (-not $success -or -not $cleanupOk) {
  exit 1
}

Write-Host "[drill] PASS: backup restored and checked in an isolated database." -ForegroundColor Green
