import asyncio

from .forward import forward_topic_messages
from .links import build_link_rewriter
from .messages import clone_topic_messages
from .telegram import (
    copy_about,
    copy_profile_photo,
    ensure_topic,
    ensure_worker_in_target,
    fetch_all_topics,
    finalize_topic,
    get_or_create_target,
    lock_target_permissions,
    make_anonymous_admin,
    worker_can_read_source,
)


def _is_nav_topic(cfg, t):
    return t.title.strip().casefold() == cfg.NAV_TOPIC_TITLE.strip().casefold()


def _distribute(topics, n):
    """Round-robin split, so a fast run of small topics next to a big one
    doesn't systematically pile onto the same worker."""
    buckets = [[] for _ in range(n)]
    for i, t in enumerate(topics):
        buckets[i % n].append(t)
    return buckets


async def _forward_worker(client, source, target, topics, mapping, state, delay, label):
    total = 0
    for t in topics:
        target_topic_id = mapping[t.id]
        print(f"[{label}] Тема «{t.title}» (источник #{t.id} -> клон #{target_topic_id})")
        n = await forward_topic_messages(client, source, target, t.id, target_topic_id, state, delay)
        total += n
        print(f"[{label}]   = {n} новых сообщений переслано")
        await finalize_topic(client, target, t, target_topic_id)
    return total


async def run_pipeline(client, cfg, state, source, target_title, delay, topics_only=False, workers=None):
    """The actual clone: create/reuse the target group, mirror the topic
    structure, then either stop (topics_only) or forward all content.
    Shared by both the CLI (clone.py) and the GUI (gui.py). `workers` is an
    optional list of additional logged-in TelegramClients that help forward
    regular-topic content in parallel (topics split round-robin between
    `client` and them) - each must already be a member of the source chat."""
    target = await get_or_create_target(client, source, cfg, state, title=target_title)
    await copy_about(client, source, target)
    await copy_profile_photo(client, source, target, cfg.DOWNLOAD_DIR)
    await lock_target_permissions(client, target)
    me = await client.get_me()
    await make_anonymous_admin(client, target, me, me.first_name or "основной аккаунт")

    usable_workers = []
    for w in workers or []:
        if await worker_can_read_source(w, source):
            if await ensure_worker_in_target(client, target, w):
                usable_workers.append(w)
        else:
            me = await w.get_me()
            print(f"  ! аккаунт «{me.first_name or me.id}» не состоит в группе-источнике - "
                  f"добавьте его туда вручную. Пропускаю этот аккаунт для переноса.")

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
    all_clients = [client] + usable_workers
    buckets = _distribute(regular_topics, len(all_clients))
    if usable_workers:
        sizes = ", ".join(str(len(b)) for b in buckets)
        print(f"Распределяю {len(regular_topics)} тем между {len(all_clients)} аккаунтами ({sizes} тем на каждого)")

    results = await asyncio.gather(*[
        _forward_worker(c, source, target, b, mapping, state, delay, f"аккаунт {i + 1}")
        for i, (c, b) in enumerate(zip(all_clients, buckets)) if b
    ])
    total = sum(results)

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
