"""ตัวจัดการคิวและการเล่นเพลงของแต่ละเซิร์ฟเวอร์"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from enum import Enum

import discord

from audio import build_source, tune_encoder
from config import Config
from ytdl import ExtractError, Track, YTDLClient

log = logging.getLogger(__name__)


class LoopMode(str, Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"

    @property
    def label(self) -> str:
        return {"off": "ปิด", "track": "วนเพลงเดียว", "queue": "วนทั้งคิว"}[self.value]


class GuildPlayer:
    """หนึ่งตัวต่อหนึ่งเซิร์ฟเวอร์ — ถือคิว สถานะ และ task ที่คอยเล่นเพลงถัดไป"""

    def __init__(
        self,
        cfg: Config,
        ytdl: YTDLClient,
        voice_client: discord.VoiceClient,
        text_channel: discord.abc.Messageable,
    ) -> None:
        self.cfg = cfg
        self.ytdl = ytdl
        self.voice = voice_client
        self.text_channel = text_channel

        self.queue: deque[Track] = deque()
        self.history: deque[Track] = deque(maxlen=25)
        self.current: Track | None = None
        self.loop_mode = LoopMode.OFF
        self.bitrate: int | None = None

        self._volume = cfg.default_volume
        self._advance = asyncio.Event()
        self._has_work = asyncio.Event()
        self._closing = False

        # ใช้คำนวณว่าเล่นมาถึงวินาทีไหนแล้ว
        self._loop = asyncio.get_running_loop()
        self._started_at = 0.0
        self._seek_offset = 0.0
        self._paused_at: float | None = None

        self._runner = self._loop.create_task(self._run(), name=f"player-{voice_client.guild.id}")

    # ---------------------------------------------------------------- สถานะ

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(value, 2.0))
        source = self.voice.source
        if isinstance(source, discord.PCMVolumeTransformer):
            source.volume = self._volume

    @property
    def is_playing(self) -> bool:
        return self.voice.is_connected() and (self.voice.is_playing() or self.voice.is_paused())

    @property
    def position(self) -> float:
        """เล่นมาแล้วกี่วินาที"""
        if not self.current or not self._started_at:
            return 0.0
        end = self._paused_at if self._paused_at is not None else self._loop.time()
        return self._seek_offset + max(0.0, end - self._started_at)

    def progress_bar(self, width: int = 22) -> str:
        total = self.current.duration if self.current else None
        if not total:
            return "🔴 ถ่ายทอดสด"
        ratio = min(max(self.position / total, 0.0), 1.0)
        filled = int(ratio * width)
        return "▬" * filled + "🔘" + "▬" * (width - filled)

    # ---------------------------------------------------------------- คิว

    def add(self, tracks: list[Track], *, front: bool = False) -> None:
        if front:
            self.queue.extendleft(reversed(tracks))
        else:
            self.queue.extend(tracks)
        self._has_work.set()

    def shuffle(self) -> None:
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)

    def clear(self) -> None:
        self.queue.clear()

    def remove(self, index: int) -> Track | None:
        """ลบเพลงลำดับที่ index (เริ่มนับจาก 1)"""
        if not 1 <= index <= len(self.queue):
            return None
        items = list(self.queue)
        track = items.pop(index - 1)
        self.queue = deque(items)
        return track

    def move(self, src: int, dst: int) -> Track | None:
        if not (1 <= src <= len(self.queue) and 1 <= dst <= len(self.queue)):
            return None
        items = list(self.queue)
        track = items.pop(src - 1)
        items.insert(dst - 1, track)
        self.queue = deque(items)
        return track

    @property
    def total_duration(self) -> int:
        return sum(t.duration or 0 for t in self.queue)

    # ---------------------------------------------------------------- ควบคุม

    def skip(self) -> bool:
        if not self.is_playing:
            return False
        # หยุด source ปัจจุบัน -> callback after จะปลุก loop ให้ไปเพลงถัดไปเอง
        self.voice.stop()
        return True

    def pause(self) -> bool:
        if not self.voice.is_playing():
            return False
        self.voice.pause()
        self._paused_at = self._loop.time()
        return True

    def resume(self) -> bool:
        if not self.voice.is_paused():
            return False
        if self._paused_at is not None:
            # ชดเชยเวลาที่หยุดไป ไม่ให้ตัวนับเดินหน้าระหว่าง pause
            self._started_at += self._loop.time() - self._paused_at
            self._paused_at = None
        self.voice.resume()
        return True

    async def seek(self, seconds: float) -> bool:
        """กระโดดไปวินาทีที่กำหนดโดยเปิดสตรีมใหม่พร้อม -ss"""
        track = self.current
        if not track or not track.duration:
            return False
        seconds = max(0.0, min(seconds, track.duration - 1))

        try:
            url = await self.ytdl.refresh_stream(track)
        except ExtractError:
            return False

        self.voice.stop()
        await asyncio.sleep(0.2)  # รอให้ source เดิมปิดสนิทก่อน
        self._start(track, url, seek=seconds)
        return True

    def stop(self) -> None:
        self.queue.clear()
        self.loop_mode = LoopMode.OFF
        if self.is_playing:
            self.voice.stop()

    async def destroy(self) -> None:
        self._closing = True
        self.queue.clear()
        self._runner.cancel()
        if self.voice.is_connected():
            await self.voice.disconnect(force=True)

    # ---------------------------------------------------------------- ลูปหลัก

    async def _run(self) -> None:
        try:
            while True:
                self._advance.clear()
                track = await self._next_track()
                if track is None:
                    await self._notify(
                        f"ไม่มีเพลงในคิวเกิน {self.cfg.idle_timeout} วินาที ออกจากห้องเสียงแล้วครับ"
                    )
                    break

                if not self.voice.is_connected():
                    break

                try:
                    url = await self.ytdl.refresh_stream(track)
                except ExtractError as exc:
                    await self._notify(f"ข้าม **{track.title}** — {exc}")
                    continue

                self.current = track
                self._start(track, url)
                await self._announce(track)

                await self._advance.wait()

                self.history.appendleft(track)
                self._requeue(track)
                self.current = None
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("ลูปเล่นเพลงพัง")
        finally:
            if not self._closing:
                await self._cleanup()

    async def _next_track(self) -> Track | None:
        """รอเพลงถัดไป คืน None ถ้าไม่มีอะไรมาเลยจนหมดเวลา"""
        while True:
            if self.queue:
                return self.queue.popleft()
            self._has_work.clear()
            try:
                await asyncio.wait_for(self._has_work.wait(), timeout=self.cfg.idle_timeout)
            except asyncio.TimeoutError:
                return None

    def _requeue(self, track: Track) -> None:
        if self.loop_mode is LoopMode.TRACK:
            self.queue.appendleft(track)
            self._has_work.set()
        elif self.loop_mode is LoopMode.QUEUE:
            self.queue.append(track)
            self._has_work.set()

    def _start(self, track: Track, url: str, *, seek: float = 0.0) -> None:
        source = build_source(
            url,
            ffmpeg_path=self.cfg.ffmpeg_path,
            volume=self._volume,
            seek=seek,
            normalize=self.cfg.normalize,
        )
        self.voice.play(source, after=self._on_finished)
        # ต้องจูนหลัง play() เพราะ discord.py เพิ่งสร้าง encoder ตอนนั้น
        self.bitrate = tune_encoder(self.voice, bitrate_override=self.cfg.opus_bitrate)

        self._seek_offset = seek
        self._started_at = self._loop.time()
        self._paused_at = None

    def _on_finished(self, error: Exception | None) -> None:
        """callback นี้ถูกเรียกจาก thread ของ ffmpeg ไม่ใช่ event loop"""
        if error:
            log.error("เล่นเพลงผิดพลาด: %s", error)
        self._loop.call_soon_threadsafe(self._advance.set)

    # ---------------------------------------------------------------- แจ้งเตือน

    async def _announce(self, track: Track) -> None:
        embed = discord.Embed(
            title=track.title,
            url=track.webpage_url or None,
            description=f"ความยาว `{track.duration_text}` • ขอโดย {track.requester_name}",
            colour=discord.Colour.from_str("#1db954"),
        )
        embed.set_author(name="กำลังเล่น")
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        footer = f"Opus {self.bitrate} kbps"
        if self.loop_mode is not LoopMode.OFF:
            footer += f" • ลูป: {self.loop_mode.label}"
        embed.set_footer(text=footer)
        await self._notify(embed=embed)

    async def _notify(self, content: str | None = None, *, embed: discord.Embed | None = None):
        try:
            await self.text_channel.send(content, embed=embed)
        except discord.HTTPException:
            log.debug("ส่งข้อความไปห้อง %s ไม่ได้", self.text_channel)

    async def _cleanup(self) -> None:
        self.current = None
        self.queue.clear()
        if self.voice.is_connected():
            await self.voice.disconnect(force=True)
