import asyncio

from telethon import helpers, types
from telethon.tl.functions.messages import ForwardMessagesRequest

from .telegram import retry_flood


async def _forward_unit(client, source, target, topic_id, msgs):
    """Forwards one message or one whole album in a single server-side call
    (no download/upload) with the origin hidden via drop_author. Returns
    {source_msg_id: target_msg_id} for the messages that were forwarded."""
    ids = [m.id for m in msgs]
    random_ids = [helpers.generate_random_long() for _ in ids]

    try:
        request = ForwardMessagesRequest(
            from_peer=source, id=ids, random_id=random_ids, to_peer=target,
            top_msg_id=topic_id, drop_author=True,
        )
        result = await retry_flood(client, request)
    except TypeError:
        # This Telethon/Telegram layer doesn't know drop_author - falls back
        # to a normal forward, which WILL show "Forwarded from ...".
        request = ForwardMessagesRequest(
            from_peer=source, id=ids, random_id=random_ids, to_peer=target,
            top_msg_id=topic_id,
        )
        result = await retry_flood(client, request)

    id_map = {}
    for upd in result.updates:
        if isinstance(upd, types.UpdateMessageID):
            id_map[upd.random_id] = upd.id

    return {msg.id: id_map.get(rid) for msg, rid in zip(msgs, random_ids)}


async def forward_topic_messages(client, source, target, source_topic_id, target_topic_id,
                                   state, delay):
    """Forwards all not-yet-copied messages of one topic, oldest first, using
    a native server-side forward with the origin hidden (drop_author) - no
    "Forwarded from" tag, and no local download/upload of media."""
    entry = state.get_topic(source_topic_id) or {}
    last_id = entry.get("last_msg_id", 0)

    unit = []
    unit_grouped_id = None
    count = 0

    async def flush():
        nonlocal unit, unit_grouped_id, count
        if not unit:
            return
        id_map = await _forward_unit(client, source, target, target_topic_id, unit)
        for m in unit:
            if getattr(m, "pinned", False):
                target_msg_id = id_map.get(m.id)
                if target_msg_id:
                    try:
                        await retry_flood(client.pin_message, target, target_msg_id, notify=False)
                    except Exception as e:
                        print(f"    ! не удалось закрепить сообщение: {e}")
        state.set_last_msg_id(source_topic_id, unit[-1].id)
        count += len(unit)
        unit, unit_grouped_id = [], None
        await asyncio.sleep(delay)

    async for msg in client.iter_messages(source, reverse=True, reply_to=source_topic_id, min_id=last_id):
        if msg.id <= last_id:
            continue

        if msg.action is not None:
            # Service message (topic created/renamed, pin notice, ...) - nothing to forward.
            state.set_last_msg_id(source_topic_id, msg.id)
            continue

        if msg.grouped_id is not None and msg.grouped_id == unit_grouped_id:
            unit.append(msg)
            continue

        await flush()
        unit_grouped_id = msg.grouped_id
        unit.append(msg)

        if unit_grouped_id is None:
            await flush()

    await flush()
    return count
