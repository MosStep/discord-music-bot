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
   สิทธิ์ที่ต้องใช้: `Connect`, `Speak`, `Send Messages`, `Embed Links`,
   `Read Message History`, `Create Instant Invite` (ตัวสุดท้ายจำเป็นสำหรับ `/v`)
5. เปิดลิงก์ที่ได้เพื่อเชิญบอทเข้าเซิร์ฟเวอร์

ใส่ `DEV_GUILD_ID` เป็น id เซิร์ฟเวอร์ของคุณ แล้ว slash command จะขึ้นทันที (ถ้าเว้นว่างจะ sync แบบ global ซึ่งใช้เวลาถึง 1 ชั่วโมง)

## คำสั่ง

| คำสั่ง | ย่อ | ทำอะไร |
| --- | --- | --- |
| `/pa <ชื่อเพลง หรือ ลิงก์>` | `p` | เล่นเพลง ใส่ลิงก์ playlist ได้ทั้งชุด |
| `/play <ชื่อเพลง หรือ ลิงก์>` | | เหมือน `/pa` ทุกอย่าง |
| `/pn <เพลง>` | `playnext` | แทรกเป็นคิวถัดไป |
| `/v [ชื่อ หรือ ลิงก์]` | `video`, `watch` | เปิด Watch Together ดูวิดีโอพร้อมกันในห้องเสียง |
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
| `PLAY_PICKER` | `1` | พิมพ์ชื่อเพลงแล้วขึ้นเมนูให้เลือก |
| `AUDIO_NORMALIZE` | `0` | ปรับความดังให้เท่ากันทุกเพลง |
| `FFMPEG_PATH` | ว่าง | path ของ ffmpeg ถ้าไม่ได้อยู่ใน PATH |
| `YTDL_COOKIE_FILE` | ว่าง | ไฟล์ cookies เมื่อ YouTube ขอยืนยันตัวตน |

## ย้ายไปรันบนเครื่องอื่น

บนเครื่องใหม่ ติดตั้ง [Git](https://git-scm.com/download/win) ก่อน แล้วเปิด PowerShell:

```powershell
git clone https://github.com/MosStep/discord-music-bot.git
cd discord-music-bot
.\setup.ps1
```

`setup.ps1` จะตรวจและติดตั้ง Python กับ ffmpeg ให้ถ้ายังไม่มี สร้าง virtual environment
ลง dependency และเตรียมไฟล์ `.env` ให้พร้อม เหลือแค่ใส่ token

**อย่าคัดลอกไฟล์ `.env` ข้ามเครื่องผ่านคลาวด์หรือแชท** เพราะมี token อยู่ข้างใน
ให้ไปกด Reset Token ใหม่ที่ Developer Portal แล้วพิมพ์ลงเครื่องใหม่โดยตรง
ปลอดภัยกว่าและใช้เวลาไม่ถึงนาที

เสร็จแล้วรัน `.\run_forever.ps1` และตั้ง Task Scheduler ตามหัวข้อถัดไป

**รันบอทได้ทีละเครื่องเท่านั้น** ถ้าเปิดสองเครื่องพร้อมกันด้วย token เดียวกัน
บอทจะตอบทุกคำสั่งซ้ำสองรอบและแย่งกันเข้าห้องเสียง

## ให้บอทออนไลน์ 24 ชั่วโมง

### วิธีที่แนะนำ — รันบนเครื่องตัวเอง (ฟรีจริง)

YouTube บล็อก IP ของ datacenter หนักมาก บอทที่รันบนคลาวด์มักเจอ
"Sign in to confirm you're not a bot" ภายในไม่กี่ชั่วโมง ขณะที่เครื่องที่บ้าน
เป็น IP บ้านจริงซึ่งแทบไม่โดน ข้อได้เปรียบนี้ใหญ่กว่าความสะดวกของคลาวด์มาก

```powershell
.\run_forever.ps1
```

สคริปต์นี้รันบอทค้างไว้ ดับเมื่อไหร่เปิดใหม่ให้เอง พร้อมหน่วงเวลาแบบเพิ่มขึ้นเรื่อย ๆ
เวลาดับซ้ำ ๆ และเก็บ log ไว้ในโฟลเดอร์ `logs/`

**ให้เริ่มเองตอนเปิดเครื่อง** — เปิด Task Scheduler แล้วสร้าง task ใหม่:

| ช่อง | ค่า |
| --- | --- |
| Trigger | At log on |
| Action | Start a program |
| Program | `powershell.exe` |
| Arguments | `-WindowStyle Hidden -ExecutionPolicy Bypass -File "<path เต็มของ run_forever.ps1>"` |

หรือสั่งจาก PowerShell ทีเดียว (แก้ path ให้ตรงเครื่องคุณก่อน):

```powershell
schtasks /create /tn "DiscordMusicBot" /tr "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File \"C:\path\to\aa\run_forever.ps1\"" /sc onlogon /rl highest
```

อย่าลืมตั้งไม่ให้เครื่องหลับด้วย: Settings → System → Power → Screen and sleep → ตั้ง Sleep เป็น Never

### ทางเลือกบนคลาวด์

| บริการ | ฟรีจริงไหม | ข้อจำกัด |
| --- | --- | --- |
| **Oracle Cloud** | ฟรีถาวร | ตัวเลือกคลาวด์ที่ดีที่สุด ARM 4 core / 24GB แต่สมัครยาก ต้องใส่บัตร และบางเขตเต็มตลอด |
| **Google Cloud** | ฟรีถาวร | e2-micro 1GB RAM เฉพาะบางเขตในสหรัฐ พอรันได้แต่ไม่เหลือมาก |
| **Render** | ฟรีมีเงื่อนไข | Background Worker เสียเงินอย่างเดียว ต้องรันเป็น Web Service ซึ่งหลับหลังไม่มีคนเรียก 15 นาที ต้องมีตัวปลุกจากข้างนอก |
| **Railway** | **ไม่ฟรีแล้ว** | ตัดฟรีทิ้งตั้งแต่ปี 2023 เหลือเครดิตทดลอง $5 แล้วต้องจ่าย $5/เดือน |

ทุกทางบนคลาวด์เจอปัญหา IP datacenter เหมือนกันหมด ถ้าจะใช้จริงต้องเตรียม
cookies ของ YouTube ไว้ด้วย (ดูหัวข้อแก้ปัญหาด้านล่าง) และยอมรับว่าอาจต้องอัปเดต
cookies เป็นระยะ

มี `Dockerfile` กับ `render.yaml` เตรียมไว้ให้แล้วถ้าจะลอง — deploy ด้วย Docker
ได้ทุกเจ้าที่รองรับ container

## แก้ปัญหาที่เจอบ่อย

**"Sign in to confirm you're not a bot"** — YouTube กันบอทอยู่ ให้ export cookies จากเบราว์เซอร์เป็นไฟล์ Netscape แล้วชี้ `YTDL_COOKIE_FILE` ไปที่ไฟล์นั้น

**เล่นได้แต่ไม่มีเสียง** — libopus โหลดไม่ขึ้น ลอง `pip install --force-reinstall PyNaCl`

**เพลงหยุดกลางคัน** — ปกติเป็นเน็ตสะดุด บอทตั้ง `-reconnect` ไว้แล้ว ถ้ายังเป็นบ่อยลองอัปเดต `yt-dlp` เป็นเวอร์ชันล่าสุด

**slash command ไม่ขึ้น** — ใส่ `DEV_GUILD_ID` แล้วรีสตาร์ทบอท

## เปิดวิดีโอ — `/v`

บอท Discord **สตรีมวิดีโอเข้าห้องเสียงไม่ได้** Go Live กับแชร์หน้าจอเป็นฟีเจอร์ฝั่งผู้ใช้เท่านั้น การทำให้ได้ต้องใช้ user account ปลอมเป็นคน ซึ่งผิด ToS ของ Discord

ทางที่ทำได้จริงคือ **Watch Together** ซึ่ง `/v` เปิดให้ — เป็น Discord Activity ที่ทุกคนในห้องเสียงดูวิดีโอเดียวกัน เล่น/หยุด/เลื่อนเวลาตรงกันหมด มีคิวร่วมกันด้วย

```
/v                      เปิด Watch Together เปล่า ๆ แล้วไปค้นในนั้นเอง
/v ชื่อวิดีโอ            เปิดพร้อมแนบลิงก์วิดีโอที่หาให้ ไปวางในช่องค้นหาของ activity
```

ข้อจำกัด: Discord ไม่เปิดช่องให้ตั้งวิดีโอล่วงหน้าผ่าน API ได้ บอทจึงทำได้แค่เปิด activity แล้วส่งลิงก์วิดีโอมาให้วางเอง

บอทต้องมีสิทธิ์ **Create Instant Invite** ในห้องเสียงนั้น ไม่งั้น `/v` จะแจ้งว่าไม่มีสิทธิ์

## เลือกเพลงเองเมื่อชื่อซ้ำ

พิมพ์ชื่อเพลง (ไม่ใช่ลิงก์) แล้ว `/pa` จะขึ้นเมนู 5 อันดับให้เลือก เพราะเพลงชื่อคล้ายกันเยอะ ระบบเดาเองมักได้ไม่ตรง

- **ไม่เลือกภายใน 3 วินาที** บอทจะเล่นอันดับ 1 ให้เอง ไม่ต้องรอ
- เฉพาะคนที่พิมพ์คำสั่งเท่านั้นที่กดเมนูได้
- ใส่ลิงก์มาจะเล่นทันที ไม่ถาม
- ปิดเมนูได้ด้วย `PLAY_PICKER=0` ใน `.env` (จะเล่นอันดับ 1 ทันทีเสมอ)
