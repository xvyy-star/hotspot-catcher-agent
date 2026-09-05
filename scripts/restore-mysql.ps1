param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [switch]$Prod,
  [switch]$ConfirmRestore,
  [switch]$ValidateOnly,
  [switch]$AllowLegacyBackup
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
. (Join-Path $PSScriptRoot "mysql-ops-common.ps1")

function Get-HotspotDatabaseDefinition {
  param([Parameter(Mandatory = $true)][psobject]$Context)

  $escapedDatabase = $Context.Database.Replace("'", "''")
  $sql = "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$escapedDatabase';"
  $rows = @(Invoke-HotspotMySql -Context $Context -Sql $sql -AsRoot)
  $row = $rows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Last 1
  $parts = @(([string]$row) -split "`t", 2)
  if ($parts.Count -ne 2 -or $parts[0] -notmatch '^[A-Za-z0-9_]+$' -or $parts[1] -notmatch '^[A-Za-z0-9_]+$') {
    throw "Could not determine a safe character set and collation for database $($Context.Database)."
  }
  return [pscustomobject]@{
    CharacterSet = $parts[0]
    Collation = $parts[1]
  }
}

function Reset-HotspotDatabase {
  param(
    [Parameter(Mandatory = $true)][psobject]$Context,
    [Parameter(Mandatory = $true)][psobject]$Definition
  )

  $databaseIdentifier = ConvertTo-HotspotMySqlIdentifier -Value $Context.Database
  $sql = "DROP DATABASE IF EXISTS $databaseIdentifier; CREATE DATABASE $databaseIdentifier CHARACTER SET $($Definition.CharacterSet) COLLATE $($Definition.Collation);"
  $resetOutput = @(Invoke-HotspotMySql -Context $Context -Sql $sql -AsRoot)
}

function Import-HotspotBackup {
  param(
    [Parameter(Mandatory = $true)][psobject]$Context,
    [Parameter(Mandatory = $true)][string]$FilePath
  )

  $containerTempFile = "/tmp/hotspot_mysql_restore_$([guid]::NewGuid().ToString('N')).sql"
  try {
    $copyOutput = @(Invoke-HotspotDocker -Arguments @("cp", $FilePath, "$($Context.Container):$containerTempFile"))
    $restoreArguments = @(
      "exec", "-e", "MYSQL_PWD=$($Context.RootPassword)", $Context.Container,
      "sh", "-c",
      'exec mysql --binary-mode=1 --default-character-set=utf8mb4 --user="$1" --database="$2" < "$3"',
      "mysql-import", "root", $Context.Database, $containerTempFile
    )
    $restoreOutput = @(Invoke-HotspotDocker -Arguments $restoreArguments)
  } finally {
    try {
      $cleanupOutput = @(Invoke-HotspotDocker -Arguments @("exec", $Context.Container, "rm", "-f", $containerTempFile))
    } catch {
      Write-Host "[restore] WARN: failed to remove container temp file: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  }
}

function Assert-HotspotRestoredBackup {
  param(
    [Parameter(Mandatory = $true)][psobject]$Context,
    [Parameter(Mandatory = $true)][psobject]$Validation
  )

  $restoredTableCount = Get-HotspotMySqlTableCount -Context $Context -Database $Context.Database -AsRoot
  if ($restoredTableCount -lt 1) {
    throw "Restore finished but the target database contains no base tables."
  }
  if ($Validation.Manifest -and $null -ne $Validation.Manifest.table_count) {
    $expectedTableCount = [int]$Validation.Manifest.table_count
    if ($restoredTableCount -ne $expectedTableCount) {
      throw "Restored table count mismatch: expected $expectedTableCount, actual $restoredTableCount."
    }
  }
  return $restoredTableCount
}

if ($ValidateOnly -and $ConfirmRestore) {
  Write-Host "[restore] FAIL: -ValidateOnly and -ConfirmRestore are mutually exclusive." -ForegroundColor Red
  exit 1
}
if ($AllowLegacyBackup) {
  Write-Host "[restore] FAIL: formal restore requires checksum and manifest metadata; legacy backups are limited to isolated recovery drills." -ForegroundColor Red
  exit 1
}

Import-HotspotLocalEnv -Root $Root
$context = Get-HotspotMySqlContext -Prod:$Prod
$validation = Test-HotspotBackupFile `
  -BackupFile $BackupFile `
  -RequireMetadata `
  -RequireTargetMetadata `
  -ExpectedStack $context.Stack `
  -ExpectedDatabase $context.Database
Write-HotspotBackupValidation -Validation $validation
if (-not $validation.IsValid) {
  exit 1
}

if ($ValidateOnly) {
  Write-Host "[restore] Validation-only mode completed for $($context.Stack)/$($context.Database); no database changes were made." -ForegroundColor Green
  exit 0
}

if (-not $ConfirmRestore) {
  Write-Host "Restore rebuilds the selected database from the validated backup." -ForegroundColor Yellow
  Write-Host "Run -ValidateOnly first, then re-run with -ConfirmRestore." -ForegroundColor Yellow
  exit 1
}

Assert-HotspotDockerAvailable
if (-not (Test-HotspotContainerRunning -Container $context.Container)) {
  Write-Host "[restore] MySQL container is not running: $($context.Container)" -ForegroundColor Red
  exit 1
}

$rollbackBackup = $null
$databaseMayHaveChanged = $false
$rollbackSucceeded = $false
try {
  $databaseDefinition = Get-HotspotDatabaseDefinition -Context $context
  $rollbackBackup = New-HotspotMySqlBackup `
    -Context $context `
    -BackupDirectory (Join-Path $Root "output\backups") `
    -FilePrefix "mysql_pre_restore" `
    -Purpose "pre_restore_rollback"
  Write-Host "[restore] Rollback backup retained: $($rollbackBackup.FilePath)" -ForegroundColor Green

  $databaseMayHaveChanged = $true
  Write-Host "[restore] Rebuilding $($context.Stack)/$($context.Database) before import ..." -ForegroundColor Cyan
  Reset-HotspotDatabase -Context $context -Definition $databaseDefinition
  Import-HotspotBackup -Context $context -FilePath $validation.FilePath
  $restoredTableCount = Assert-HotspotRestoredBackup -Context $context -Validation $validation

  Write-Host "[restore] Done. Tables: $restoredTableCount" -ForegroundColor Green
  Write-Host "[restore] Rollback backup: $($rollbackBackup.FilePath)" -ForegroundColor Green
  exit 0
} catch {
  $restoreError = $_.Exception.Message
  Write-Host "[restore] FAIL: $restoreError" -ForegroundColor Red

  if ($databaseMayHaveChanged -and $rollbackBackup) {
    Write-Host "[restore] Attempting automatic rollback from $($rollbackBackup.FilePath) ..." -ForegroundColor Yellow
    try {
      Reset-HotspotDatabase -Context $context -Definition $databaseDefinition
      Import-HotspotBackup -Context $context -FilePath $rollbackBackup.FilePath
      $rollbackTableCount = Assert-HotspotRestoredBackup -Context $context -Validation $rollbackBackup.Validation
      $rollbackSucceeded = $true
      Write-Host "[restore] Automatic rollback completed. Tables: $rollbackTableCount" -ForegroundColor Green
    } catch {
      Write-Host "[restore] FAIL: automatic rollback failed: $($_.Exception.Message)" -ForegroundColor Red
    }
  } else {
    Write-Host "[restore] Target database was not changed." -ForegroundColor Yellow
  }

  if ($rollbackBackup) {
    Write-Host "[restore] Rollback backup retained: $($rollbackBackup.FilePath)" -ForegroundColor Yellow
  }
  if ($rollbackSucceeded) {
    Write-Host "[restore] Restore failed and the original database was restored; exiting non-zero." -ForegroundColor Red
  }
  exit 1
}
