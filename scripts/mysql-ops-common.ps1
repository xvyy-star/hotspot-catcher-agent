function Import-HotspotLocalEnv {
  param([Parameter(Mandatory = $true)][string]$Root)

  $envFile = Join-Path $Root ".env"
  if (-not (Test-Path -LiteralPath $envFile)) { return }

  Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
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

function Get-HotspotMySqlContext {
  param([switch]$Prod)

  return [pscustomobject]@{
    Container = if ($Prod) { "hotspot-agent-prod-mysql" } else { "hotspot-agent-mysql" }
    Stack = if ($Prod) { "production" } else { "development" }
    User = if ($env:MYSQL_USER) { $env:MYSQL_USER } else { "hotspot" }
    Password = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "hotspot123" }
    RootPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "root123456" }
    Database = if ($env:MYSQL_DATABASE) { $env:MYSQL_DATABASE } else { "hotspot_agent" }
  }
}

function Assert-HotspotDockerAvailable {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker CLI was not found in PATH."
  }
}

function Invoke-HotspotDocker {
  param([Parameter(Mandatory = $true)][string[]]$Arguments)

  $output = @(& docker @Arguments 2>&1)
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    $detail = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "no command output" }
    throw "docker command failed with exit code ${exitCode}: $detail"
  }
  return $output
}

function Test-HotspotContainerRunning {
  param([Parameter(Mandatory = $true)][string]$Container)

  try {
    $state = @(Invoke-HotspotDocker -Arguments @("inspect", "--format", "{{.State.Running}}", $Container))
    return (($state | Select-Object -Last 1).ToString().Trim() -eq "true")
  } catch {
    return $false
  }
}

function Invoke-HotspotMySql {
  param(
    [Parameter(Mandatory = $true)][psobject]$Context,
    [Parameter(Mandatory = $true)][string]$Sql,
    [string]$Database,
    [switch]$AsRoot
  )

  $user = if ($AsRoot) { "root" } else { $Context.User }
  $password = if ($AsRoot) { $Context.RootPassword } else { $Context.Password }
  $arguments = @(
    "exec", "-e", "MYSQL_PWD=$password", $Context.Container,
    "mysql", "--batch", "--skip-column-names", "--default-character-set=utf8mb4", "--user=$user"
  )
  if ($Database) { $arguments += "--database=$Database" }
  $arguments += "--execute=$Sql"
  return @(Invoke-HotspotDocker -Arguments $arguments)
}

function Get-HotspotMySqlTableCount {
  param(
    [Parameter(Mandatory = $true)][psobject]$Context,
    [Parameter(Mandatory = $true)][string]$Database,
    [switch]$AsRoot
  )

  $escapedDatabase = $Database.Replace("'", "''")
  $sql = "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$escapedDatabase' AND table_type = 'BASE TABLE';"
  $result = @(Invoke-HotspotMySql -Context $Context -Sql $sql -AsRoot:$AsRoot)
  $value = ($result | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Last 1)
  if ($null -eq $value -or -not ([string]$value -match '^\d+$')) {
    throw "MySQL table-count query returned an unexpected value: $value"
  }
  return [int]$value
}

function ConvertTo-HotspotMySqlIdentifier {
  param([Parameter(Mandatory = $true)][string]$Value)

  $quote = [char]96
  return "$quote$($Value.Replace([string]$quote, ([string]$quote + [string]$quote)))$quote"
}

function Test-HotspotBackupFile {
  param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [switch]$RequireMetadata,
    [string]$ExpectedStack,
    [string]$ExpectedDatabase,
    [switch]$RequireTargetMetadata
  )

  $errors = New-Object System.Collections.Generic.List[string]
  $warnings = New-Object System.Collections.Generic.List[string]
  $manifest = $null
  $resolvedPath = $null
  $sizeBytes = 0
  $sha256 = $null

  if (-not (Test-Path -LiteralPath $BackupFile -PathType Leaf)) {
    $errors.Add("backup file not found: $BackupFile")
  } else {
    $item = Get-Item -LiteralPath $BackupFile
    $resolvedPath = $item.FullName
    $sizeBytes = $item.Length
    if ($sizeBytes -lt 256) {
      $errors.Add("backup file is unexpectedly small: $sizeBytes bytes")
    }

    $head = @(Get-Content -LiteralPath $resolvedPath -Encoding UTF8 -TotalCount 80)
    $tail = @(Get-Content -LiteralPath $resolvedPath -Encoding UTF8 -Tail 30)
    if (-not ($head -match '^-- MySQL dump')) {
      $errors.Add("MySQL dump header was not found")
    }
    if (-not ($tail -match '^-- Dump completed on ')) {
      $errors.Add("MySQL dump completion marker was not found")
    }
    if (-not (Select-String -LiteralPath $resolvedPath -Encoding UTF8 -Pattern '^CREATE TABLE ' -Quiet)) {
      $errors.Add("backup contains no CREATE TABLE statements")
    }

    $sha256 = (Get-FileHash -LiteralPath $resolvedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumPath = "$resolvedPath.sha256"
    if (Test-Path -LiteralPath $checksumPath -PathType Leaf) {
      $checksumLine = (Get-Content -LiteralPath $checksumPath -Encoding ASCII -TotalCount 1).Trim()
      $expectedHash = ($checksumLine -split '\s+')[0].ToLowerInvariant()
      if ($expectedHash -notmatch '^[a-f0-9]{64}$') {
        $errors.Add("checksum sidecar has an invalid SHA256 value")
      } elseif ($expectedHash -ne $sha256) {
        $errors.Add("checksum mismatch: expected $expectedHash, actual $sha256")
      }
    } else {
      $message = "checksum sidecar is missing: $checksumPath"
      if ($RequireMetadata) { $errors.Add($message) } else { $warnings.Add($message) }
    }

    $manifestPath = "$resolvedPath.manifest.json"
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
      try {
        $manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
        $manifestProperties = @($manifest.PSObject.Properties.Name)
        if ($RequireMetadata) {
          foreach ($requiredProperty in @(
            "schema_version", "created_at", "stack", "container", "database", "table_count",
            "size_bytes", "sha256", "backup_file", "dump_tool"
          )) {
            if ($manifestProperties -notcontains $requiredProperty -or
                [string]::IsNullOrWhiteSpace([string]$manifest.$requiredProperty)) {
              $errors.Add("manifest is missing required field: $requiredProperty")
            }
          }
        }

        if ($manifestProperties -contains "schema_version" -and [string]$manifest.schema_version -ne "1") {
          $errors.Add("manifest schema_version is not supported: $($manifest.schema_version)")
        }
        if ($manifestProperties -contains "sha256") {
          $manifestHash = ([string]$manifest.sha256).ToLowerInvariant()
          if ($manifestHash -notmatch '^[a-f0-9]{64}$') {
            $errors.Add("manifest SHA256 is invalid")
          } elseif ($manifestHash -ne $sha256) {
            $errors.Add("manifest SHA256 does not match the backup")
          }
        }
        if ($manifestProperties -contains "size_bytes") {
          $manifestSize = 0L
          if (-not [long]::TryParse([string]$manifest.size_bytes, [ref]$manifestSize) -or $manifestSize -lt 0) {
            $errors.Add("manifest size_bytes is invalid")
          } elseif ($manifestSize -ne $sizeBytes) {
            $errors.Add("manifest size does not match the backup")
          }
        }
        if ($manifestProperties -contains "table_count") {
          $manifestTableCount = 0
          if (-not [int]::TryParse([string]$manifest.table_count, [ref]$manifestTableCount) -or $manifestTableCount -lt 1) {
            $errors.Add("manifest table_count is invalid")
          }
        }
        if ($manifestProperties -contains "backup_file" -and [string]$manifest.backup_file -cne $item.Name) {
          $errors.Add("manifest backup_file does not match the backup filename")
        }
      } catch {
        $errors.Add("manifest is invalid JSON: $($_.Exception.Message)")
      }
    } else {
      $message = "backup manifest is missing: $manifestPath"
      if ($RequireMetadata) { $errors.Add($message) } else { $warnings.Add($message) }
    }

    if ($manifest) {
      if ([string]::IsNullOrWhiteSpace([string]$manifest.stack)) {
        if ($RequireTargetMetadata) { $errors.Add("manifest stack is required to verify the restore target") }
      } elseif ($ExpectedStack -and [string]$manifest.stack -cne $ExpectedStack) {
        $errors.Add("manifest stack mismatch: expected $ExpectedStack, actual $($manifest.stack)")
      }
      if ([string]::IsNullOrWhiteSpace([string]$manifest.database)) {
        if ($RequireTargetMetadata) { $errors.Add("manifest database is required to verify the restore target") }
      } elseif ($ExpectedDatabase -and [string]$manifest.database -cne $ExpectedDatabase) {
        $errors.Add("manifest database mismatch: expected $ExpectedDatabase, actual $($manifest.database)")
      }
    } elseif ($RequireTargetMetadata) {
      $errors.Add("a valid manifest is required to verify the restore target")
    }
  }

  return [pscustomobject]@{
    IsValid = ($errors.Count -eq 0)
    FilePath = $resolvedPath
    SizeBytes = $sizeBytes
    Sha256 = $sha256
    Manifest = $manifest
    Errors = @($errors)
    Warnings = @($warnings)
  }
}

function Write-HotspotBackupValidation {
  param([Parameter(Mandatory = $true)][psobject]$Validation)

  foreach ($warning in @($Validation.Warnings)) {
    Write-Host "[validate] WARN: $warning" -ForegroundColor Yellow
  }
  foreach ($reason in @($Validation.Errors)) {
    Write-Host "[validate] FAIL: $reason" -ForegroundColor Red
  }
  if ($Validation.IsValid) {
    Write-Host "[validate] OK: $($Validation.FilePath)" -ForegroundColor Green
    Write-Host "[validate] SHA256=$($Validation.Sha256) size=$($Validation.SizeBytes)" -ForegroundColor DarkGray
  }
}

function New-HotspotMySqlBackup {
  param(
    [Parameter(Mandatory = $true)][psobject]$Context,
    [Parameter(Mandatory = $true)][string]$BackupDirectory,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$FilePrefix = "mysql",
    [string]$Purpose = "manual"
  )

  if (-not (Test-HotspotContainerRunning -Container $Context.Container)) {
    throw "MySQL container is not running: $($Context.Container)"
  }

  New-Item -ItemType Directory -Force -Path $BackupDirectory | Out-Null
  $timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
  $uniqueSuffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
  $backupFile = Join-Path $BackupDirectory "${FilePrefix}_${timestamp}_${uniqueSuffix}.sql"
  $containerTempFile = "/tmp/hotspot_mysql_backup_$([guid]::NewGuid().ToString('N')).sql"
  $tableCount = Get-HotspotMySqlTableCount -Context $Context -Database $Context.Database -AsRoot

  Write-Host "[backup] Dumping $($Context.Database) from $($Context.Container) ..." -ForegroundColor Cyan
  try {
    $dumpArguments = @(
      "exec", "-e", "MYSQL_PWD=$($Context.RootPassword)", $Context.Container,
      "mysqldump", "--user=root", "--default-character-set=utf8mb4", "--no-tablespaces",
      "--single-transaction", "--quick", "--routines", "--triggers", "--events",
      "--hex-blob", "--set-gtid-purged=OFF", "--result-file=$containerTempFile",
      $Context.Database
    )
    $dumpOutput = @(Invoke-HotspotDocker -Arguments $dumpArguments)
    $copyOutput = @(Invoke-HotspotDocker -Arguments @("cp", "$($Context.Container):$containerTempFile", $backupFile))
  } finally {
    try {
      $cleanupOutput = @(Invoke-HotspotDocker -Arguments @("exec", $Context.Container, "rm", "-f", $containerTempFile))
    } catch {
      Write-Host "[backup] WARN: failed to remove container temp file: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  }

  if (-not (Test-Path -LiteralPath $backupFile -PathType Leaf)) {
    throw "mysqldump completed without creating the local backup file."
  }

  $item = Get-Item -LiteralPath $backupFile
  $sha256 = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash.ToLowerInvariant()
  Set-Content -LiteralPath "$backupFile.sha256" -Value "$sha256  $($item.Name)" -Encoding ASCII

  $manifest = [ordered]@{
    schema_version = 1
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    stack = $Context.Stack
    container = $Context.Container
    database = $Context.Database
    table_count = $tableCount
    size_bytes = $item.Length
    sha256 = $sha256
    backup_file = $item.Name
    dump_tool = "mysqldump"
    purpose = $Purpose
  }
  $manifest | ConvertTo-Json | Set-Content -LiteralPath "$backupFile.manifest.json" -Encoding UTF8

  $validation = Test-HotspotBackupFile `
    -BackupFile $backupFile `
    -RequireMetadata `
    -RequireTargetMetadata `
    -ExpectedStack $Context.Stack `
    -ExpectedDatabase $Context.Database
  Write-HotspotBackupValidation -Validation $validation
  if (-not $validation.IsValid) {
    throw "Generated backup failed validation."
  }

  return [pscustomobject]@{
    FilePath = $backupFile
    TableCount = $tableCount
    Sha256 = $sha256
    Validation = $validation
  }
}
