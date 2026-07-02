import asyncio
import logging
from core import account_manager as am
from core import database as db

logger = logging.getLogger(__name__)

is_running = False
stop_flag = False
current_task = ""


async def sync_owner_channels(owner: dict, log_cb=None) -> list:
    """Fetch all channels owned by the account and save to DB."""
    if log_cb:
        log_cb("🔄 Синхронизирую каналы...")
    db.log_action("editor", "Синхронизация каналов", "running")
    try:
        channels = await am.get_owner_channels(owner)
        db.clear_channels()
        for ch in channels:
            db.upsert_channel(ch["tg_id"], ch["username"], ch["title"], ch["subscribers"])
        db.log_action("editor", f"Найдено каналов: {len(channels)}", "done")
        if log_cb:
            log_cb(f"✅ Найдено {len(channels)} каналов")
        return channels
    except Exception as e:
        db.log_action("editor", "Ошибка синхронизации", "error", str(e))
        raise e


async def get_posts_for_channel(owner: dict, channel: dict, limit: int = 30, log_cb=None) -> list:
    """Get posts from a specific channel."""
    if log_cb:
        log_cb(f"📋 Загружаю посты из {channel['title']}...")
    try:
        posts = await am.get_channel_posts(owner, channel["tg_id"], limit)
        if log_cb:
            log_cb(f"✅ Загружено {len(posts)} постов")
        return posts
    except Exception as e:
        if log_cb:
            log_cb(f"❌ Ошибка: {e}")
        raise e


async def copy_post_to_channel(owner: dict, source_url: str, channel: dict,
                                target_post_id: int, extra_text: str = "",
                                log_cb=None) -> bool:
    """
    Fetch content from source_url and edit target_post_id in channel.
    Appends extra_text below with one blank line separator.
    """
    global current_task
    current_task = f"Копирование поста в {channel['title']}"

    if log_cb:
        log_cb(f"📥 Загружаю пост из {source_url}...")
    db.log_action("editor", f"Копирование поста", "running", source_url)

    try:
        content = await am.fetch_post_content(owner, source_url)
        source_text = content["text"]
        media_bytes = content["media_bytes"]

        # Build new text: source text + blank line + extra text
        if extra_text.strip():
            new_text = f"{source_text}\n\n{extra_text.strip()}"
        else:
            new_text = source_text

        if log_cb:
            log_cb(f"✏️ Редактирую пост #{target_post_id}...")

        ok = await am.edit_channel_post(
            owner, channel["tg_id"], target_post_id, new_text, media_bytes
        )

        if ok:
            db.update_task_status_by_url(source_url, "done")
            db.log_action("editor", f"Пост #{target_post_id} отредактирован", "done")
            if log_cb:
                log_cb(f"✅ Пост #{target_post_id} успешно обновлён")
        return ok

    except Exception as e:
        db.log_action("editor", "Ошибка копирования", "error", str(e))
        if log_cb:
            log_cb(f"❌ Ошибка: {e}")
        return False


async def batch_copy(owner: dict, source_urls: list, channel: dict,
                     target_post_ids: list, extra_text: str = "",
                     log_cb=None, done_cb=None):
    """
    Copy multiple source posts to multiple target posts in order.
    source_urls[0] -> target_post_ids[0], etc.
    """
    global is_running, stop_flag
    is_running = True
    stop_flag = False

    total = min(len(source_urls), len(target_post_ids))
    done = 0
    errors = 0

    db.log_action("editor", f"Массовое копирование {total} постов", "running")

    for i in range(total):
        if stop_flag:
            break
        ok = await copy_post_to_channel(
            owner, source_urls[i], channel, target_post_ids[i],
            extra_text, log_cb
        )
        if ok:
            done += 1
        else:
            errors += 1
        await asyncio.sleep(1.5)  # небольшая пауза между редактированиями

    is_running = False
    summary = f"✅ Готово: {done}/{total}, ошибок: {errors}"
    db.log_action("editor", summary, "done")
    if log_cb:
        log_cb(summary)
    if done_cb:
        done_cb(done, errors)


def stop():
    global stop_flag
    stop_flag = True


def get_status():
    return {"is_running": is_running, "current_task": current_task}
