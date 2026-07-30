from .forward import forward_topic_messages
from .links import build_link_rewriter
from .messages import clone_topic_messages
from .telegram import (
    copy_about,
    copy_profile_photo,
    ensure_topic,
    fetch_all_topics,
    finalize_topic,
    get_or_create_target,
)


def _is_nav_topic(cfg, t):
    return t.title.strip().casefold() == cfg.NAV_TOPIC_TITLE.strip().casefold()


async def run_pipeline(client, cfg, state, source, target_title, delay, topics_only=False):
    """The actual clone: create/reuse the target group, mirror the topic
    structure, then either stop (topics_only) or forward all content.
    Shared by both the CLI (clone.py) and the GUI (gui.py)."""
    target = await get_or_create_target(client, source, cfg, state, title=target_title)
    await copy_about(client, source, target)
    await copy_profile_photo(client, source, target, cfg.DOWNLOAD_DIR)

    print("Считываю список тем источника...")
    source_topics = await fetch_all_topics(client, source)
    print(f"Найдено тем: {len(source_topics)}")

    nav_topic = next((t for t in source_topics if _is_nav_topic(cfg, t)), None)
    regular_topics = [t for t in source_topics if t is not nav_topic]
    if nav_topic:
        print(f"Тема-навигация «{nav_topic.title}» будет создана и заполнена последней.")

    print("Создаю обычные темы в клоне (если ещё не созданы)...")
    mapping = {}
    for t in regular_topics:
        mapping[t.id] = await ensure_topic(client, target, t, state)

    if topics_only:
        if nav_topic:
            mapping[nav_topic.id] = await ensure_topic(client, target, nav_topic, state)
        print("Готово: структура тем создана (без копирования сообщений).")
        return

    warnings = []
    total = 0
    for t in regular_topics:
        target_topic_id = mapping[t.id]
        print(f"Тема «{t.title}» (источник #{t.id} -> клон #{target_topic_id})")
        n = await forward_topic_messages(client, source, target, t.id, target_topic_id, state, delay)
        total += n
        print(f"  = {n} новых сообщений переслано")
        await finalize_topic(client, target, t, target_topic_id)

    if nav_topic:
        nav_target_id = await ensure_topic(client, target, nav_topic, state)
        mapping[nav_topic.id] = nav_target_id
        print(f"Тема «{nav_topic.title}» (источник #{nav_topic.id} -> клон #{nav_target_id})")
        rewrite = build_link_rewriter(source, target, mapping)
        n = await clone_topic_messages(
            client, source, target, nav_topic.id, nav_target_id,
            state, cfg.DOWNLOAD_DIR, delay, link_rewrite=rewrite, warnings=warnings,
        )
        total += n
        print(f"  = {n} новых сообщений скопировано (ссылки на темы переписаны)")
        await finalize_topic(client, target, nav_topic, nav_target_id)

    print(f"Готово. Всего скопировано {total} сообщений в этом запуске.")
    if warnings:
        print(f"\nВНИМАНИЕ: {len(warnings)} ссылок в теме-навигации не удалось переписать автоматически "
              f"(это не скрытые ссылки, а голый текст вида t.me/...). Проверьте вручную:")
        for w in warnings:
            print(f"  - {w}")
    print("\nЗапустите повторно в любой момент, чтобы докопировать новые материалы.")
