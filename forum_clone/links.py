import re

from telethon import types

_LINK_RE_TEMPLATE = r"(?:https?://)?(?:www\.)?t\.me/(?:{bases})/(?P<topic>\d+)(?:/\d+)?(?:[?#]\S*)?"


def build_link_rewriter(source, target, topic_map):
    """Returns a function url -> rewritten url (or None if url isn't a link
    to a source-forum topic covered by topic_map)."""
    bases = [re.escape(str(source.id))]
    username = getattr(source, "username", None)
    if username:
        bases.append(re.escape(username))
    pattern = re.compile(_LINK_RE_TEMPLATE.format(bases="|".join(bases)), re.IGNORECASE)

    def rewrite(url):
        m = pattern.fullmatch(url.strip())
        if not m:
            return None
        source_topic_id = int(m.group("topic"))
        target_topic_id = topic_map.get(source_topic_id)
        if target_topic_id is None:
            return None
        return f"https://t.me/c/{target.id}/{target_topic_id}"

    return rewrite


def rewrite_message_links(msg, rewrite):
    """Rewrites hidden-hyperlink (MessageEntityTextUrl) entities that point to
    a source-forum topic. Returns (text, entities, unresolved_raw_urls) where
    unresolved_raw_urls lists plain-text URLs (MessageEntityUrl) that look like
    they might need manual fixing (rewriting raw pasted links in-place is not
    attempted, to avoid corrupting the message text)."""
    text = msg.text or ""
    entities = list(msg.entities or [])
    new_entities = []
    unresolved = []

    for e in entities:
        if isinstance(e, types.MessageEntityTextUrl):
            new_url = rewrite(e.url)
            if new_url:
                e = types.MessageEntityTextUrl(offset=e.offset, length=e.length, url=new_url)
        elif isinstance(e, types.MessageEntityUrl):
            raw = _slice_utf16(text, e.offset, e.length)
            if rewrite(raw):
                unresolved.append(raw)
        new_entities.append(e)

    return text, new_entities, unresolved


def _slice_utf16(text, offset, length):
    b = text.encode("utf-16-le")
    return b[offset * 2:(offset + length) * 2].decode("utf-16-le")
