import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient

from forum_clone import config as cfg
from forum_clone.state import State
from forum_clone.telegram import is_forum, resolve_chat_ref
from forum_clone.pipeline import run_pipeline


async def list_chats(client):
    print("Ваши чаты (id, username, название):")
    async for d in client.iter_dialogs():
        username = f"@{d.entity.username}" if getattr(d.entity, "username", None) else "-"
        print(f"  {d.id:>15}  {username:<25}  {d.title}")


async def pick_source_chat(client):
    """Lets the user pick the source forum by number instead of typing an id."""
    print("\nЗагружаю список ваших групп...")
    dialogs = [d async for d in client.iter_dialogs() if d.is_group or d.is_channel]
    if not dialogs:
        raise SystemExit("Не нашёл ни одной группы/канала на этом аккаунте.")

    print("\nВыберите группу-источник (форум, который нужно клонировать):\n")
    for i, d in enumerate(dialogs, 1):
        kind = "форум" if getattr(d.entity, "forum", False) else "группа"
        username = f" @{d.entity.username}" if getattr(d.entity, "username", None) else ""
        print(f"  {i}. {d.title}  [{kind}]{username}")

    while True:
        raw = input("\nНомер группы-источника: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(dialogs):
            chosen = dialogs[int(raw) - 1].entity
            cfg.save_to_env("SOURCE_CHAT", chosen.id)
            print(f"  (запомнил «{dialogs[int(raw) - 1].title}» как источник, в следующий раз спрашивать не буду)\n")
            return chosen
        print("  Некорректный номер, попробуйте ещё раз.")


async def run(args):
    if args.switch_account:
        cfg.clear_env_keys("API_ID", "API_HASH", "SOURCE_CHAT")
        for suffix in (".session", ".session-journal"):
            path = cfg.SESSION_NAME + suffix
            if os.path.exists(path):
                os.remove(path)
        print("Данные предыдущего аккаунта сброшены - сейчас спрошу новые API_ID/API_HASH и номер телефона.\n")

    api_id = cfg.get_api_id()
    api_hash = cfg.get_api_hash()
    client = TelegramClient(cfg.SESSION_NAME, api_id, api_hash)
    await client.start()

    if args.list_chats:
        await list_chats(client)
        await client.disconnect()
        return

    state = State(cfg.STATE_FILE)
    if args.reset or args.switch_account:
        # A group/topics created under the old account likely isn't owned by
        # the new one either, so there's nothing to safely resume from.
        state.reset()
        print("Прогресс сброшен, клон будет пересобран заново.")

    if cfg.SOURCE_CHAT:
        source = await client.get_entity(resolve_chat_ref(cfg.SOURCE_CHAT))
    else:
        source = await pick_source_chat(client)

    print(f"Источник: {source.title}")
    forum, _ = await is_forum(client, source)
    if not forum:
        raise SystemExit(
            "Источник не является форумом (группой с включёнными темами). "
            "Включите темы в настройках группы и попробуйте снова."
        )

    target_title = cfg.TARGET_TITLE
    if not target_title and not cfg.TARGET_CHAT and not state.target_chat_id:
        raw = input(f"Название новой группы-клона [{source.title}]: ").strip()
        target_title = raw or source.title

    await run_pipeline(client, cfg, state, source, target_title, cfg.DELAY_SECONDS, topics_only=args.topics_only)
    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Клонирует форум-группу Telegram 1-в-1, включая темы.")
    parser.add_argument("--reset", action="store_true", help="забыть прогресс и пересобрать клон с нуля")
    parser.add_argument("--topics-only", action="store_true", help="только создать темы, без копирования сообщений")
    parser.add_argument("--list-chats", action="store_true", help="вывести id/username ваших чатов и выйти")
    parser.add_argument("--switch-account", action="store_true",
                         help="забыть API_ID/API_HASH/сессию/источник и залогиниться заново под другим аккаунтом")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
