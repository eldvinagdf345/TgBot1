import asyncio
import os

from telethon import types
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    CreateForumTopicRequest,
    EditForumTopicRequest,
    EditPhotoRequest,
    EditTitleRequest,
    GetForumTopicsRequest,
    GetFullChannelRequest,
    ToggleForumRequest,
)
from telethon.tl.functions.messages import EditChatAboutRequest


async def retry_flood(coro_func, *args, **kwargs):
    """Calls coro_func(*args, **kwargs), retrying on Telegram's FloodWait."""
    while True:
        try:
            return await coro_func(*args, **kwargs)
        except FloodWaitError as e:
            wait = e.seconds + 1
            print(f"    … flood-wait, жду {wait} сек.")
            await asyncio.sleep(wait)


async def is_forum(client, channel):
    full = await client(GetFullChannelRequest(channel))
    return bool(full.full_chat.forum), full


async def get_or_create_target(client, source, cfg, state):
    if state.target_chat_id:
        try:
            return await client.get_entity(state.target_chat_id)
        except Exception:
            print("  ! сохранённая целевая группа недоступна, ищу/создаю заново")

    title = cfg.TARGET_TITLE or source.title

    if cfg.TARGET_CHAT:
        target = await client.get_entity(cfg.TARGET_CHAT)
        forum, _ = await is_forum(client, target)
        if not forum:
            await retry_flood(client, ToggleForumRequest(channel=target, enabled=True))
        if getattr(target, "title", None) != title:
            await retry_flood(client, EditTitleRequest(channel=target, title=title))
        state.target_chat_id = target.id
        print(f"Использую существующую группу «{title}» как клон (id {target.id})")
        return target

    _, source_full = await is_forum(client, source)
    about = source_full.full_chat.about or ""

    try:
        request = CreateChannelRequest(title=title, about=about, megagroup=True, forum=True)
    except TypeError:
        # Older Telethon releases don't expose `forum=` on CreateChannelRequest.
        request = CreateChannelRequest(title=title, about=about, megagroup=True)
    result = await retry_flood(client, request)

    target = result.chats[0]
    forum, _ = await is_forum(client, target)
    if not forum:
        await retry_flood(client, ToggleForumRequest(channel=target, enabled=True))

    state.target_chat_id = target.id
    print(f"Создана новая группа-форум «{title}» (id {target.id})")
    return target


async def copy_profile_photo(client, source, target, tmp_dir):
    if not source.photo or isinstance(source.photo, types.ChatPhotoEmpty):
        return
    os.makedirs(tmp_dir, exist_ok=True)
    path = await client.download_profile_photo(source, file=os.path.join(tmp_dir, "avatar"))
    if not path:
        return
    try:
        uploaded = await client.upload_file(path)
        await retry_flood(
            client,
            EditPhotoRequest(channel=target, photo=types.InputChatUploadedPhoto(file=uploaded)),
        )
        print("  + аватар скопирован")
    except Exception as e:
        print(f"  ! не удалось скопировать аватар: {e}")
    finally:
        if os.path.exists(path):
            os.remove(path)


async def copy_about(client, source, target):
    _, source_full = await is_forum(client, source)
    about = source_full.full_chat.about or ""
    if not about:
        return
    try:
        await retry_flood(client, EditChatAboutRequest(peer=target, about=about))
        print("  + описание скопировано")
    except Exception as e:
        print(f"  ! не удалось скопировать описание: {e}")


async def fetch_all_topics(client, source):
    """Returns source forum topics ordered by creation (ascending id)."""
    topics = []
    offset_date, offset_id, offset_topic = 0, 0, 0
    while True:
        request = GetForumTopicsRequest(
            channel=source, offset_date=offset_date, offset_id=offset_id,
            offset_topic=offset_topic, limit=100,
        )
        res = await retry_flood(client, request)
        if not res.topics:
            break
        topics.extend(res.topics)
        if len(res.topics) < 100:
            break
        last = res.topics[-1]
        offset_topic = last.id
        offset_id = last.top_message
        last_msg = next((m for m in res.messages if m.id == last.top_message), None)
        offset_date = int(last_msg.date.timestamp()) if last_msg else 0

    topics.sort(key=lambda t: t.id)
    return topics


async def ensure_target_topics(client, target, source_topics, state):
    """Creates matching topics in the target forum, returns {source_id: target_id}."""
    mapping = {}
    for t in source_topics:
        existing = state.get_topic(t.id)
        if existing:
            mapping[t.id] = existing["target_topic_id"]
            continue

        if t.id == 1:
            # Topic id 1 is Telegram's built-in "General" topic - it already
            # exists in every forum, we just rename it to match the source.
            try:
                await retry_flood(client, EditForumTopicRequest(channel=target, topic_id=1, title=t.title))
            except Exception:
                pass
            state.set_topic_mapping(t.id, 1)
            mapping[t.id] = 1
            print(f"  + тема «{t.title}» -> General")
            continue

        request = CreateForumTopicRequest(
            channel=target, title=t.title,
            icon_color=getattr(t, "icon_color", None),
            icon_emoji_id=getattr(t, "icon_emoji_id", None) or None,
        )
        result = await retry_flood(client, request)
        new_id = None
        for upd in result.updates:
            msg = getattr(upd, "message", None)
            if msg is not None and isinstance(getattr(msg, "action", None), types.MessageActionTopicCreate):
                new_id = msg.id
                break
        if new_id is None:
            raise RuntimeError(f"Не удалось определить id новой темы «{t.title}»")

        state.set_topic_mapping(t.id, new_id)
        mapping[t.id] = new_id
        print(f"  + тема «{t.title}» создана (id {new_id})")

    return mapping
