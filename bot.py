import asyncio
import logging
import os

from telethon import TelegramClient, events

import database as db
from parser import run_search

log = logging.getLogger(__name__)

ADMIN_ID       = int(os.getenv("ADMIN_USER_ID", "0"))
SEARCH_INTERVAL = int(os.getenv("SEARCH_INTERVAL_MINUTES", "5")) * 60


class State:
    search_running = False
    paused         = False
    loop_task      = None
    last_run       = "никогда"
    next_run       = "—"


def _is_admin(event) -> bool:
    return event.sender_id == ADMIN_ID


async def _auto_loop(user_client: TelegramClient, bot: TelegramClient):
    """Background loop: search every SEARCH_INTERVAL seconds."""
    import time
    from datetime import datetime, timedelta

    log.info("Auto-search loop started (every %ds)", SEARCH_INTERVAL)
    await asyncio.sleep(10)   # small delay before first auto-run

    while True:
        if not State.paused:
            if not State.search_running:
                State.search_running = True
                State.last_run = datetime.utcnow().strftime("%H:%M:%S UTC")
                try:
                    count = await run_search(user_client, bot, ADMIN_ID)
                    log.info("Auto-search done. New posts: %d", count)
                    if count:
                        await bot.send_message(
                            ADMIN_ID,
                            f"🔄 Авто-поиск завершён. Новых постов: `{count}`",
                            parse_mode="markdown"
                        )
                except Exception as e:
                    log.exception("Auto-search error: %s", e)
                finally:
                    State.search_running = False

            next_dt = datetime.utcnow() + timedelta(seconds=SEARCH_INTERVAL)
            State.next_run = next_dt.strftime("%H:%M:%S UTC")

        await asyncio.sleep(SEARCH_INTERVAL)


def register(bot: TelegramClient, user_client: TelegramClient):

    # /start
    @bot.on(events.NewMessage(pattern=r"^/start$"))
    async def _(event):
        if not _is_admin(event): return
        await event.respond(
            "👋 **TG Hashtag Parser**\n\n"
            "`/add_tag #TOKEN` — добавить тег\n"
            "`/remove_tag #TOKEN` — убрать тег\n"
            "`/list_tags` — все теги\n"
            "`/run_search` — запустить поиск вручную\n"
            "`/pause` — приостановить авто-поиск\n"
            "`/resume` — возобновить авто-поиск\n"
            "`/stats` — статистика\n"
            "`/status` — состояние",
            parse_mode="markdown"
        )

    # /add_tag
    @bot.on(events.NewMessage(pattern=r"^/add_tag\s+(\S+)$"))
    async def _(event):
        if not _is_admin(event): return
        raw = event.pattern_match.group(1).strip()
        tag = raw if raw.startswith("#") else f"#{raw}"
        added = db.add_tag(tag)
        txt = f"✅ Тег `{tag}` добавлен." if added else f"ℹ️ Тег `{tag}` уже есть (активирован)."
        await event.respond(txt, parse_mode="markdown")

    # /remove_tag
    @bot.on(events.NewMessage(pattern=r"^/remove_tag\s+(\S+)$"))
    async def _(event):
        if not _is_admin(event): return
        raw = event.pattern_match.group(1).strip()
        tag = raw if raw.startswith("#") else f"#{raw}"
        ok = db.remove_tag(tag)
        txt = f"🗑 Тег `{tag}` деактивирован." if ok else f"⚠️ Тег `{tag}` не найден."
        await event.respond(txt, parse_mode="markdown")

    # /list_tags
    @bot.on(events.NewMessage(pattern=r"^/list_tags$"))
    async def _(event):
        if not _is_admin(event): return
        tags = db.list_tags()
        if not tags:
            await event.respond("Тегов пока нет.")
            return
        lines = [("🟢" if t["active"] else "🔴") + f" `{t['tag']}`" for t in tags]
        await event.respond("**Все теги:**\n" + "\n".join(lines), parse_mode="markdown")

    # /stats
    @bot.on(events.NewMessage(pattern=r"^/stats$"))
    async def _(event):
        if not _is_admin(event): return
        s = db.get_stats()
        await event.respond(
            "📊 **Статистика**\n\n"
            f"Спарсено всего: `{s.get('total_parsed', 0)}`\n"
            f"Ожидают проверки: `{s.get('pending', 0)}`\n"
            f"Опубликовано: `{s.get('published', 0)}`\n"
            f"Спам: `{s.get('total_spam', 0)}`\n"
            f"Плохой источник: `{s.get('total_bad_source', 0)}`\n"
            f"Пропущено: `{s.get('total_skipped', 0)}`\n",
            parse_mode="markdown"
        )

    # /status
    @bot.on(events.NewMessage(pattern=r"^/status$"))
    async def _(event):
        if not _is_admin(event): return
        tags   = db.get_active_tags()
        parser = "🔄 Работает" if State.search_running else "⚪ Ожидает"
        loop   = "⏸ Пауза" if State.paused else f"🟢 Авто (каждые {SEARCH_INTERVAL//60} мин)"
        await event.respond(
            "**Состояние системы**\n\n"
            f"Парсер: {parser}\n"
            f"Авто-поиск: {loop}\n"
            f"Последний запуск: `{State.last_run}`\n"
            f"Следующий запуск: `{State.next_run}`\n"
            f"Активных тегов: `{len(tags)}`\n",
            parse_mode="markdown"
        )

    # /pause
    @bot.on(events.NewMessage(pattern=r"^/pause$"))
    async def _(event):
        if not _is_admin(event): return
        State.paused = True
        State.next_run = "—"
        await event.respond("⏸ Авто-поиск приостановлен. `/resume` для возобновления.",
                            parse_mode="markdown")

    # /resume
    @bot.on(events.NewMessage(pattern=r"^/resume$"))
    async def _(event):
        if not _is_admin(event): return
        State.paused = False
        await event.respond("▶️ Авто-поиск возобновлён.", parse_mode="markdown")

    # /run_search  (manual)
    @bot.on(events.NewMessage(pattern=r"^/run_search$"))
    async def _(event):
        if not _is_admin(event): return
        if State.search_running:
            await event.respond("⚠️ Поиск уже запущен.")
            return
        await event.respond("🔍 Запускаю поиск вручную…")
        State.search_running = True
        from datetime import datetime
        State.last_run = datetime.utcnow().strftime("%H:%M:%S UTC")
        try:
            count = await run_search(user_client, bot, ADMIN_ID)
            await event.respond(f"✅ Готово. Новых постов: `{count}`", parse_mode="markdown")
        except Exception as e:
            log.exception("Manual search error: %s", e)
            await event.respond(f"❌ Ошибка: {e}")
        finally:
            State.search_running = False

    # Inline buttons
    @bot.on(events.CallbackQuery())
    async def _(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Нет доступа.", alert=True)
            return
        data = event.data.decode()
        if ":" not in data:
            return
        action, pid = data.split(":", 1)
        post_id = int(pid)
        MAP = {
            "pub":  ("published",  "✅ Опубликовано"),
            "spam": ("spam",       "🚫 Спам"),
            "bad":  ("bad_source", "❌ Плохой источник"),
            "skip": ("skipped",    "⏭ Пропущено"),
        }
        if action not in MAP:
            await event.answer("Неизвестное действие.")
            return
        status, label = MAP[action]
        db.update_status(post_id, status)
        orig = await event.get_message()
        await event.edit(orig.text + f"\n\n**→ {label}**", buttons=None, parse_mode="markdown")
        await event.answer(label)

    # Start background loop
    State.loop_task = asyncio.get_event_loop().create_task(
        _auto_loop(user_client, bot)
    )
    log.info("Background search loop scheduled every %d min", SEARCH_INTERVAL // 60)
