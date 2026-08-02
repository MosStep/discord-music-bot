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

ACCESS_HELP = (
    "sync คำสั่งเข้าเซิร์ฟเวอร์ %s ไม่ได้ (403 Missing Access)\n"
    "  แปลว่าบอทยังไม่ได้อยู่ในเซิร์ฟเวอร์นั้น หรือเชิญมาโดยไม่มี scope applications.commands\n"
    "  เชิญใหม่ด้วยลิงก์นี้แล้วเลือกเซิร์ฟเวอร์เดิม (ทับของเดิมได้ ไม่ต้องเตะบอทออกก่อน):\n"
    "  https://discord.com/oauth2/authorize"
    "?client_id=%s&permissions=3230721&scope=bot%%20applications.commands\n"
    "  ตอนนี้จะ sync แบบ global ไปก่อน คำสั่งจะโผล่ช้าถึง 1 ชม."
)


class MusicBot(commands.Bot):
    def __init__(self, cfg: Config, *, message_content: bool = True) -> None:
        intents = discord.Intents.default()
        # ต้องเปิด MESSAGE CONTENT INTENT ในหน้า Developer Portal ด้วย
        # ถ้าเปิดไม่ได้ก็ยังใช้ slash command ได้ครบทุกคำสั่ง (ดูการ fallback ใน main)
        intents.message_content = message_content
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(cfg.prefix),
            intents=intents,
            help_command=commands.DefaultHelpCommand(no_category="คำสั่ง"),
            activity=discord.Activity(type=discord.ActivityType.listening, name=f"{cfg.prefix}pa"),
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
            try:
                synced = await self.tree.sync(guild=guild)
                log.info(
                    "sync slash command %d คำสั่ง เข้าเซิร์ฟเวอร์ %s", len(synced), self.cfg.dev_guild_id
                )
                # ล้างคำสั่ง global ที่ค้างจากการรันครั้งก่อน
                # ไม่งั้นเมนูจะมีตัวซ้ำที่กดแล้วขึ้น "แอปพลิเคชันไม่ตอบสนอง"
                self.tree.clear_commands(guild=None)
                removed = await self.tree.sync()
                log.info("ล้างคำสั่ง global ที่ค้างแล้ว (เหลือ %d)", len(removed))
                return
            except discord.Forbidden:
                # บอทไม่ได้อยู่ในเซิร์ฟเวอร์นั้น หรือเชิญมาโดยไม่มี scope applications.commands
                log.warning(ACCESS_HELP, self.cfg.dev_guild_id, self.application_id)

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


INTENT_HELP = (
    "ยังไม่ได้เปิด MESSAGE CONTENT INTENT ในหน้า Developer Portal\n"
    "  แก้ที่ https://discord.com/developers/applications -> เลือกแอป -> แท็บ Bot\n"
    "  -> Privileged Gateway Intents -> เปิด MESSAGE CONTENT INTENT -> Save Changes\n"
    "  ตอนนี้จะรันต่อแบบใช้ได้เฉพาะ slash command (คำสั่งแบบพิมพ์ prefix จะไม่ทำงาน)"
)


async def _start(cfg: Config, *, message_content: bool) -> bool:
    """สตาร์ทบอท คืน True ถ้าล้มเพราะ intent เพื่อให้ลองใหม่แบบไม่ใช้ message_content"""
    async with MusicBot(cfg, message_content=message_content) as bot:
        try:
            await bot.start(cfg.token)
        except discord.errors.PrivilegedIntentsRequired:
            if message_content:
                return True
            raise
        except discord.errors.LoginFailure:
            raise SystemExit(
                "token ไม่ถูกต้อง — ตรวจค่า DISCORD_TOKEN ใน .env อีกครั้ง "
                "(ถ้าเพิ่งกด Reset Token ต้องใช้ค่าใหม่)"
            ) from None
    return False


async def main() -> None:
    cfg = Config.load()
    if await _start(cfg, message_content=True):
        log.warning(INTENT_HELP)
        await _start(cfg, message_content=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
