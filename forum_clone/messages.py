import os

from telethon import types

from .links import rewrite_message_links
from .telegram import retry_flood


def _topic_reply(topic_id):
    # Explicit InputReplyToMessage so the message lands in the right forum
    # topic regardless of how a given Telethon version auto-converts a bare int.
    return types.InputReplyToMessage(reply_to_msg_id=topic_id, top_msg_id=topic_id)


def _sanitize_attributes(attrs):
    """Keeps voice/round-video/sticker/animated(GIF) flags, but strips the
    original sticker-pack reference (invalid once re-uploaded as a new file)."""
    result = []
    for a in attrs or []:
        if isinstance(a, types.DocumentAttributeSticker):
            result.append(types.DocumentAttributeSticker(
                alt=a.alt, stickerset=types.InputStickerSetEmpty(),
                mask=a.mask, mask_coords=a.mask_coords,
            ))
        else:
            result.append(a)
    return result


def _poll_input_media(msg):
    poll = msg.media.poll
    results = msg.media.results
    correct = [r.option for r in (results.results or []) if getattr(r, "correct", False)] if results else []
    return types.InputMediaPoll(
        poll=types.Poll(
            id=0,
            question=poll.question,
            answers=poll.answers,
            closed=False,
            public_voters=poll.public_voters,
            multiple_choice=poll.multiple_choice,
            quiz=poll.quiz,
        ),
        correct_answers=correct or None,
        solution=getattr(results, "solution", None),
        solution_entities=getattr(results, "solution_entities", None),
    )


def _contact_input_media(msg):
    c = msg.media
    return types.InputMediaContact(
        phone_number=c.phone_number, first_name=c.first_name,
        last_name=c.last_name, vcard=c.vcard or "",
    )


def _geo_input_media(msg):
    m = msg.media
    if isinstance(m, types.MessageMediaVenue):
        return types.InputMediaVenue(
            geo_point=types.InputGeoPoint(lat=m.geo.lat, long=m.geo.long),
            title=m.title, address=m.address, provider=m.provider,
            venue_id=m.venue_id, venue_type=m.venue_type,
        )
    return types.InputMediaGeoPoint(geo_point=types.InputGeoPoint(lat=m.geo.lat, long=m.geo.long))


async def clone_topic_messages(client, source, target, source_topic_id, target_topic_id,
                                 state, download_dir, delay, link_rewrite=None, warnings=None):
    """Copies all not-yet-copied messages of one topic, oldest first.
    If link_rewrite is given (used for the navigation topic only), hidden
    hyperlinks pointing at a source-forum topic are rewritten to the target."""
    entry = state.get_topic(source_topic_id) or {}
    last_id = entry.get("last_msg_id", 0)

    album = []
    album_id = None
    count = 0

    async def flush():
        nonlocal album, album_id, count
        if not album:
            return
        await _send_album(client, target, target_topic_id, album, download_dir, link_rewrite, warnings)
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
        await _send_single(client, target, target_topic_id, msg, download_dir, link_rewrite, warnings)
        state.set_last_msg_id(source_topic_id, msg.id)
        count += 1

        if count and count % 20 == 0:
            print(f"    … скопировано {count} сообщений")

    await flush()
    return count


async def _pin_if_needed(client, target, source_msg, sent_msg):
    if not getattr(source_msg, "pinned", False) or sent_msg is None:
        return
    try:
        await retry_flood(client.pin_message, target, sent_msg, notify=False)
    except Exception as e:
        print(f"    ! не удалось закрепить сообщение: {e}")


def _prepare_text(msg, link_rewrite, warnings):
    if link_rewrite is None:
        return msg.text or "", msg.entities
    text, entities, unresolved = rewrite_message_links(msg, link_rewrite)
    if unresolved and warnings is not None:
        for u in unresolved:
            warnings.append(f"тема-навигация, сообщение #{msg.id}: не смог автоматически "
                             f"переписать ссылку в тексте (не скрытая ссылка): {u}")
    return text, entities


async def _send_single(client, target, topic_id, msg, download_dir, link_rewrite=None, warnings=None):
    media = msg.media
    text, entities = _prepare_text(msg, link_rewrite, warnings)

    if media is None:
        sent = None
        if text.strip():
            sent = await retry_flood(
                client.send_message, target, text,
                reply_to=_topic_reply(topic_id),
                formatting_entities=entities, link_preview=False,
            )
        await _pin_if_needed(client, target, msg, sent)
        return

    if isinstance(media, types.MessageMediaPoll):
        try:
            sent = await retry_flood(
                client.send_message, target, "",
                file=_poll_input_media(msg), reply_to=_topic_reply(topic_id),
            )
        except Exception as e:
            print(f"    ! опрос #{msg.id} не пересоздан ({e}), копирую как текст")
            sent = await retry_flood(
                client.send_message, target, f"[Опрос] {media.poll.question}",
                reply_to=_topic_reply(topic_id),
            )
        await _pin_if_needed(client, target, msg, sent)
        return

    if isinstance(media, types.MessageMediaContact):
        sent = await retry_flood(
            client.send_message, target, "", file=_contact_input_media(msg),
            reply_to=_topic_reply(topic_id),
        )
        await _pin_if_needed(client, target, msg, sent)
        return

    if isinstance(media, (types.MessageMediaGeo, types.MessageMediaVenue)):
        sent = await retry_flood(
            client.send_message, target, "", file=_geo_input_media(msg),
            reply_to=_topic_reply(topic_id),
        )
        await _pin_if_needed(client, target, msg, sent)
        return

    if isinstance(media, types.MessageMediaWebPage):
        sent = None
        if text.strip():
            sent = await retry_flood(
                client.send_message, target, text, reply_to=_topic_reply(topic_id),
                formatting_entities=entities, link_preview=False,
            )
        await _pin_if_needed(client, target, msg, sent)
        return

    # Photo / document (video, file, voice, round video, sticker, gif, audio)
    path = None
    try:
        os.makedirs(download_dir, exist_ok=True)
        path = await retry_flood(client.download_media, msg, file=download_dir + os.sep)
        if not path:
            return
        attrs = _sanitize_attributes(msg.document.attributes) if msg.document else None
        sent = await retry_flood(
            client.send_message, target, text,
            file=path, attributes=attrs,
            reply_to=_topic_reply(topic_id),
            formatting_entities=entities, link_preview=False,
        )
        await _pin_if_needed(client, target, msg, sent)
    finally:
        if path and os.path.exists(path):
            os.remove(path)


async def _send_album(client, target, topic_id, msgs, download_dir, link_rewrite=None, warnings=None):
    paths = []
    attrs_list = []
    try:
        os.makedirs(download_dir, exist_ok=True)
        for m in msgs:
            if isinstance(m.media, (types.MessageMediaDocument, types.MessageMediaPhoto)):
                p = await retry_flood(client.download_media, m, file=download_dir + os.sep)
                if p:
                    paths.append(p)
                    attrs_list.append(_sanitize_attributes(m.document.attributes) if m.document else None)

        caption_msg = next((m for m in msgs if (m.text or "").strip()), None)
        caption, entities = "", None
        if caption_msg:
            caption, entities = _prepare_text(caption_msg, link_rewrite, warnings)

        if not paths:
            sent = None
            if caption:
                sent = await retry_flood(
                    client.send_message, target, caption,
                    reply_to=_topic_reply(topic_id), formatting_entities=entities, link_preview=False,
                )
            if sent:
                for m in msgs:
                    await _pin_if_needed(client, target, m, sent)
            return

        sent = await retry_flood(
            client.send_file, target, paths,
            caption=caption, reply_to=_topic_reply(topic_id), formatting_entities=entities,
            attributes=attrs_list if any(attrs_list) else None,
        )
        sent_list = sent if isinstance(sent, list) else [sent]
        if sent_list:
            for m in msgs:
                if getattr(m, "pinned", False):
                    await _pin_if_needed(client, target, m, sent_list[0])
    finally:
        for p in paths:
            if os.path.exists(p):
                os.remove(p)
