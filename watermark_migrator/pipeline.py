import asyncio
import logging
import os
import shutil
from dataclasses import dataclass

from .config import Config, load_config
from .db import StateDB, open_db
from .detector import detect_watermark
from .ffmpeg_utils import clean_watermark, extract_sample_frames, get_duration, get_video_dimensions
from .telegram_io import (
    download_media,
    download_media_auto,
    iter_source_messages,
    make_client,
    upload_message,
)
from .text_rules import load_brand_terms, sanitize_text, sanitized_filename

logger = logging.getLogger("watermark_migrator")


@dataclass
class ProcessResult:
    skip: bool  # True => already handled in a previous run, or errored this run; nothing to publish
    media_path: str | None  # local file ready for upload, or None for a text-only message
    transcoded: bool  # True => media_path was re-encoded by us (force the .mp4 extension)
    is_video: bool = False  # True => media_path is a video; publisher should attach w/h/duration


async def _process_one(cfg: Config, client, db: StateDB, msg) -> ProcessResult:
    """Download, and for videos detect+clean if a watermark is found. Every
    other message type (photo, voice, document, plain text) passes through
    untouched."""
    message_id = msg.id

    if db.is_done(message_id):
        return ProcessResult(skip=True, media_path=None, transcoded=False)

    job_dir = os.path.join(cfg.work_dir, str(message_id))
    os.makedirs(job_dir, exist_ok=True)

    try:
        if msg.video is None:
            if msg.media is None:
                db.upsert_status(message_id, "uploading", watermark_found=0)
                return ProcessResult(skip=False, media_path=None, transcoded=False)

            db.upsert_status(message_id, "downloading")
            media_dir = os.path.join(job_dir, "media")
            downloaded = await download_media_auto(client, msg, media_dir)
            db.upsert_status(message_id, "uploading", watermark_found=0)
            return ProcessResult(skip=False, media_path=downloaded, transcoded=False)

        raw_path = os.path.join(job_dir, "raw.mp4")
        clean_path = os.path.join(job_dir, "clean.mp4")

        db.upsert_status(message_id, "downloading")
        await download_media(client, msg, raw_path)

        db.upsert_status(message_id, "detecting")
        frame_dir = os.path.join(job_dir, "frames")
        os.makedirs(frame_dir, exist_ok=True)
        frames = await extract_sample_frames(cfg, raw_path, frame_dir)
        bbox = detect_watermark(cfg, frames, cfg.watermark_templates_dir) if frames else None
        shutil.rmtree(frame_dir, ignore_errors=True)

        if bbox is None:
            db.upsert_status(message_id, "uploading", watermark_found=0)
            return ProcessResult(skip=False, media_path=raw_path, transcoded=False, is_video=True)

        x, y, w, h = bbox
        db.upsert_status(
            message_id, "cleaning", watermark_found=1,
            bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
        )
        await clean_watermark(cfg, raw_path, clean_path, bbox)
        os.remove(raw_path)
        db.upsert_status(message_id, "uploading")
        return ProcessResult(skip=False, media_path=clean_path, transcoded=True, is_video=True)

    except Exception as e:
        logger.exception(f"message {message_id} failed")
        db.upsert_status(message_id, "error", error=str(e))
        return ProcessResult(skip=True, media_path=None, transcoded=False)


async def run(cfg: Config | None = None) -> None:
    cfg = cfg or load_config()
    os.makedirs(cfg.work_dir, exist_ok=True)
    logging.basicConfig(level=logging.INFO)

    brand_terms = load_brand_terms(cfg.brand_terms_path)

    with open_db(cfg.db_path) as db:
        client = make_client(cfg)
        await client.start()

        logger.info("Fetching message list from source channel...")
        messages = [msg async for msg in iter_source_messages(client, cfg.source_channel)]
        logger.info(f"Found {len(messages)} messages to process")

        sem = asyncio.Semaphore(cfg.concurrency)
        results: dict[int, ProcessResult] = {}
        ready = asyncio.Condition()

        async def worker(pos: int, msg):
            async with sem:
                result = await _process_one(cfg, client, db, msg)
            async with ready:
                results[pos] = result
                ready.notify_all()

        async def publisher():
            next_pos = 0
            total = len(messages)
            while next_pos < total:
                async with ready:
                    await ready.wait_for(lambda: next_pos in results)
                    result = results.pop(next_pos)
                msg = messages[next_pos]
                if not result.skip:
                    try:
                        final_path = result.media_path
                        if final_path:
                            original_name = msg.file.name if msg.file else None
                            force_ext = "mp4" if result.transcoded else None
                            target_name = sanitized_filename(
                                original_name, brand_terms, msg.id, force_ext=force_ext
                            )
                            final_path = os.path.join(os.path.dirname(result.media_path), target_name)
                            if final_path != result.media_path:
                                os.rename(result.media_path, final_path)
                        video_attrs = None
                        if result.is_video and final_path:
                            duration = await get_duration(cfg, final_path)
                            width, height = await get_video_dimensions(cfg, final_path)
                            video_attrs = (duration, width, height)
                        caption = sanitize_text(msg.message, brand_terms)
                        await upload_message(
                            client, cfg.target_channel, final_path, caption, video_attrs
                        )
                        db.upsert_status(msg.id, "done")
                    except Exception as e:
                        logger.exception(f"upload failed for message {msg.id}")
                        db.upsert_status(msg.id, "error", error=str(e))
                    finally:
                        shutil.rmtree(os.path.join(cfg.work_dir, str(msg.id)), ignore_errors=True)
                next_pos += 1
                if next_pos % 25 == 0:
                    logger.info(f"Progress: {next_pos}/{total}")

        workers = [asyncio.create_task(worker(i, m)) for i, m in enumerate(messages)]
        pub_task = asyncio.create_task(publisher())
        await asyncio.gather(*workers)
        await pub_task

        logger.info("Migration complete.")
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
