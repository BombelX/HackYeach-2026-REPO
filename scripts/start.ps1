$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "server\.venv")) {
  python -m venv "server\.venv"
}
& "server\.venv\Scripts\python.exe" -m pip install -r "server\requirements.txt"

Set-Location "$root\web"
if (-not (Test-Path "node_modules")) {
  npm install
}

Write-Host "Starting API on :8000 and Vite on :5173"
Write-Host "Admin: http://localhost:5173/admin  password: hackyeah"
Write-Host "Tunnel: cloudflared tunnel --url http://127.0.0.1:5173"

Start-Process -WorkingDirectory "$root\server" -FilePath "$root\server\.venv\Scripts\uvicorn.exe" -ArgumentList "app:app --host 127.0.0.1 --port 8000"
Start-Process -WorkingDirectory "$root\web" -FilePath "npm" -ArgumentList "run","dev"
