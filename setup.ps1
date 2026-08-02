# ติดตั้งบอทบนเครื่องใหม่ตั้งแต่ต้น — รันครั้งเดียวจบ
#
#   .\setup.ps1
#
# ตรวจของที่ต้องมี ติดตั้งให้ถ้าขาด แล้วเตรียมไฟล์ตั้งค่าให้พร้อมใช้

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step($msg) { Write-Host "`n[ขั้นตอน] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "  !   $msg" -ForegroundColor Yellow }

Write-Host "ติดตั้งบอทเพลง Discord" -ForegroundColor Magenta

# ---------------------------------------------------------------- Python
Write-Step "ตรวจ Python"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($python) {
    $ver = & python --version
    Write-Ok "$ver"
} else {
    Write-Warn2 "ไม่พบ Python กำลังติดตั้งผ่าน winget"
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Write-Warn2 "ติดตั้งเสร็จแล้ว ปิดหน้าต่างนี้ เปิด PowerShell ใหม่ แล้วรัน .\setup.ps1 อีกครั้ง"
    Write-Warn2 "(ต้องเปิดใหม่เพื่อให้ระบบเห็นคำสั่ง python)"
    exit 1
}

# ---------------------------------------------------------------- ffmpeg
Write-Step "ตรวจ ffmpeg"
$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if ($ffmpeg) {
    Write-Ok "เจอที่ $ffmpeg"
} else {
    Write-Warn2 "ไม่พบ ffmpeg กำลังติดตั้งผ่าน winget"
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    Write-Warn2 "ติดตั้งเสร็จแล้ว ปิดหน้าต่างนี้ เปิด PowerShell ใหม่ แล้วรัน .\setup.ps1 อีกครั้ง"
    exit 1
}

# ---------------------------------------------------------------- venv
Write-Step "เตรียม virtual environment"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Ok "สร้าง .venv แล้ว"
} else {
    Write-Ok "มี .venv อยู่แล้ว"
}

Write-Step "ติดตั้ง dependency"
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
Write-Ok "ติดตั้งครบแล้ว"

# ---------------------------------------------------------------- .env
Write-Step "เตรียมไฟล์ตั้งค่า"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok "สร้าง .env จากตัวอย่างแล้ว"
    $needToken = $true
} else {
    Write-Ok "มี .env อยู่แล้ว ไม่ทับให้"
    $token = (Select-String -Path ".env" -Pattern "^DISCORD_TOKEN=(.+)$").Matches.Groups[1].Value
    $needToken = [string]::IsNullOrWhiteSpace($token)
}

Write-Host "`n----------------------------------------" -ForegroundColor Magenta

if ($needToken) {
    Write-Host "เหลืออีกขั้นเดียว: ใส่ token ของบอท" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. เปิด https://discord.com/developers/applications"
    Write-Host "  2. เลือกแอปของคุณ -> แท็บ Bot -> Reset Token -> Copy"
    Write-Host "  3. วางลงในไฟล์ .env บรรทัด DISCORD_TOKEN="
    Write-Host "  4. ใส่ DEV_GUILD_ID ด้วย (คลิกขวาไอคอนเซิร์ฟเวอร์ -> Copy Server ID)"
    Write-Host ""
    $open = Read-Host "เปิดไฟล์ .env ให้เลยไหม (y/n)"
    if ($open -eq "y") { notepad .env }
    Write-Host ""
    Write-Host "ใส่เสร็จแล้วรัน:  .\run_forever.ps1" -ForegroundColor Cyan
} else {
    Write-Host "พร้อมใช้งานแล้ว รันได้เลย:" -ForegroundColor Green
    Write-Host ""
    Write-Host "  .\run_forever.ps1        รันค้างไว้ ดับแล้วเปิดใหม่ให้เอง" -ForegroundColor Cyan
    Write-Host "  .\run.ps1                รันครั้งเดียว ใช้ตอนทดสอบ" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "อยากให้เริ่มเองตอนเปิดเครื่อง ดูหัวข้อ 'ให้บอทออนไลน์ 24 ชั่วโมง' ใน README.md"
