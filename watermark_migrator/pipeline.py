import asyncio
import logging
import os
import shutil

from .config import Config, load_config
from .db import StateDB, open_db
from .detector import detect_watermark
from .ffmpeg_utils import clean_watermark, extract_sample_frames
from .telegram_io import download_video, iter_source_videos, make_client, upload_video
from .text_rules import load_brand_terms, sanitize_text, sanitized_filename

logger = logging.getLogger("watermark_migrator")


async def _process_one(cfg: Config, client, db: StateDB, msg) -> str | None:
    """Download, detect, clean (if needed). Returns path to the file ready for upload,
    or None if this message was already fully handled in a previous run."""
    message_id = msg.id

    if db.is_done(message_id):
        return None

    job_dir = os.path.join(cfg.work_dir, str(message_id))
    os.makedirs(job_dir, exist_ok=True)
    raw_path = os.path.join(job_dir, "raw.mp4")
    clean_path = os.path.join(job_dir, "clean.mp4")

    try:
        db.upsert_status(message_id, "downloading")
        await download_video(client, msg, raw_path)

        db.upsert_status(message_id, "detecting")
        frame_dir = os.path.join(job_dir, "frames")
        os.makedirs(frame_dir, exist_ok=True)
        frames = await extract_sample_frames(cfg, raw_path, frame_dir)
        bbox = detect_watermark(cfg, frames, cfg.watermark_templates_dir) if frames else None
        shutil.rmtree(frame_dir, ignore_errors=True)

        if bbox is None:
            db.upsert_status(message_id, "uploading", watermark_found=0)
            return raw_path

        x, y, w, h = bbox
        db.upsert_status(
            message_id, "cleaning", watermark_found=1,
            bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h,
        )
        await clean_watermark(cfg, raw_path, clean_path, bbox)
        os.remove(raw_path)
        db.upsert_status(message_id, "uploading")
        return clean_path

    except Exception as e:
        logger.exception(f"message {message_id} failed")
        db.upsert_status(message_id, "error", error=str(e))
        return None


async def run(cfg: Config | None = None) -> None:
    cfg = cfg or load_config()
    os.makedirs(cfg.work_dir, exist_ok=True)
    logging.basicConfig(level=logging.INFO)

    brand_terms = load_brand_terms(cfg.brand_terms_path)

    with open_db(cfg.db_path) as db:
        client = make_client(cfg)
        await client.start()

        logger.info("Fetching video message list from source channel...")
        messages = [msg async for msg in iter_source_videos(client, cfg.source_channel)]
        logger.info(f"Found {len(messages)} videos to process")

        sem = asyncio.Semaphore(cfg.concurrency)
        results: dict[int, str | None] = {}
        ready = asyncio.Condition()

        async def worker(pos: int, msg):
            async with sem:
                path = await _process_one(cfg, client, db, msg)
            async with ready:
                results[pos] = path
                ready.notify_all()

        async def publisher():
            next_pos = 0
            total = len(messages)
            while next_pos < total:
                async with ready:
                    await ready.wait_for(lambda: next_pos in results)
                    path = results.pop(next_pos)
                msg = messages[next_pos]
                if path is not None:
                    try:
                        original_name = msg.file.name if msg.file else None
                        target_name = sanitized_filename(original_name, brand_terms, msg.id)
                        final_path = os.path.join(os.path.dirname(path), target_name)
                        if final_path != path:
                            os.rename(path, final_path)
                        caption = sanitize_text(msg.message, brand_terms)
                        await upload_video(
                            client, cfg.target_channel, final_path, caption
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
