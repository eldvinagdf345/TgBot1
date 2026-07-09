"""
Continuous mode: instead of one historical pass, stay connected and watch
SOURCE_CHANNEL for new messages as they arrive, processing (and forwarding)
each one the same way the batch pipeline does.

Usage:
    python3 -m watermark_migrator.live
"""
import asyncio
import logging
import os

from telethon import events

from .config import Config, load_config, prompt_for_channels
from .db import open_db
from .pipeline import _process_one, publish_one
from .telegram_io import make_client
from .text_rules import load_brand_terms

logger = logging.getLogger("watermark_migrator")


async def run_live(cfg: Config | None = None) -> None:
    cfg = cfg or load_config()
    prompt_for_channels(cfg)
    os.makedirs(cfg.work_dir, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    brand_terms = load_brand_terms(cfg.brand_terms_path)

    with open_db(cfg.db_path) as db:
        client = make_client(cfg)
        await client.start()
        source_entity = await client.get_entity(cfg.source_channel)
        sem = asyncio.Semaphore(cfg.concurrency)

        @client.on(events.NewMessage(chats=source_entity))
        async def handler(event):
            msg = event.message
            if msg.action is not None:
                return
            if msg.media is None and not (msg.message and msg.message.strip()):
                return

            async def _handle():
                async with sem:
                    result = await _process_one(cfg, client, db, msg)
                await publish_one(cfg, client, db, brand_terms, msg, result)

            asyncio.create_task(_handle())

        logger.info(f"Watching {cfg.source_channel} for new messages - leave this running.")
        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run_live())
