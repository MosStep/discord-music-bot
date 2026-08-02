"""ค้นหา/ดึงข้อมูลจาก YouTube ด้วย yt-dlp (รันใน thread แยกไม่ให้บล็อก event loop)"""

from __future__ import annotations

import asyncio
import functools
import re
from dataclasses import dataclass, field
from typing import Any

import yt_dlp

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# ปิด logger ของ yt-dlp ไม่ให้รกคอนโซล
yt_dlp.utils.bug_reports_message = lambda *_args, **_kwargs: ""


class ExtractError(Exception):
    """ดึงข้อมูลวิดีโอไม่สำเร็จ"""


@dataclass(slots=True)
class Track:
    """หนึ่งเพลงในคิว — เก็บแค่ข้อมูล metadata

    ลิงก์สตรีมจริงจะไปดึงตอนกำลังจะเล่น เพราะ URL ของ YouTube หมดอายุใน ~6 ชม.
    """

    title: str
    webpage_url: str
    duration: int | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    requester_id: int | None = None
    requester_name: str = "unknown"
    stream_url: str | None = field(default=None, repr=False)

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return "LIVE"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @property
    def markdown(self) -> str:
        return f"[{self.title}]({self.webpage_url})"


def _base_opts(cookie_file: str | None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        # ไม่จำกัด bitrate — เอาไฟล์เสียงที่ดีที่สุดที่ YouTube มีให้
        "format": "bestaudio/best",
        # เรียงลำดับความสำคัญเอง: bitrate สูงสุดก่อน แล้วค่อยเลือก opus (คุณภาพต่อ bit ดีกว่า aac)
        "format_sort": ["abr", "acodec:opus", "asr"],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "ignoreerrors": False,
        "nocheckcertificate": True,
        "cachedir": False,
        "retries": 3,
        "socket_timeout": 15,
        "default_search": "ytsearch",
        "source_address": "0.0.0.0",
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file
    return opts


def _to_track(info: dict[str, Any]) -> Track:
    return Track(
        title=info.get("title") or "ไม่ทราบชื่อ",
        webpage_url=info.get("webpage_url") or info.get("url") or "",
        duration=int(info["duration"]) if info.get("duration") else None,
        thumbnail=info.get("thumbnail"),
        uploader=info.get("uploader") or info.get("channel"),
        stream_url=info.get("url"),
    )


class YTDLClient:
    def __init__(self, cookie_file: str | None = None) -> None:
        self._cookie_file = cookie_file

    async def _extract(self, query: str, opts: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        def run() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(query, download=False)

        try:
            return await loop.run_in_executor(None, functools.partial(run))
        except yt_dlp.utils.DownloadError as exc:
            raise ExtractError(_clean_error(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001 - yt-dlp โยน error ได้หลากหลายมาก
            raise ExtractError(str(exc)) from exc

    async def resolve(self, query: str, *, allow_playlist: bool = True) -> list[Track]:
        """แปลงคำค้นหรือลิงก์เป็นรายการเพลง (playlist ได้ทั้งอัลบั้ม)"""
        opts = _base_opts(self._cookie_file)
        opts["noplaylist"] = not (allow_playlist and _URL_RE.match(query))

        info = await self._extract(query, opts)
        if not info:
            raise ExtractError("ไม่พบผลลัพธ์")

        entries = info["entries"] if info.get("_type") == "playlist" else [info]
        tracks = [_to_track(e) for e in entries if e]
        if not tracks:
            raise ExtractError("ไม่พบผลลัพธ์")
        return tracks

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        """ค้นหาแบบเร็ว (flat) สำหรับเมนูให้ผู้ใช้เลือก"""
        opts = _base_opts(self._cookie_file)
        opts.update({"extract_flat": "in_playlist", "noplaylist": True})

        info = await self._extract(f"ytsearch{limit}:{query}", opts)
        entries = (info or {}).get("entries") or []
        return [
            Track(
                title=e.get("title") or "ไม่ทราบชื่อ",
                webpage_url=e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}",
                duration=int(e["duration"]) if e.get("duration") else None,
                uploader=e.get("uploader") or e.get("channel"),
            )
            for e in entries
            if e
        ]

    async def refresh_stream(self, track: Track) -> str:
        """ดึง URL สตรีมสด ๆ ตอนกำลังจะเล่น"""
        opts = _base_opts(self._cookie_file)
        opts["noplaylist"] = True

        info = await self._extract(track.webpage_url, opts)
        url = (info or {}).get("url")
        if not url:
            # บางกรณี yt-dlp คืน formats มาแทน field url ตรง ๆ
            formats = (info or {}).get("formats") or []
            audio = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("url")]
            if audio:
                url = audio[-1]["url"]
        if not url:
            raise ExtractError(f"ดึงลิงก์เสียงของ {track.title} ไม่ได้")

        track.stream_url = url
        if info.get("duration") and not track.duration:
            track.duration = int(info["duration"])
        return url


def _clean_error(message: str) -> str:
    message = re.sub(r"\x1b\[[0-9;]*m", "", message)
    message = message.replace("ERROR: ", "").strip()
    return message[:300]
