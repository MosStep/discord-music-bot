"""จุดเริ่มต้นของบอท — รันด้วย `python bot.py`"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import discord
from discord.ext import commands

from config import Config

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
log = logging.getLogger("bot")


class MusicBot(commands.Bot):
    def __init__(self, cfg: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # ต้องเปิด MESSAGE CONTENT INTENT ในหน้า Developer Portal ด้วย
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(cfg.prefix),
            intents=intents,
            help_command=commands.DefaultHelpCommand(no_category="คำสั่ง"),
            activity=discord.Activity(type=discord.ActivityType.listening, name=f"{cfg.prefix}play"),
        )
        self.cfg = cfg

    async def setup_hook(self) -> None:
        # discord.py โหลด libopus แบบ lazy — บังคับโหลดตอนนี้เลยจะได้รู้ปัญหาก่อนมีคนสั่งเพลง
        if not discord.opus.is_loaded():
            try:
                discord.opus._load_default()
            except Exception:  # noqa: BLE001
                pass
        if discord.opus.is_loaded():
            log.info("โหลด libopus สำเร็จ")
        else:
            log.warning("โหลด libopus ไม่ได้ — เล่นเพลงจะไม่มีเสียง ลองติดตั้ง PyNaCl ใหม่")

        await self.load_extension("cogs.music")

        if self.cfg.dev_guild_id:
            guild = discord.Object(id=self.cfg.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("sync slash command %d คำสั่ง เข้าเซิร์ฟเวอร์ %s", len(synced), self.cfg.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("sync slash command %d คำสั่งแบบ global (อาจใช้เวลาถึง 1 ชม.)", len(synced))

    async def on_ready(self) -> None:
        log.info("ล็อกอินเป็น %s (id: %s) — อยู่ใน %d เซิร์ฟเวอร์", self.user, self.user.id, len(self.guilds))

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"⚠️ ใส่ค่า `{error.param.name}` ด้วยครับ")
            return
        # ที่เหลือปล่อยให้ cog จัดการเอง
        if ctx.cog is None:
            log.exception("คำสั่งผิดพลาด", exc_info=error)


async def main() -> None:
    cfg = Config.load()
    async with MusicBot(cfg) as bot:
        await bot.start(cfg.token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
