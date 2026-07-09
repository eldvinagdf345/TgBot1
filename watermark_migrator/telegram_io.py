import os

from telethon import TelegramClient
from telethon.tl.custom.message import Message
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo

from .config import Config


def make_client(cfg: Config) -> TelegramClient:
    return TelegramClient(cfg.session_name, cfg.api_id, cfg.api_hash)


async def iter_source_messages(client: TelegramClient, source_channel: str):
    """Yield every real message (any type) from oldest to newest, so order is
    preserved in the target channel. Service messages (pins, member joins,
    channel migrations, etc.) and truly empty messages are skipped."""
    entity = await client.get_entity(source_channel)
    async for msg in client.iter_messages(entity, reverse=True):
        if msg.action is not None:
            continue
        if msg.media is None and not (msg.message and msg.message.strip()):
            continue
        yield msg


async def download_media(client: TelegramClient, msg: Message, dest_path: str) -> str:
    """Download to an exact file path (used for videos, where we control the
    container/extension ourselves)."""
    return await client.download_media(msg, file=dest_path)


async def download_media_auto(client: TelegramClient, msg: Message, dest_dir: str) -> str:
    """Download into a directory, letting Telethon pick the correct filename
    and extension for whatever media type this message actually holds."""
    os.makedirs(dest_dir, exist_ok=True)
    return await client.download_media(msg, file=dest_dir + os.sep)


async def upload_message(
    client: TelegramClient,
    target_channel: str,
    media_path: str | None,
    caption: str,
    video_attrs: tuple[float, int, int] | None = None,
    progress_callback=None,
) -> None:
    """video_attrs, if given, is (duration_seconds, width, height) measured
    straight from the actual output file - passing it explicitly avoids
    Telegram guessing the wrong aspect ratio (which otherwise shows up as a
    stretched/squashed video, since Telethon can only auto-detect this with
    the optional `hachoir` package installed).

    progress_callback, if given, is called as callback(sent_bytes, total_bytes)
    while uploading - Telethon calls this itself as the transfer progresses."""
    entity = await client.get_entity(target_channel)
    if media_path:
        attributes = None
        if video_attrs is not None:
            duration, w, h = video_attrs
            attributes = [
                DocumentAttributeVideo(
                    duration=duration, w=w, h=h, supports_streaming=True
                ),
                DocumentAttributeFilename(file_name=os.path.basename(media_path)),
            ]
        await client.send_file(
            entity, media_path, caption=caption or None,
            supports_streaming=True, attributes=attributes,
            progress_callback=progress_callback,
        )
    elif caption and caption.strip():
        await client.send_message(entity, caption)
    # else: no media and nothing left of the text after sanitizing - nothing to send
