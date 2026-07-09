"""
One-off helper: download a specific sticker from a Telegram sticker pack and
save it as a PNG you can point OVERLAY_IMAGE at.

Usage:
    python3 -m watermark_migrator.fetch_sticker https://t.me/addstickers/PACK_NAME --index 0
"""
import argparse
import asyncio
import os
import re

from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import InputStickerSetShortName

from .config import load_config
from .ffmpeg_utils import _run
from .telegram_io import make_client


def parse_short_name(link_or_name: str) -> str:
    m = re.search(r"addstickers/([^/?]+)", link_or_name)
    return m.group(1) if m else link_or_name


def _is_gzip(path: str) -> bool:
    with open(path, "rb") as f:
        return f.read(2) == b"\x1f\x8b"


async def fetch_sticker(link_or_name: str, index: int, out_path: str) -> None:
    cfg = load_config()
    client = make_client(cfg)
    await client.start()

    short_name = parse_short_name(link_or_name)
    result = await client(
        GetStickerSetRequest(
            stickerset=InputStickerSetShortName(short_name=short_name), hash=0
        )
    )
    documents = result.documents
    print(f"Pack '{short_name}' has {len(documents)} stickers.")
    if not documents:
        raise RuntimeError("Sticker pack has no stickers.")
    if index >= len(documents):
        raise RuntimeError(f"Index {index} out of range - pack only has {len(documents)} stickers.")

    doc = documents[index]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    raw_path = out_path + ".raw"
    await client.download_media(doc, file=raw_path)
    await client.disconnect()

    if raw_path.lower().endswith(".tgs") or _is_gzip(raw_path):
        os.remove(raw_path)
        raise RuntimeError(
            "That sticker is animated (.tgs) - pick a different (static) "
            "sticker index from the same pack."
        )

    code, _, err = await _run([cfg.ffmpeg_bin, "-y", "-i", raw_path, out_path])
    os.remove(raw_path)
    if code != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {err.decode(errors='ignore')}")

    print(f"Saved sticker as {out_path}")
    print(f"Now set OVERLAY_IMAGE={out_path} in your .env")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("link_or_name", help="Sticker pack link or short name")
    parser.add_argument("--index", type=int, default=0, help="Which sticker in the pack (0-based)")
    parser.add_argument(
        "--out", default="watermark_migrator/assets/sticker_mask.png",
        help="Where to save the converted PNG",
    )
    args = parser.parse_args()
    asyncio.run(fetch_sticker(args.link_or_name, args.index, args.out))
