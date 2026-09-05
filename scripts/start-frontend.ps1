$ErrorActionPreference = "Stop"
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "frontend")

Write-Host "[1/2] 安装前端依赖..." -ForegroundColor Cyan
npm install

Write-Host "[2/2] 启动 Vue 前端 http://localhost:5173 ..." -ForegroundColor Cyan
npm run dev
