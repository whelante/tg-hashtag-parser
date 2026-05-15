import asyncio
import logging
import re
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Message, Channel, Chat

import database as db
from filters import should_pass

log = logging.getLogger(__name__)

SEARCH_LIMIT = 200   # messages per channel per tag


def _extract_tags(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"#\w+", text or "")]


def _post_link(chat, msg_id: int) -> str:
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{msg_id}"
    return f"tg://channel?id={chat.id}&post={msg_id}"


async def _send_to_admin(
    bot: TelegramClient,
    admin_id: int,
    post: dict,
    post_id: int,
):
    from telethon.tl.types import (
        ReplyInlineMarkup, KeyboardButtonRow, KeyboardButtonCallback
    )

    text     = (post.get("text") or "")
    preview  = text[:600] + ("…" if len(text) > 600 else "")
    ch_name  = post.get("channel_name") or "unknown"
    username = post.get("username") or ""
    hashtag  = post.get("hashtag") or ""
    link     = post.get("post_link") or ""
    pub      = post.get("published_at") or ""

    msg = (
        f"🔍 **New signal post**\n\n"
        f"📢 **Channel:** {ch_name}"
        + (f" (@{username})" if username else "") + "\n"
        f"🏷 **Tag:** `{hashtag}`\n"
        f"🕐 **Published:** {pub[:19].replace('T',' ')}\n"
        f"🔗 **Link:** {link}\n\n"
        f"📝 **Text:**\n{preview}"
    )

    buttons = ReplyInlineMarkup(rows=[
        KeyboardButtonRow(buttons=[
            KeyboardButtonCallback(text="✅ Publish",     data=f"pub:{post_id}".encode()),
            KeyboardButtonCallback(text="🚫 Spam",       data=f"spam:{post_id}".encode()),
            KeyboardButtonCallback(text="❌ Bad source", data=f"bad:{post_id}".encode()),
            KeyboardButtonCallback(text="⏭ Skip",        data=f"skip:{post_id}".encode()),
        ])
    ])

    await bot.send_message(admin_id, msg, buttons=buttons, parse_mode="markdown")
    log.debug("Sent post %d to admin", post_id)


async def run_search(
    user_client: TelegramClient,
    bot: TelegramClient,
    admin_id: int,
) -> int:
    tags = db.get_active_tags()
    if not tags:
        log.warning("No active tags in DB")
        return 0

    log.info("=== Search start: %d tags ===", len(tags))
    total_new = 0

    for tag in tags:
        log.info("[%s] Searching public channels…", tag)
        try:
            result = await user_client(SearchRequest(q=tag, limit=20))
            chats = getattr(result, "chats", [])
            log.info("[%s] Found %d chats", tag, len(chats))
        except FloodWaitError as e:
            log.warning("[%s] FloodWait %ds — skipping tag", tag, e.seconds)
            await asyncio.sleep(e.seconds + 2)
            continue
        except Exception as e:
            log.error("[%s] Search error: %s", tag, e)
            continue

        for chat in chats:
            if not isinstance(chat, (Channel, Chat)):
                continue

            ch_name  = getattr(chat, "title", "") or ""
            username = getattr(chat, "username", "") or ""
            log.debug("[%s] Scanning channel: %s (@%s)", tag, ch_name, username)

            try:
                scanned = 0
                async for msg in user_client.iter_messages(
                    chat,
                    limit=SEARCH_LIMIT,
                    search=tag,
                ):
                    if not isinstance(msg, Message) or not msg.text:
                        continue

                    scanned += 1
                    msg_tags = _extract_tags(msg.text)

                    # Must contain the tag we're searching
                    if tag not in msg_tags:
                        log.debug("Tag %s not in message tags %s — skip", tag, msg_tags)
                        continue

                    ok, reason = should_pass(msg.text)
                    if not ok:
                        log.debug("Filtered (%s): %s…", reason, msg.text[:60])
                        continue

                    pub_at = ""
                    if msg.date:
                        pub_at = msg.date.astimezone(timezone.utc).isoformat()

                    post_id = db.save_post(
                        channel_id   = chat.id,
                        channel_name = ch_name,
                        username     = username,
                        message_id   = msg.id,
                        post_link    = _post_link(chat, msg.id),
                        published_at = pub_at,
                        hashtag      = tag,
                        text         = msg.text,
                    )

                    if post_id:
                        total_new += 1
                        post = db.get_post(post_id)
                        if post:
                            try:
                                await _send_to_admin(bot, admin_id, post, post_id)
                                await asyncio.sleep(0.5)
                            except Exception as e:
                                log.error("Failed to send post %d to admin: %s", post_id, e)

                log.info("[%s] @%s — scanned %d msgs", tag, username or chat.id, scanned)

            except ChannelPrivateError:
                log.debug("[%s] Channel %s is private — skip", tag, ch_name)
            except FloodWaitError as e:
                log.warning("[%s] FloodWait %ds in %s", tag, e.seconds, ch_name)
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                log.error("[%s] Error in %s: %s", tag, ch_name, e)

            await asyncio.sleep(1)

        await asyncio.sleep(2)

    log.info("=== Search done. New posts: %d ===", total_new)
    return total_new
