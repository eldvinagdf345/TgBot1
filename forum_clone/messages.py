import os

from telethon import types

from .telegram import retry_flood


def _topic_reply(topic_id):
    # Explicit InputReplyToMessage so the message lands in the right forum
    # topic regardless of how a given Telethon version auto-converts a bare int.
    return types.InputReplyToMessage(reply_to_msg_id=topic_id, top_msg_id=topic_id)


async def clone_topic_messages(client, source, target, source_topic_id, target_topic_id,
                                 state, download_dir, delay):
    entry = state.get_topic(source_topic_id) or {}
    last_id = entry.get("last_msg_id", 0)

    album = []
    album_id = None
    count = 0

    async def flush():
        nonlocal album, album_id, count
        if not album:
            return
        await _send_album(client, target, target_topic_id, album, download_dir)
        state.set_last_msg_id(source_topic_id, album[-1].id)
        count += len(album)
        album, album_id = [], None

    async for msg in client.iter_messages(source, reverse=True, reply_to=source_topic_id, min_id=last_id):
        if msg.id <= last_id:
            continue

        if msg.action is not None:
            # Service message (topic created/renamed, pin notice, ...) - no content to copy.
            state.set_last_msg_id(source_topic_id, msg.id)
            continue

        if msg.grouped_id is not None:
            if album_id is not None and msg.grouped_id != album_id:
                await flush()
            album_id = msg.grouped_id
            album.append(msg)
            continue

        await flush()
        await _send_single(client, target, target_topic_id, msg, download_dir)
        state.set_last_msg_id(source_topic_id, msg.id)
        count += 1

        if count and count % 20 == 0:
            print(f"    … скопировано {count} сообщений")

    await flush()
    return count


async def _send_single(client, target, topic_id, msg, download_dir):
    path = None
    try:
        if msg.media and not isinstance(msg.media, types.MessageMediaWebPage):
            os.makedirs(download_dir, exist_ok=True)
            path = await retry_flood(client.download_media, msg, file=download_dir + os.sep)

        if not path and not (msg.text or "").strip():
            return  # nothing to copy (e.g. unsupported media type)

        await retry_flood(
            client.send_message,
            target, msg.text or "",
            file=path,
            reply_to=_topic_reply(topic_id),
            formatting_entities=msg.entities,
            link_preview=False,
        )
    finally:
        if path and os.path.exists(path):
            os.remove(path)


async def _send_album(client, target, topic_id, msgs, download_dir):
    paths = []
    try:
        os.makedirs(download_dir, exist_ok=True)
        for m in msgs:
            if m.media and not isinstance(m.media, types.MessageMediaWebPage):
                p = await retry_flood(client.download_media, m, file=download_dir + os.sep)
                if p:
                    paths.append(p)

        caption_msg = next((m for m in msgs if (m.text or "").strip()), None)
        caption = caption_msg.text if caption_msg else ""
        entities = caption_msg.entities if caption_msg else None

        if not paths:
            if caption:
                await retry_flood(
                    client.send_message, target, caption,
                    reply_to=_topic_reply(topic_id), formatting_entities=entities, link_preview=False,
                )
            return

        await retry_flood(
            client.send_file, target, paths,
            caption=caption, reply_to=_topic_reply(topic_id), formatting_entities=entities,
        )
    finally:
        for p in paths:
            if os.path.exists(p):
                os.remove(p)
