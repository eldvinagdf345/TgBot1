import sqlite3
import os
import tempfile
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import AuthKeyUnregisteredError, UserDeactivatedBanError, PhoneNumberBannedError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest

FALLBACK_API_ID = 2040
FALLBACK_API_HASH = "b18441a1ff607e10a989891a5462e627"


def extract_from_session_file(session_bytes: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as f:
        f.write(session_bytes)
        tmp_path = f.name
    try:
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        api_id, api_hash = None, None
        try:
            cursor.execute("SELECT * FROM sessions")
            col_names = [d[0] for d in cursor.description]
            for row in cursor.fetchall():
                rd = dict(zip(col_names, row))
                if rd.get("api_id"):
                    api_id = int(rd["api_id"])
                if rd.get("api_hash"):
                    api_hash = rd["api_hash"]
        except Exception:
            pass
        try:
            cursor.execute("SELECT key,value FROM kv WHERE key IN ('api_id','api_hash')")
            for key, value in cursor.fetchall():
                if key == "api_id":
                    api_id = int(value)
                elif key == "api_hash":
                    api_hash = value
        except Exception:
            pass
        conn.close()
        return {"api_id": api_id or FALLBACK_API_ID, "api_hash": api_hash or FALLBACK_API_HASH, "tmp_path": tmp_path}
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise e


async def import_session(session_bytes: bytes) -> dict:
    data = extract_from_session_file(session_bytes)
    tmp_path = data["tmp_path"]
    try:
        client = TelegramClient(tmp_path, data["api_id"], data["api_hash"])
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise Exception("Сессия не авторизована")
        session_string = StringSession.save(client.session)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        phone = me.phone or "unknown"
        await client.disconnect()
        return {
            "session_string": session_string,
            "api_id": data["api_id"],
            "api_hash": data["api_hash"],
            "name": name,
            "phone": phone,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def make_client(account: dict) -> TelegramClient:
    api_id = account.get("api_id") or FALLBACK_API_ID
    api_hash = account.get("api_hash") or FALLBACK_API_HASH
    return TelegramClient(StringSession(account["session_string"]), api_id, api_hash)


async def check_status(account: dict) -> str:
    try:
        client = make_client(account)
        await client.connect()
        try:
            me = await client.get_me()
            if me is None:
                return "banned"
            await client.get_dialogs(limit=1)
            return "active"
        except (AuthKeyUnregisteredError, UserDeactivatedBanError, PhoneNumberBannedError):
            return "banned"
        except Exception as e:
            return "spam" if "spam" in str(e).lower() else "banned"
        finally:
            await client.disconnect()
    except Exception:
        return "banned"


async def get_owner_channels(account: dict) -> list:
    """Get all channels where account is owner/admin."""
    channels = []
    try:
        client = make_client(account)
        await client.connect()
        try:
            async for dialog in client.iter_dialogs():
                if dialog.is_channel and dialog.entity.creator:
                    channels.append({
                        "tg_id": str(dialog.entity.id),
                        "username": dialog.entity.username or "",
                        "title": dialog.entity.title or "",
                        "subscribers": getattr(dialog.entity, "participants_count", 0) or 0,
                    })
        finally:
            await client.disconnect()
    except Exception as e:
        raise e
    return channels


async def get_channel_posts(account: dict, channel_id: str, limit: int = 50) -> list:
    """Get posts from a channel."""
    posts = []
    try:
        client = make_client(account)
        await client.connect()
        try:
            entity = await client.get_entity(int(channel_id))
            async for msg in client.iter_messages(entity, limit=limit):
                if msg.text or msg.media:
                    posts.append({
                        "id": msg.id,
                        "text": msg.text or "",
                        "date": str(msg.date),
                        "has_media": msg.media is not None,
                        "views": getattr(msg, "views", 0) or 0,
                    })
        finally:
            await client.disconnect()
    except Exception as e:
        raise e
    return posts


async def fetch_post_content(account: dict, post_url: str) -> dict:
    """Fetch text and media from a Telegram post URL."""
    # Parse URL like https://t.me/channel/123
    try:
        parts = post_url.strip("/").split("/")
        channel_username = parts[-2]
        post_id = int(parts[-1])
    except Exception:
        raise Exception(f"Неверный формат ссылки: {post_url}")

    client = make_client(account)
    await client.connect()
    try:
        entity = await client.get_entity(channel_username)
        msg = await client.get_messages(entity, ids=post_id)
        if not msg:
            raise Exception("Пост не найден")

        media_bytes = None
        media_type = None
        if msg.media:
            try:
                media_bytes = await client.download_media(msg.media, bytes)
                media_type = type(msg.media).__name__
            except Exception:
                pass

        return {
            "text": msg.text or "",
            "media_bytes": media_bytes,
            "media_type": media_type,
        }
    finally:
        await client.disconnect()


async def edit_channel_post(account: dict, channel_id: str, post_id: int,
                             new_text: str, media_bytes: bytes = None) -> bool:
    """Edit a post in owner's channel."""
    client = make_client(account)
    await client.connect()
    try:
        entity = await client.get_entity(int(channel_id))
        if media_bytes:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(media_bytes)
                tmp = f.name
            try:
                await client.edit_message(entity, post_id, new_text, file=tmp)
                os.unlink(tmp)
            except Exception:
                await client.edit_message(entity, post_id, new_text)
        else:
            await client.edit_message(entity, post_id, new_text)
        return True
    finally:
        await client.disconnect()


async def update_name(account: dict, first: str, last: str = "") -> bool:
    try:
        client = make_client(account)
        await client.connect()
        try:
            await client(UpdateProfileRequest(first_name=first, last_name=last))
            return True
        finally:
            await client.disconnect()
    except Exception:
        return False


async def update_bio(account: dict, bio: str) -> bool:
    try:
        client = make_client(account)
        await client.connect()
        try:
            await client(UpdateProfileRequest(about=bio))
            return True
        finally:
            await client.disconnect()
    except Exception:
        return False
