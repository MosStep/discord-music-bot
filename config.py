"""โหลดค่าตั้งค่าทั้งหมดจากไฟล์ .env"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    token: str
    prefix: str
    dev_guild_id: int | None
    idle_timeout: int
    default_volume: float
    ffmpeg_path: str
    cookie_file: str | None
    opus_bitrate: int | None
    normalize: bool

    @classmethod
    def load(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "ไม่พบ DISCORD_TOKEN — คัดลอก .env.example เป็น .env แล้วใส่ token ของบอทก่อน"
            )

        ffmpeg = os.getenv("FFMPEG_PATH", "").strip() or shutil.which("ffmpeg") or ""
        if not ffmpeg:
            raise SystemExit(
                "หา ffmpeg ไม่เจอ — ติดตั้ง ffmpeg แล้วใส่ไว้ใน PATH หรือกำหนด FFMPEG_PATH ใน .env"
            )

        guild_id = _int("DEV_GUILD_ID", 0)
        cookie_file = os.getenv("YTDL_COOKIE_FILE", "").strip() or None
        bitrate = _int("OPUS_BITRATE", 0)

        return cls(
            token=token,
            prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
            dev_guild_id=guild_id or None,
            idle_timeout=max(30, _int("IDLE_TIMEOUT", 300)),
            default_volume=min(max(_int("DEFAULT_VOLUME", 100), 0), 200) / 100,
            ffmpeg_path=ffmpeg,
            cookie_file=cookie_file,
            opus_bitrate=min(max(bitrate, 16), 512) if bitrate else None,
            normalize=_int("AUDIO_NORMALIZE", 0) == 1,
        )
