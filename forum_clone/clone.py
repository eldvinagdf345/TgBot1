import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient

from forum_clone import config as cfg
from forum_clone.state import State
from forum_clone.telegram import (
    copy_about,
    copy_profile_photo,
    ensure_topic,
    fetch_all_topics,
    finalize_topic,
    get_or_create_target,
    is_forum,
)
from forum_clone.links import build_link_rewriter
from forum_clone.messages import clone_topic_messages


async def list_chats(client):
    print("Ваши чаты (id, username, название):")
    async for d in client.iter_dialogs():
        username = f"@{d.entity.username}" if getattr(d.entity, "username", None) else "-"
        print(f"  {d.id:>15}  {username:<25}  {d.title}")


def _is_nav_topic(t):
    return t.title.strip().casefold() == cfg.NAV_TOPIC_TITLE.strip().casefold()


async def run(args):
    client = TelegramClient(cfg.SESSION_NAME, cfg.API_ID, cfg.API_HASH)
    await client.start()

    if args.list_chats:
        await list_chats(client)
        await client.disconnect()
        return

    state = State(cfg.STATE_FILE)
    if args.reset:
        state.reset()
        print("Прогресс сброшен, клон будет пересобран заново.")

    print(f"Читаю исходный форум: {cfg.SOURCE_CHAT}")
    source = await client.get_entity(cfg.SOURCE_CHAT)
    forum, _ = await is_forum(client, source)
    if not forum:
        raise SystemExit(
            "Источник не является форумом (группой с включёнными темами). "
            "Включите темы в настройках группы и попробуйте снова."
        )

    target = await get_or_create_target(client, source, cfg, state)
    await copy_about(client, source, target)
    await copy_profile_photo(client, source, target, cfg.DOWNLOAD_DIR)

    print("Считываю список тем источника...")
    source_topics = await fetch_all_topics(client, source)
    print(f"Найдено тем: {len(source_topics)}")

    nav_topic = next((t for t in source_topics if _is_nav_topic(t)), None)
    regular_topics = [t for t in source_topics if t is not nav_topic]
    if nav_topic:
        print(f"Тема-навигация «{nav_topic.title}» будет создана и заполнена последней.")

    print("Создаю обычные темы в клоне (если ещё не созданы)...")
    mapping = {}
    for t in regular_topics:
        mapping[t.id] = await ensure_topic(client, target, t, state)

    if args.topics_only and not nav_topic:
        print("Готово: структура тем создана (--topics-only, сообщения не копировались).")
        await client.disconnect()
        return

    warnings = []
    total = 0

    if not args.topics_only:
        for t in regular_topics:
            target_topic_id = mapping[t.id]
            print(f"Тема «{t.title}» (источник #{t.id} -> клон #{target_topic_id})")
            n = await clone_topic_messages(
                client, source, target, t.id, target_topic_id,
                state, cfg.DOWNLOAD_DIR, cfg.DELAY_SECONDS,
            )
            total += n
            print(f"  = {n} новых сообщений скопировано")
            await finalize_topic(client, target, t, target_topic_id)

    if nav_topic:
        nav_target_id = await ensure_topic(client, target, nav_topic, state)
        mapping[nav_topic.id] = nav_target_id
        if not args.topics_only:
            print(f"Тема «{nav_topic.title}» (источник #{nav_topic.id} -> клон #{nav_target_id})")
            rewrite = build_link_rewriter(source, target, mapping)
            n = await clone_topic_messages(
                client, source, target, nav_topic.id, nav_target_id,
                state, cfg.DOWNLOAD_DIR, cfg.DELAY_SECONDS,
                link_rewrite=rewrite, warnings=warnings,
            )
            total += n
            print(f"  = {n} новых сообщений скопировано (ссылки на темы переписаны)")
            await finalize_topic(client, target, nav_topic, nav_target_id)

    if args.topics_only:
        print("Готово: структура тем создана (--topics-only, сообщения не копировались).")
        await client.disconnect()
        return

    print(f"Готово. Всего скопировано {total} сообщений в этом запуске.")
    if warnings:
        print(f"\nВНИМАНИЕ: {len(warnings)} ссылок в теме-навигации не удалось переписать автоматически "
              f"(это не скрытые ссылки, а голый текст вида t.me/...). Проверьте вручную:")
        for w in warnings:
            print(f"  - {w}")
    print("\nЗапустите скрипт повторно в любой момент, чтобы докопировать новые материалы.")
    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Клонирует форум-группу Telegram 1-в-1, включая темы.")
    parser.add_argument("--reset", action="store_true", help="забыть прогресс и пересобрать клон с нуля")
    parser.add_argument("--topics-only", action="store_true", help="только создать темы, без копирования сообщений")
    parser.add_argument("--list-chats", action="store_true", help="вывести id/username ваших чатов и выйти")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
