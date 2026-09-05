$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

docker compose --env-file .env -f docker-compose.prod.yml down
if ($LASTEXITCODE -ne 0) {
  throw "Production Compose shutdown failed."
}

Write-Host "[prod] Production stack stopped. Data volumes are kept." -ForegroundColor Green
Write-Host "To remove data volumes manually, run: docker compose --env-file .env -f docker-compose.prod.yml down -v"
