param(
  [switch]$Prod
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
. (Join-Path $PSScriptRoot "mysql-ops-common.ps1")

Import-HotspotLocalEnv -Root $Root
Assert-HotspotDockerAvailable
$context = Get-HotspotMySqlContext -Prod:$Prod
$backupDir = Join-Path $Root "output\backups"
$backup = New-HotspotMySqlBackup `
  -Context $context `
  -BackupDirectory $backupDir `
  -FilePrefix "mysql" `
  -Purpose "operator"

Write-Host "[backup] Saved: $($backup.FilePath)" -ForegroundColor Green
Write-Host "[backup] Tables: $($backup.TableCount)" -ForegroundColor Green
Write-Output $backup.FilePath
