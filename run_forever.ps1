# รันบอทค้างไว้ตลอด ดับเมื่อไหร่เปิดใหม่ให้เอง
#
# ใช้คู่กับ Task Scheduler เพื่อให้เริ่มเองตอนเปิดเครื่อง (ดูวิธีใน README)
# ปิดด้วยการปิดหน้าต่าง หรือกด Ctrl+C

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $PSScriptRoot "logs"

if (-not (Test-Path $python)) {
    Write-Host "ยังไม่ได้ติดตั้ง ให้รัน .\run.ps1 หนึ่งครั้งก่อน" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".env")) {
    Write-Host "ไม่มีไฟล์ .env — คัดลอกจาก .env.example แล้วใส่ DISCORD_TOKEN ก่อน" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# หน่วงแบบเพิ่มขึ้นเรื่อย ๆ เวลาดับซ้ำ ๆ กันวนรัวตอน token ผิดหรือเน็ตหลุด
$delay = 5
$maxDelay = 300
$restarts = 0

while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$stamp] เริ่มบอท (รีสตาร์ทมาแล้ว $restarts ครั้ง)" -ForegroundColor Cyan

    $log = Join-Path $logDir ("bot-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
    & $python -X utf8 -u bot.py 2>&1 | Tee-Object -FilePath $log -Append

    $code = $LASTEXITCODE
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($code -eq 0) {
        Write-Host "[$stamp] บอทปิดตัวเองตามปกติ จบการทำงาน" -ForegroundColor Green
        break
    }

    $restarts++
    Write-Host "[$stamp] บอทดับ (exit $code) รอ $delay วินาทีแล้วเปิดใหม่" -ForegroundColor Yellow
    Start-Sleep -Seconds $delay

    # ดับติดกันแปลว่าน่าจะมีปัญหาจริง ค่อย ๆ ถ่างเวลาออกไป
    $delay = [Math]::Min($delay * 2, $maxDelay)
}
