"""Control Jarvis from your phone through a Telegram bot.

Env vars (set by the user):
  TELEGRAM_BOT_TOKEN        from @BotFather
  TELEGRAM_ALLOWED_CHAT_ID  your chat id; until set, the bot only tells
                            whoever messages it their chat id and does nothing else.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Callable

_CHAT_ID = re.compile(r"^-?\d+$")


def allowed_ids(raw: str) -> set[str]:
    return {c.strip() for c in raw.split(",") if _CHAT_ID.match(c.strip())}


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="telegram-reply", daemon=True).start()


def make_handler(
    brain_reply: Callable[[str], str],
    send: Callable[[str, str], Any],
    allowed: set[str],
    spawn: Callable[[Callable[[], None]], None] = _spawn,
) -> Callable[[Any], None]:
    """Build the per-message callback. Only ``allowed`` chats reach the brain."""

    def handle(msg: Any) -> None:
        chat = str(msg.conversation_id)
        if not allowed:
            send(chat, (
                f"Your chat ID is {chat}. Set the environment variable "
                f"TELEGRAM_ALLOWED_CHAT_ID={chat} on your PC and restart Jarvis."
            ))
            return
        if chat not in allowed:
            return
        text = (msg.content or "").strip()
        if not text:
            return
        spawn(lambda: send(chat, brain_reply(text)))

    return handle


def start_telegram(brain_reply: Callable[[str], str]) -> tuple[Any, set[str]] | None:
    """Start polling if a bot token is set. Returns (channel, allowed ids)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    from openjarvis.channels.telegram import TelegramChannel

    allowed = allowed_ids(os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", ""))
    channel = TelegramChannel(
        token,
        # Setup mode passes no allow-list so the handler can reply with the id.
        allowed_chat_ids=",".join(sorted(allowed)),
        parse_mode="",  # plain text; model replies aren't Telegram Markdown
    )
    channel.on_message(make_handler(brain_reply, lambda c, t: channel.send(c, t), allowed))
    channel.connect()
    return channel, allowed
