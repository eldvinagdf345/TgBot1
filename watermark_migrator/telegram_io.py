from telethon import TelegramClient
from telethon.tl.custom.message import Message

from .config import Config


def make_client(cfg: Config) -> TelegramClient:
    return TelegramClient(cfg.session_name, cfg.api_id, cfg.api_hash)


async def iter_source_videos(client: TelegramClient, source_channel: str):
    """Yield video messages from oldest to newest, so order is preserved in the target channel."""
    entity = await client.get_entity(source_channel)
    async for msg in client.iter_messages(entity, reverse=True):
        if msg.video is not None:
            yield msg


async def download_video(client: TelegramClient, msg: Message, dest_path: str) -> str:
    return await client.download_media(msg, file=dest_path)


async def upload_video(
    client: TelegramClient, target_channel: str, video_path: str, caption: str
) -> None:
    entity = await client.get_entity(target_channel)
    await client.send_file(
        entity, video_path, caption=caption, supports_streaming=True
    )
