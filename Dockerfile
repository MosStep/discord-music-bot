FROM python:3.12-slim

# ffmpeg เป็นตัวถอดรหัสเสียง ไม่มีไม่ได้
# libopus0 ให้ discord.py เข้ารหัสเสียงส่งเข้า Discord
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ลง dependency แยกชั้นก่อน จะได้ใช้ cache ตอน build ซ้ำ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
