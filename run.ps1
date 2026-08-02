# ติดตั้ง dependency แล้วรันบอท (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "สร้าง virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "สร้างไฟล์ .env แล้ว — ใส่ DISCORD_TOKEN ก่อนรันอีกครั้ง" -ForegroundColor Yellow
    exit 1
}

& ".venv\Scripts\python.exe" bot.py
