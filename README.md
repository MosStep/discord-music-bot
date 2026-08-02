# aa — บอท Discord เปิดเพลงจาก YouTube

บอทเปิดเพลงในห้องเสียง Discord เน้น **คุณภาพเสียงสูงสุดเท่าที่ Discord รองรับ** รองรับคำสั่งทั้งแบบ slash (`/play`) และแบบพิมพ์ (`!play`)

## ติดตั้ง

ต้องมี **Python 3.10+** และ **ffmpeg** ก่อน

```powershell
.\run.ps1
```

สคริปต์จะสร้าง virtual environment ติดตั้ง dependency และสร้างไฟล์ `.env` ให้ รอบแรกจะหยุดให้ไปใส่ token ก่อน แล้วรันซ้ำอีกครั้ง

ถ้าอยากทำเองทีละขั้น:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python bot.py
```

## ตั้งค่าบอทใน Discord

1. เข้า https://discord.com/developers/applications → **New Application**
2. แท็บ **Bot** → **Reset Token** → คัดลอกไปใส่ `DISCORD_TOKEN` ใน `.env`
3. แท็บ **Bot** → เปิด **MESSAGE CONTENT INTENT** (จำเป็นสำหรับคำสั่งแบบ prefix)
4. แท็บ **OAuth2 → URL Generator** → ติ๊ก `bot` + `applications.commands`
   สิทธิ์ที่ต้องใช้: `Connect`, `Speak`, `Send Messages`, `Embed Links`, `Read Message History`
5. เปิดลิงก์ที่ได้เพื่อเชิญบอทเข้าเซิร์ฟเวอร์

ใส่ `DEV_GUILD_ID` เป็น id เซิร์ฟเวอร์ของคุณ แล้ว slash command จะขึ้นทันที (ถ้าเว้นว่างจะ sync แบบ global ซึ่งใช้เวลาถึง 1 ชั่วโมง)

## คำสั่ง

| คำสั่ง | ย่อ | ทำอะไร |
| --- | --- | --- |
| `/play <ชื่อเพลง หรือ ลิงก์>` | `p` | เล่นเพลง ใส่ลิงก์ playlist ได้ทั้งชุด |
| `/playnext <เพลง>` | `pn` | แทรกเป็นคิวถัดไป |
| `/search <คำค้น>` | | ค้นหา 5 อันดับแล้วเลือกจากเมนู |
| `/skip [จำนวน]` | `s` | ข้ามเพลง |
| `/pause` `/resume` | `r` | หยุด / เล่นต่อ |
| `/seek <เวลา>` | | กระโดดไปเวลาที่ต้องการ เช่น `1:30` |
| `/stop` | | หยุดและล้างคิว |
| `/queue [หน้า]` | `q` | ดูคิว |
| `/nowplaying` | `np` | เพลงที่กำลังเล่น + แถบความคืบหน้า |
| `/shuffle` `/clear` | | สลับคิว / ล้างคิว |
| `/remove <ลำดับ>` `/move <จาก> <ไป>` | | จัดการคิว |
| `/loop <off\|track\|queue>` | | เล่นซ้ำ |
| `/volume [0-200]` | `vol` | ปรับเสียง |
| `/quality` | | ดูสายสัญญาณเสียงที่ใช้อยู่ |
| `/join` `/leave` | `dc` | เข้า / ออกห้องเสียง |

## เรื่องคุณภาพเสียง

สายสัญญาณทั้งเส้น:

```
YouTube (opus สูงสุดที่มี) → ffmpeg → PCM 48kHz stereo → Opus encoder → Discord
```

สิ่งที่บอทตัวนี้ทำต่างจากบอททั่วไป:

- **ไม่จำกัด bitrate ตอนดึงไฟล์** — `format_sort` เรียง abr สูงสุดก่อน แล้วค่อยเลือก opus (YouTube opus 160k เสียงดีกว่า m4a 128k ที่บอทส่วนใหญ่ได้ไป)
- **soxr precision 28 + triangular dither** — resampler คุณภาพสูงสุดของ ffmpeg แทนตัวเริ่มต้น
- **จูน Opus encoder ตาม bitrate ของห้องเสียง** — discord.py ตั้งไว้ที่ 128 kbps ตายตัว ทั้งที่ห้องที่บูสต์แล้วรับได้ถึง 384 kbps บอทจะจูนใหม่ทุกครั้งที่เริ่มเพลง พร้อมตั้ง `signal_type=music`, `bandwidth=full` และปิด FEC
- **ระดับเสียงเริ่มต้น 100%** เพราะการหรี่เสียงในบอทคือการคูณ sample 16-bit ซึ่งเสียคุณภาพ ให้ไปหรี่ที่ตัวผู้ใช้ใน Discord แทน

**ตัวจำกัดที่แท้จริงคือ bitrate ของห้องเสียง** ไม่ใช่โค้ด — ห้องปกติได้ 64 kbps เท่านั้น ถ้าอยากได้เสียงดีจริงต้องเข้าไปตั้งค่าห้องเสียง → เลื่อน Bitrate ขึ้น (เซิร์ฟเวอร์ที่บูสต์ระดับ 3 ได้ถึง 384 kbps) พิมพ์ `/quality` เพื่อดูว่าตอนนี้ได้เท่าไหร่

ถ้าอยากให้ทุกเพลงดังเท่ากัน ตั้ง `AUDIO_NORMALIZE=1` ใน `.env` (แลกมาด้วยการบีบไดนามิกเล็กน้อย)

## ตั้งค่าใน .env

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
| --- | --- | --- |
| `DISCORD_TOKEN` | — | token ของบอท (จำเป็น) |
| `COMMAND_PREFIX` | `!` | prefix คำสั่งแบบพิมพ์ |
| `DEV_GUILD_ID` | ว่าง | sync slash command เข้าเซิร์ฟเวอร์นี้ทันที |
| `IDLE_TIMEOUT` | `300` | ไม่มีเพลงกี่วินาทีแล้วออกจากห้อง |
| `DEFAULT_VOLUME` | `100` | ระดับเสียงเริ่มต้น |
| `OPUS_BITRATE` | ว่าง | บังคับ bitrate (kbps) เว้นว่าง = ตามห้องเสียง |
| `AUDIO_NORMALIZE` | `0` | ปรับความดังให้เท่ากันทุกเพลง |
| `FFMPEG_PATH` | ว่าง | path ของ ffmpeg ถ้าไม่ได้อยู่ใน PATH |
| `YTDL_COOKIE_FILE` | ว่าง | ไฟล์ cookies เมื่อ YouTube ขอยืนยันตัวตน |

## แก้ปัญหาที่เจอบ่อย

**"Sign in to confirm you're not a bot"** — YouTube กันบอทอยู่ ให้ export cookies จากเบราว์เซอร์เป็นไฟล์ Netscape แล้วชี้ `YTDL_COOKIE_FILE` ไปที่ไฟล์นั้น

**เล่นได้แต่ไม่มีเสียง** — libopus โหลดไม่ขึ้น ลอง `pip install --force-reinstall PyNaCl`

**เพลงหยุดกลางคัน** — ปกติเป็นเน็ตสะดุด บอทตั้ง `-reconnect` ไว้แล้ว ถ้ายังเป็นบ่อยลองอัปเดต `yt-dlp` เป็นเวอร์ชันล่าสุด

**slash command ไม่ขึ้น** — ใส่ `DEV_GUILD_ID` แล้วรีสตาร์ทบอท

## เปิดวิดีโอ

บอท Discord **สตรีมวิดีโอเข้าห้องเสียงไม่ได้** — Go Live กับแชร์หน้าจอเป็นฟีเจอร์ฝั่งผู้ใช้เท่านั้น การทำให้ได้ต้องใช้ user account ปลอมเป็นคน ซึ่งผิด ToS ของ Discord

ทางที่ทำได้จริงคือ **Watch Together** (Discord Activity ของ YouTube) ที่ทุกคนในห้องเสียงดูวิดีโอเดียวกันแบบ sync ตรงกัน — ยังไม่ได้ทำในเวอร์ชันนี้
