"""คำสั่งเล่นเพลงทั้งหมด — ใช้ได้ทั้งแบบ slash และแบบพิมพ์ prefix"""

from __future__ import annotations

import functools
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route

from audio import describe_chain
from player import GuildPlayer, LoopMode
from ytdl import ExtractError, Track, YTDLClient

log = logging.getLogger(__name__)

GREEN = discord.Colour.from_str("#1db954")
RED = discord.Colour.from_str("#ed4245")
QUEUE_PAGE_SIZE = 10
URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# id ของ activity "Watch Together" ที่ Discord ทำไว้ให้ดู YouTube ร่วมกัน
YOUTUBE_TOGETHER_ID = "880218394199220334"

# ไม่เลือกภายในกี่วินาทีแล้วให้เล่นอันดับแรกเอง
PICK_TIMEOUT = 3.0


class NotInVoice(commands.CheckFailure):
    pass


def fmt_duration(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_timestamp(raw: str) -> float | None:
    """รับได้ทั้ง '90', '1:30' และ '1:02:03'"""
    raw = raw.strip()
    if not re.fullmatch(r"(\d+:)?(\d+:)?\d+(\.\d+)?", raw):
        return None
    parts = [float(p) for p in raw.split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cfg = bot.cfg
        self.ytdl = YTDLClient(bot.cfg.cookie_file)
        self.players: dict[int, GuildPlayer] = {}

    async def cog_unload(self) -> None:
        for player in list(self.players.values()):
            await player.destroy()
        self.players.clear()

    # ---------------------------------------------------------------- helper

    def get_player(self, guild_id: int) -> GuildPlayer | None:
        player = self.players.get(guild_id)
        if player and not player.voice.is_connected():
            self.players.pop(guild_id, None)
            return None
        return player

    async def ensure_player(self, ctx: commands.Context) -> GuildPlayer:
        """เข้าห้องเสียงของคนสั่ง (หรือย้ายห้องถ้าจำเป็น) แล้วคืน player"""
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            raise NotInVoice("เข้าห้องเสียงก่อนสั่งเพลงนะครับ")

        channel = ctx.author.voice.channel
        perms = channel.permissions_for(ctx.me)
        if not (perms.connect and perms.speak):
            raise NotInVoice(f"ผมไม่มีสิทธิ์เข้าหรือพูดในห้อง **{channel.name}**")

        player = self.get_player(ctx.guild.id)
        if player:
            if player.voice.channel != channel and not player.is_playing:
                await player.voice.move_to(channel)
            player.text_channel = ctx.channel
            return player

        voice = await channel.connect(self_deaf=True, timeout=30.0)
        player = GuildPlayer(self.cfg, self.ytdl, voice, ctx.channel)
        self.players[ctx.guild.id] = player
        return player

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandInvokeError):
            error = error.original
        if isinstance(error, (NotInVoice, commands.CheckFailure, ExtractError)):
            await ctx.reply(f"⚠️ {error}", ephemeral=True)
            return
        log.exception("คำสั่ง %s พัง", ctx.command, exc_info=error)
        await ctx.reply(f"❌ เกิดข้อผิดพลาด: `{error}`", ephemeral=True)

    def stamp(self, tracks: list[Track], user: discord.abc.User) -> None:
        for track in tracks:
            track.requester_id = user.id
            track.requester_name = user.display_name

    # ---------------------------------------------------------------- เล่นเพลง

    @commands.hybrid_command(name="pa", aliases=["p"], description="เล่นเพลงจาก YouTube")
    @app_commands.describe(query="ชื่อเพลง หรือลิงก์ YouTube (ใส่ลิงก์ playlist ได้ทั้งชุด)")
    @commands.guild_only()
    async def pa(self, ctx: commands.Context, *, query: str) -> None:
        await self._enqueue(ctx, query, front=False)

    # ลงทะเบียน /play เป็นคำสั่งจริงอีกตัว ไม่ใช่แค่ alias
    # เพราะ alias ใช้ได้เฉพาะคำสั่งแบบพิมพ์ ส่วนเมนู slash จะเห็นแค่ชื่อหลัก
    @commands.hybrid_command(name="play", description="เล่นเพลงจาก YouTube (เหมือน /pa)")
    @app_commands.describe(query="ชื่อเพลง หรือลิงก์ YouTube (ใส่ลิงก์ playlist ได้ทั้งชุด)")
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        await self._enqueue(ctx, query, front=False)

    @commands.hybrid_command(name="pn", aliases=["playnext"], description="แทรกเพลงเป็นคิวถัดไป")
    @app_commands.describe(query="ชื่อเพลง หรือลิงก์ YouTube")
    @commands.guild_only()
    async def playnext(self, ctx: commands.Context, *, query: str) -> None:
        await self._enqueue(ctx, query, front=True)

    async def _enqueue(self, ctx: commands.Context, query: str, *, front: bool) -> None:
        # พิมพ์ชื่อเพลงแล้วให้เลือกเอง เพราะเพลงชื่อซ้ำกันเยอะ ระบบเดาเองมักได้ไม่ตรง
        # ใส่ลิงก์มาถือว่ารู้อยู่แล้วว่าจะเอาอันไหน เล่นทันทีไม่ต้องถาม
        if self.cfg.play_picker and not URL_RE.match(query.strip()):
            await self._offer_choices(ctx, query, front=front)
            return

        async with ctx.typing():
            player = await self.ensure_player(ctx)
            tracks = await self.ytdl.resolve(query)
            self.stamp(tracks, ctx.author)
            player.add(tracks, front=front)

        await ctx.reply(embed=self._added_embed(player, tracks, front=front))

    def _added_embed(
        self, player: GuildPlayer, tracks: list[Track], *, front: bool
    ) -> discord.Embed:
        if len(tracks) > 1:
            total = fmt_duration(sum(t.duration or 0 for t in tracks))
            return discord.Embed(
                description=f"เพิ่ม **{len(tracks)}** เพลงเข้าคิวแล้ว • รวม `{total}`",
                colour=GREEN,
            )

        track = tracks[0]
        embed = discord.Embed(
            title=track.title,
            url=track.webpage_url or None,
            description=f"ความยาว `{track.duration_text}`",
            colour=GREEN,
        )
        embed.set_author(name="เพิ่มเข้าคิวแล้ว")
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        if player.current:
            embed.set_footer(text=f"คิวที่ {1 if front else len(player.queue)}")
        return embed

    @commands.hybrid_command(name="search", description="ค้นหา 5 อันดับแรกแล้วเลือกเอง")
    @app_commands.describe(query="คำค้น")
    @commands.guild_only()
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        await self._offer_choices(ctx, query, front=False)

    async def _offer_choices(self, ctx: commands.Context, query: str, *, front: bool) -> None:
        """แสดงผลค้นหา 5 อันดับให้คนที่สั่งเลือกเอง"""
        async with ctx.typing():
            results = await self.ytdl.search(query, limit=5)

        if not results:
            await ctx.reply("⚠️ ไม่พบผลลัพธ์")
            return

        # เจอผลเดียวก็ไม่ต้องถามให้เสียเวลา
        if len(results) == 1:
            await self._add_now(ctx, results[0].webpage_url, front=front)
            return

        view = SearchView(self, ctx, results, front=front)
        listing = "\n".join(
            f"**{i}.** [{t.title}]({t.webpage_url}) `{t.duration_text}`"
            + (f" — {t.uploader}" if t.uploader else "")
            for i, t in enumerate(results, start=1)
        )
        embed = discord.Embed(title=f"ผลการค้นหา: {query}", description=listing, colour=GREEN)
        embed.set_footer(
            text=f"กดปุ่มเลข • ไม่กดใน {PICK_TIMEOUT:g} วินาที จะเล่นอันดับ 1 (ปุ่มเขียว) ให้เอง"
        )
        view.message = await ctx.reply(embed=embed, view=view)

    async def _add_now(self, ctx: commands.Context, query: str, *, front: bool) -> None:
        """เพิ่มเข้าคิวทันทีโดยไม่ถาม (ใช้ตอนได้ลิงก์ที่แน่ชัดแล้ว)"""
        async with ctx.typing():
            player = await self.ensure_player(ctx)
            tracks = await self.ytdl.resolve(query, allow_playlist=False)
            self.stamp(tracks, ctx.author)
            player.add(tracks, front=front)
        await ctx.reply(embed=self._added_embed(player, tracks, front=front))

    # ---------------------------------------------------------------- ควบคุม

    @commands.hybrid_command(name="skip", aliases=["s"], description="ข้ามเพลงปัจจุบัน")
    @app_commands.describe(amount="ข้ามกี่เพลง (ค่าเริ่มต้น 1)")
    @commands.guild_only()
    async def skip(self, ctx: commands.Context, amount: int = 1) -> None:
        player = self.get_player(ctx.guild.id)
        if not player or not player.current:
            await ctx.reply("⚠️ ตอนนี้ไม่มีเพลงเล่นอยู่")
            return

        title = player.current.title
        # เพลงแรกข้ามด้วย stop() ที่เหลือดึงออกจากคิวตรง ๆ
        for _ in range(max(0, amount - 1)):
            if player.queue:
                player.queue.popleft()
        player.skip()
        await ctx.reply(f"⏭️ ข้าม **{title}** แล้ว")

    @commands.hybrid_command(name="pause", description="หยุดชั่วคราว")
    @commands.guild_only()
    async def pause(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if player and player.pause():
            await ctx.reply("⏸️ หยุดชั่วคราว")
        else:
            await ctx.reply("⚠️ ไม่มีเพลงที่กำลังเล่นอยู่")

    @commands.hybrid_command(name="resume", aliases=["r"], description="เล่นต่อ")
    @commands.guild_only()
    async def resume(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if player and player.resume():
            await ctx.reply("▶️ เล่นต่อ")
        else:
            await ctx.reply("⚠️ ไม่มีเพลงที่หยุดค้างไว้")

    @commands.hybrid_command(name="seek", description="กระโดดไปเวลาที่ต้องการ")
    @app_commands.describe(position="เช่น 90, 1:30 หรือ 1:02:03")
    @commands.guild_only()
    async def seek(self, ctx: commands.Context, position: str) -> None:
        player = self.get_player(ctx.guild.id)
        if not player or not player.current:
            await ctx.reply("⚠️ ตอนนี้ไม่มีเพลงเล่นอยู่")
            return

        seconds = parse_timestamp(position)
        if seconds is None:
            await ctx.reply("⚠️ รูปแบบเวลาไม่ถูกต้อง ลอง `90`, `1:30` หรือ `1:02:03`")
            return

        async with ctx.typing():
            ok = await player.seek(seconds)
        await ctx.reply(
            f"⏩ ไปที่ `{fmt_duration(int(seconds))}`" if ok else "⚠️ เพลงนี้กระโดดเวลาไม่ได้"
        )

    @commands.hybrid_command(name="stop", description="หยุดเล่นและล้างคิว")
    @commands.guild_only()
    async def stop(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if not player:
            await ctx.reply("⚠️ บอทไม่ได้เล่นอะไรอยู่")
            return
        player.stop()
        await ctx.reply("⏹️ หยุดเล่นและล้างคิวแล้ว")

    @commands.hybrid_command(name="leave", aliases=["dc"], description="ออกจากห้องเสียง")
    @commands.guild_only()
    async def leave(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if not player:
            await ctx.reply("⚠️ บอทไม่ได้อยู่ในห้องเสียง")
            return
        await player.destroy()
        self.players.pop(ctx.guild.id, None)
        await ctx.reply("👋 ออกจากห้องเสียงแล้ว")

    @commands.hybrid_command(name="join", description="ให้บอทเข้าห้องเสียง")
    @commands.guild_only()
    async def join(self, ctx: commands.Context) -> None:
        player = await self.ensure_player(ctx)
        await ctx.reply(f"🔊 เข้าห้อง **{player.voice.channel.name}** แล้ว")

    # ---------------------------------------------------------------- คิว

    @commands.hybrid_command(name="queue", aliases=["q"], description="ดูคิวเพลง")
    @app_commands.describe(page="หน้าที่ต้องการดู")
    @commands.guild_only()
    async def queue(self, ctx: commands.Context, page: int = 1) -> None:
        player = self.get_player(ctx.guild.id)
        if not player or (not player.queue and not player.current):
            await ctx.reply("📭 คิวว่างเปล่า")
            return

        embed = discord.Embed(title="คิวเพลง", colour=GREEN)
        if player.current:
            embed.add_field(
                name="กำลังเล่น",
                value=(
                    f"{player.current.markdown}\n"
                    f"{player.progress_bar()} "
                    f"`{fmt_duration(int(player.position))} / {player.current.duration_text}`"
                ),
                inline=False,
            )

        pages = max(1, -(-len(player.queue) // QUEUE_PAGE_SIZE))
        page = min(max(page, 1), pages)
        start = (page - 1) * QUEUE_PAGE_SIZE
        chunk = list(player.queue)[start : start + QUEUE_PAGE_SIZE]

        if chunk:
            lines = [
                f"`{start + i}.` {t.markdown} `{t.duration_text}` — {t.requester_name}"
                for i, t in enumerate(chunk, start=1)
            ]
            embed.add_field(name="ถัดไป", value="\n".join(lines), inline=False)

        embed.set_footer(
            text=(
                f"หน้า {page}/{pages} • {len(player.queue)} เพลงในคิว • "
                f"รวม {fmt_duration(player.total_duration)} • ลูป: {player.loop_mode.label}"
            )
        )
        await ctx.reply(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="ดูเพลงที่กำลังเล่น")
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if not player or not player.current:
            await ctx.reply("⚠️ ตอนนี้ไม่มีเพลงเล่นอยู่")
            return

        track = player.current
        embed = discord.Embed(title=track.title, url=track.webpage_url or None, colour=GREEN)
        embed.set_author(name="กำลังเล่น")
        embed.description = (
            f"{player.progress_bar()}\n"
            f"`{fmt_duration(int(player.position))} / {track.duration_text}`\n"
            f"ขอโดย {track.requester_name}"
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(
            text=f"เสียง {int(player.volume * 100)}% • Opus {player.bitrate} kbps"
        )
        await ctx.reply(embed=embed)

    @commands.hybrid_command(name="shuffle", description="สลับคิวแบบสุ่ม")
    @commands.guild_only()
    async def shuffle(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if not player or len(player.queue) < 2:
            await ctx.reply("⚠️ ต้องมีเพลงในคิวอย่างน้อย 2 เพลง")
            return
        player.shuffle()
        await ctx.reply(f"🔀 สลับคิว {len(player.queue)} เพลงแล้ว")

    @commands.hybrid_command(name="clear", description="ล้างคิวแต่เล่นเพลงปัจจุบันต่อ")
    @commands.guild_only()
    async def clear(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        if not player or not player.queue:
            await ctx.reply("📭 คิวว่างอยู่แล้ว")
            return
        count = len(player.queue)
        player.clear()
        await ctx.reply(f"🗑️ ล้างคิว {count} เพลงแล้ว")

    @commands.hybrid_command(name="remove", description="ลบเพลงออกจากคิว")
    @app_commands.describe(index="ลำดับในคิว (ดูจาก /queue)")
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, index: int) -> None:
        player = self.get_player(ctx.guild.id)
        track = player.remove(index) if player else None
        if not track:
            await ctx.reply("⚠️ ไม่มีเพลงลำดับนั้นในคิว")
            return
        await ctx.reply(f"🗑️ ลบ **{track.title}** ออกจากคิวแล้ว")

    @commands.hybrid_command(name="move", description="ย้ายลำดับเพลงในคิว")
    @app_commands.describe(source="ลำดับเดิม", destination="ลำดับใหม่")
    @commands.guild_only()
    async def move(self, ctx: commands.Context, source: int, destination: int) -> None:
        player = self.get_player(ctx.guild.id)
        track = player.move(source, destination) if player else None
        if not track:
            await ctx.reply("⚠️ ลำดับไม่ถูกต้อง")
            return
        await ctx.reply(f"↕️ ย้าย **{track.title}** ไปคิวที่ {destination} แล้ว")

    @commands.hybrid_command(name="loop", description="ตั้งโหมดเล่นซ้ำ")
    @app_commands.describe(mode="off = ปิด, track = วนเพลงเดียว, queue = วนทั้งคิว")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="ปิด", value="off"),
            app_commands.Choice(name="วนเพลงเดียว", value="track"),
            app_commands.Choice(name="วนทั้งคิว", value="queue"),
        ]
    )
    @commands.guild_only()
    async def loop(self, ctx: commands.Context, mode: str) -> None:
        player = self.get_player(ctx.guild.id)
        if not player:
            await ctx.reply("⚠️ บอทไม่ได้อยู่ในห้องเสียง")
            return
        try:
            player.loop_mode = LoopMode(mode.lower())
        except ValueError:
            await ctx.reply("⚠️ เลือกได้แค่ `off`, `track` หรือ `queue`")
            return
        await ctx.reply(f"🔁 โหมดเล่นซ้ำ: **{player.loop_mode.label}**")

    # ---------------------------------------------------------------- วิดีโอ

    @commands.hybrid_command(
        name="v", aliases=["video", "watch"], description="เปิด Watch Together ดูวิดีโอพร้อมกัน"
    )
    @app_commands.describe(query="ชื่อหรือลิงก์วิดีโอที่จะดู (ไม่ใส่ก็ได้)")
    @commands.guild_only()
    async def video(self, ctx: commands.Context, *, query: str | None = None) -> None:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            await ctx.reply("⚠️ เข้าห้องเสียงก่อนนะครับ Watch Together เปิดในห้องเสียงเท่านั้น")
            return

        channel = ctx.author.voice.channel
        if not channel.permissions_for(ctx.me).create_instant_invite:
            await ctx.reply(
                f"⚠️ ผมไม่มีสิทธิ์ **Create Invite** ในห้อง **{channel.name}** "
                "ให้เพิ่มสิทธิ์นี้ให้บอทก่อน แล้วลองใหม่"
            )
            return

        async with ctx.typing():
            try:
                link = await self._create_activity(channel)
            except discord.HTTPException as exc:
                await ctx.reply(f"⚠️ เปิด Watch Together ไม่สำเร็จ: {exc.text or exc}")
                return

            found: Track | None = None
            if query:
                try:
                    found = (await self.ytdl.resolve(query, allow_playlist=False))[0]
                except ExtractError:
                    found = None

        embed = discord.Embed(
            title="เปิด Watch Together แล้ว",
            description=(
                f"กดลิงก์เพื่อเข้าดูพร้อมกันในห้อง **{channel.name}**\n{link}\n\n"
                "ทุกคนที่กดจะเห็นวิดีโอเดียวกัน เล่น/หยุด/เลื่อนเวลาตรงกันหมด"
            ),
            colour=GREEN,
        )
        if found:
            # Watch Together เปิดวิดีโอที่ระบุล่วงหน้าไม่ได้ ต้องวางลิงก์ในตัว activity เอง
            embed.add_field(
                name="วิดีโอที่คุณหา — วางลิงก์นี้ในช่องค้นหาของ Watch Together",
                value=f"{found.markdown}\n`{found.webpage_url}`",
                inline=False,
            )
        embed.set_footer(text="ลิงก์หมดอายุใน 24 ชั่วโมง")
        await ctx.reply(embed=embed)

    async def _create_activity(self, channel: discord.VoiceChannel) -> str:
        """สร้าง invite แบบ activity — discord.py ยังไม่มี API ตรง ต้องยิง route เอง"""
        payload = {
            "max_age": 86400,
            "max_uses": 0,
            "target_application_id": YOUTUBE_TOGETHER_ID,
            "target_type": 2,  # 2 = embedded application
            "temporary": False,
        }
        route = Route("POST", "/channels/{channel_id}/invites", channel_id=channel.id)
        data = await self.bot.http.request(route, json=payload)
        return f"https://discord.gg/{data['code']}"

    # ---------------------------------------------------------------- คุณภาพเสียง

    @commands.hybrid_command(name="volume", aliases=["vol"], description="ปรับระดับเสียง 0-200")
    @app_commands.describe(level="เว้นว่างเพื่อดูค่าปัจจุบัน")
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, level: int | None = None) -> None:
        player = self.get_player(ctx.guild.id)
        if not player:
            await ctx.reply("⚠️ บอทไม่ได้อยู่ในห้องเสียง")
            return

        if level is None:
            await ctx.reply(f"🔊 ระดับเสียงตอนนี้ **{int(player.volume * 100)}%**")
            return

        player.volume = min(max(level, 0), 200) / 100
        note = ""
        if level < 100:
            note = "\n-# หรี่เสียงในบอททำให้คุณภาพลดลงเล็กน้อย — ปรับที่ตัวผู้ใช้ใน Discord ดีกว่า"
        elif level > 100:
            note = "\n-# เกิน 100% อาจทำให้เสียงแตกได้"
        await ctx.reply(f"🔊 ตั้งระดับเสียงเป็น **{level}%**{note}")

    @commands.hybrid_command(name="quality", description="ดูสายสัญญาณเสียงที่ใช้อยู่")
    @commands.guild_only()
    async def quality(self, ctx: commands.Context) -> None:
        player = self.get_player(ctx.guild.id)
        embed = discord.Embed(
            title="คุณภาพเสียง",
            description=describe_chain(player.voice if player else None, player.bitrate if player else None),
            colour=GREEN,
        )
        if self.cfg.normalize:
            embed.set_footer(text="เปิด loudnorm อยู่ (AUDIO_NORMALIZE=1)")
        await ctx.reply(embed=embed)

    # ---------------------------------------------------------------- อัตโนมัติ

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.id == self.bot.user.id and after.channel is None:
            # โดนเตะหรือถูกตัดการเชื่อมต่อ
            player = self.players.pop(member.guild.id, None)
            if player:
                await player.destroy()
            return

        player = self.get_player(member.guild.id)
        if not player:
            return

        channel = player.voice.channel
        humans = [m for m in channel.members if not m.bot]
        if not humans and player.is_playing:
            player.pause()


class SearchView(discord.ui.View):
    """ปุ่มเลือกเพลงจากผลการค้นหา"""

    def __init__(
        self, cog: Music, ctx: commands.Context, results: list[Track], *, front: bool = False
    ) -> None:
        super().__init__(timeout=PICK_TIMEOUT)
        self.cog = cog
        self.ctx = ctx
        self.results = results
        self.front = front
        self.message: discord.Message | None = None
        self._handled = False  # กันไม่ให้เลือกเองกับเลือกอัตโนมัติชนกัน

        # ใช้ปุ่มแทน dropdown เพราะ dropdown ต้องกดสองที (เปิดเมนูแล้วค่อยเลือก)
        # ปุ่มกดทีเดียวจบ และทันกับเวลาเลือกอัตโนมัติ 3 วินาที
        for i in range(len(results)):
            button = discord.ui.Button(
                label=str(i + 1),
                # อันดับ 1 เป็นสีเขียวเพราะเป็นตัวที่จะถูกเลือกเองถ้าไม่กดอะไร
                style=discord.ButtonStyle.success if i == 0 else discord.ButtonStyle.primary,
                row=0,
            )
            button.callback = functools.partial(self._on_button, i)
            self.add_item(button)

        cancel = discord.ui.Button(label="ยกเลิก", style=discord.ButtonStyle.secondary, row=1)
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "⚠️ ปุ่มนี้ของคนที่สั่งค้นหาเท่านั้นครับ พิมพ์คำสั่งเองได้เลย", ephemeral=True
            )
            return False
        return True

    async def _on_button(self, index: int, interaction: discord.Interaction) -> None:
        if self._handled:
            await interaction.response.defer()
            return
        self._handled = True

        await interaction.response.defer()
        embed = await self._enqueue_choice(index, auto=False)

        self.clear_items()
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        if self._handled:
            await interaction.response.defer()
            return
        self._handled = True

        await interaction.response.defer()
        self.clear_items()
        await interaction.edit_original_response(
            embed=discord.Embed(description="ยกเลิกแล้ว", colour=RED), view=self
        )
        self.stop()

    async def on_timeout(self) -> None:
        """ครบเวลาแล้วยังไม่เลือก — เล่นอันดับแรกให้เลย"""
        if self._handled:
            return
        self._handled = True

        try:
            embed = await self._enqueue_choice(0, auto=True)
        except Exception as exc:  # noqa: BLE001 - ไม่มี context ให้ตอบ error ต้องกลืนไว้
            log.warning("เลือกเพลงอัตโนมัติไม่สำเร็จ: %s", exc)
            embed = discord.Embed(description=f"⚠️ เพิ่มเพลงอัตโนมัติไม่สำเร็จ: {exc}", colour=RED)

        if self.message:
            self.clear_items()
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
        self.stop()

    async def _enqueue_choice(self, index: int, *, auto: bool) -> discord.Embed:
        track = self.results[index]
        player = await self.cog.ensure_player(self.ctx)
        # ผลจากการค้นหาเป็นข้อมูลแบบย่อ ต้องดึงรายละเอียดเต็มก่อนเข้าคิว
        tracks = await self.cog.ytdl.resolve(track.webpage_url, allow_playlist=False)
        self.cog.stamp(tracks, self.ctx.author)
        player.add(tracks, front=self.front)

        embed = self.cog._added_embed(player, tracks, front=self.front)
        if auto:
            existing = embed.footer.text
            note = f"เลือกอัตโนมัติ (อันดับ 1) เพราะไม่ได้เลือกใน {PICK_TIMEOUT:g} วินาที"
            embed.set_footer(text=f"{existing} • {note}" if existing else note)
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
