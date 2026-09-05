$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import langchain; print('langchain', langchain.__version__)"
