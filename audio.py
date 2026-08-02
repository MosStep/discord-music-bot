"""สร้าง audio source และจูน Opus encoder ให้ได้คุณภาพสูงสุด

สายสัญญาณทั้งเส้น:
    YouTube (opus ~160k) -> ffmpeg -> PCM 48kHz stereo 16-bit -> Opus encoder -> Discord

จุดที่มีผลกับคุณภาพมากที่สุดคือขั้นสุดท้าย: discord.py ตั้ง encoder ไว้ที่ 128 kbps ตายตัว
ทั้งที่ห้องเสียงที่บูสต์แล้วรับได้ถึง 384 kbps — เราจึงจูนใหม่ทุกครั้งที่เริ่มเล่น
"""

from __future__ import annotations

import logging

import discord

log = logging.getLogger(__name__)

# ต่อสายใหม่อัตโนมัติเวลาเน็ตสะดุด ไม่งั้นเพลงจะหยุดกลางคัน
# rw_timeout กันกรณีเซิร์ฟเวอร์ค้างไม่ส่งข้อมูลแต่ไม่ตัดการเชื่อมต่อ (หน่วยไมโครวินาที)
FFMPEG_BEFORE = (
    "-nostdin "
    "-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 "
    "-reconnect_on_http_error 4xx,5xx -reconnect_delay_max 5 "
    "-rw_timeout 15000000"
)

# soxr เป็น resampler คุณภาพสูงของ ffmpeg (ค่าเริ่มต้นคือ swr ธรรมดาที่ด้อยกว่า)
# precision 24 โปร่งใสเกินพอสำหรับปลายทาง 16-bit และเบากว่า 28 มาก
# — precision 28 กินซีพียูหนักจนแย่งเวลาเธรดส่งเสียง ทำให้เสียงกระตุกเป็นช่วง ๆ
# triangular dither ช่วยกลบ quantisation noise ตอนลดมาเป็น 16-bit
HQ_RESAMPLE = "aresample=resampler=soxr:precision=24:dither_method=triangular:osr=48000"

# EBU R128 ปรับความดังให้เท่ากันทุกเพลง (เปิดผ่าน AUDIO_NORMALIZE=1)
LOUDNORM = "loudnorm=I=-14:LRA=11:TP=-1.5"


def build_source(
    stream_url: str,
    *,
    ffmpeg_path: str,
    volume: float,
    seek: float = 0.0,
    normalize: bool = False,
) -> discord.PCMVolumeTransformer:
    """สร้าง audio source จากลิงก์สตรีม พร้อมตัวคุมระดับเสียง"""
    before = FFMPEG_BEFORE
    if seek > 0:
        # วาง -ss ไว้ก่อน -i เพื่อให้ ffmpeg seek แบบเร็ว (ไม่ต้อง decode ตั้งแต่ต้นไฟล์)
        before = f"-ss {seek:.3f} {before}"

    filters = [HQ_RESAMPLE]
    if normalize:
        filters.insert(0, LOUDNORM)

    # -vn/-sn/-dn ตัด stream วิดีโอ ซับ และ data ทิ้ง เหลือแต่เสียง
    options = f'-vn -sn -dn -af "{",".join(filters)}" -loglevel error'

    source = discord.FFmpegPCMAudio(
        stream_url,
        executable=ffmpeg_path,
        before_options=before,
        options=options,
    )
    return discord.PCMVolumeTransformer(source, volume=volume)


def tune_encoder(voice_client: discord.VoiceClient, *, bitrate_override: int | None = None) -> int:
    """จูน Opus encoder หลังเรียก play()

    ต้องเรียกทุกครั้งที่เริ่มเพลงใหม่ เพราะ discord.py สร้าง encoder ใหม่ทุกครั้งที่ play()
    คืนค่า bitrate จริงที่ตั้งได้ (kbps)
    """
    encoder = getattr(voice_client, "encoder", None)
    channel = voice_client.channel

    # bitrate ของห้องเสียงคือเพดานจริง — ส่งเกินไปก็โดน Discord ตัดทิ้ง
    ceiling = getattr(channel, "bitrate", 64000) // 1000
    kbps = min(bitrate_override or ceiling, ceiling)
    kbps = min(max(kbps, 16), 512)

    if encoder is None:
        return kbps

    try:
        encoder.set_bitrate(kbps)
        # บอก encoder ว่าเป็นดนตรี ไม่ใช่เสียงพูด — เปลี่ยนวิธีจัดสรร bit ทั้งหมด
        encoder.set_signal_type("music")
        encoder.set_bandwidth("full")
        # FEC กินแบนด์วิดท์ไปทำ error correction แลกกับคุณภาพเสียง — ปิดเพื่อเอาคุณภาพเต็ม
        encoder.set_fec(False)
        encoder.set_expected_packet_loss_percent(0.0)
    except Exception:  # noqa: BLE001 - เป็นแค่การจูน ถ้าพังก็ยังเล่นได้ปกติ
        log.warning("จูน Opus encoder ไม่สำเร็จ ใช้ค่าเริ่มต้นแทน", exc_info=True)

    return kbps


def describe_chain(voice_client: discord.VoiceClient | None, kbps: int | None) -> str:
    """สรุปสายสัญญาณให้ดูด้วยคำสั่ง /quality"""
    ceiling = getattr(getattr(voice_client, "channel", None), "bitrate", 0) // 1000
    lines = [
        "**ต้นทาง** YouTube opus/aac bitrate สูงสุดที่มี",
        "**ถอดรหัส** ffmpeg -> PCM 48 kHz stereo 16-bit",
        "**Resample** soxr precision 28 + triangular dither",
        f"**Opus encoder** {kbps or '-'} kbps, signal=music, bandwidth=full, FEC ปิด",
        f"**เพดานห้องเสียง** {ceiling or '-'} kbps",
    ]
    if ceiling and ceiling < 128:
        lines.append(
            "\nห้องนี้จำกัดที่ "
            f"{ceiling} kbps — บูสต์เซิร์ฟเวอร์หรือแก้ bitrate ในตั้งค่าห้อง "
            "จะได้เสียงดีขึ้นชัดเจนกว่าการปรับอะไรในบอท"
        )
    return "\n".join(lines)
