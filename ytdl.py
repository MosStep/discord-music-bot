"""ค้นหา/ดึงข้อมูลจาก YouTube ด้วย yt-dlp (รันใน thread แยกไม่ให้บล็อก event loop)"""

from __future__ import annotations

import asyncio
import functools
import re
import urllib.parse
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


def wants_playlist(url: str) -> bool:
    """ลิงก์นี้มีเพลย์ลิสต์ให้ดึงไหม

    มี list= ก็ดึงมาทั้งชุด รวมถึง Mix/Radio (list=RD...) ที่ YouTube สร้างสด ๆ
    Mix ไม่มีจุดจบในตัวมันเอง แต่ playlistend จำกัดจำนวนไว้แล้ว จึงหยุดได้แน่นอน
    """
    if not _URL_RE.match(url):
        return False

    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return bool((params.get("list") or [""])[0])


def _base_opts(
    cookie_file: str | None, max_playlist: int = 100, sleep_requests: float = 0.8
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        # ไม่จำกัด bitrate — เอาไฟล์เสียงที่ดีที่สุดที่ YouTube มีให้
        "format": "bestaudio/best",
        # เอา opus ก่อนเพราะเป็น 48kHz อยู่แล้ว ตรงกับที่ Discord ใช้พอดี ไม่ต้อง resample
        # (m4a ของ YouTube เป็น 44.1kHz ต้องแปลงเรต ซึ่งกินซีพียูจนเสียงกระตุกได้)
        # แล้วค่อยเรียงตาม bitrate สูงสุด
        "format_sort": ["acodec:opus", "abr", "asr"],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "ignoreerrors": False,
        "nocheckcertificate": True,
        "cachedir": False,
        "retries": 3,
        "extractor_retries": 3,
        "socket_timeout": 15,
        "default_search": "ytsearch",
        "source_address": "0.0.0.0",
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        # YouTube ไม่ประกาศลิมิตไว้ แต่ยิงรัว ๆ จะโดนกันเป็นชั่วโมง
        # หน่วงระหว่างคำขอกับจำกัดจำนวนเพลงต่อครั้ง คือวิธีที่กันได้จริง
        "sleep_interval_requests": sleep_requests,
        "playlistend": max_playlist,
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


def _flat_track(entry: dict[str, Any]) -> Track:
    """แปลงรายการแบบย่อ (extract_flat) เป็น Track

    ไม่มีลิงก์สตรีมกับรูปปก แต่ไม่เป็นไร เพราะตัวเล่นจะไปดึงข้อมูลเต็มตอนใกล้ถึงคิวอยู่แล้ว
    """
    return Track(
        title=entry.get("title") or "ไม่ทราบชื่อ",
        webpage_url=entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
        duration=int(entry["duration"]) if entry.get("duration") else None,
        thumbnail=entry.get("thumbnail"),
        uploader=entry.get("uploader") or entry.get("channel"),
    )


class YTDLClient:
    def __init__(
        self,
        cookie_file: str | None = None,
        *,
        max_playlist: int = 100,
        sleep_requests: float = 0.8,
    ) -> None:
        self._cookie_file = cookie_file
        self._max_playlist = max_playlist
        self._sleep_requests = sleep_requests

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
        """แปลงคำค้นหรือลิงก์เป็นรายการเพลง (เพลย์ลิสต์ได้ทั้งชุด สูงสุดตาม max_playlist)"""
        expand = allow_playlist and wants_playlist(query)

        opts = _base_opts(self._cookie_file, self._max_playlist, self._sleep_requests)
        opts["noplaylist"] = not expand
        if expand:
            # ดึงแบบย่อ: ขอครั้งเดียวได้ทั้งรายการ
            # ถ้าดึงเต็มทีละเพลง 100 เพลงจะกลายเป็น 100 คำขอ รอนานและเสี่ยงโดนจำกัดอัตรา
            opts["extract_flat"] = "in_playlist"

        info = await self._extract(query, opts)
        if not info:
            raise ExtractError("ไม่พบผลลัพธ์")

        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            tracks = [_flat_track(e) if expand else _to_track(e) for e in entries]
        else:
            tracks = [_to_track(info)]

        if not tracks:
            raise ExtractError("ไม่พบผลลัพธ์")
        return tracks[: self._max_playlist]

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        """ค้นหาแบบเร็ว (flat) สำหรับเมนูให้ผู้ใช้เลือก"""
        opts = _base_opts(self._cookie_file, self._max_playlist, self._sleep_requests)
        opts.update({"extract_flat": "in_playlist", "noplaylist": True})

        info = await self._extract(f"ytsearch{limit}:{query}", opts)
        entries = (info or {}).get("entries") or []
        return [
            _flat_track(e)
            for e in entries
            if e
        ]

    async def refresh_stream(self, track: Track) -> str:
        """ดึง URL สตรีมสด ๆ ตอนกำลังจะเล่น"""
        opts = _base_opts(self._cookie_file, self._max_playlist, self._sleep_requests)
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
