"""Tests for the Telegram message handler. No network."""

from dataclasses import dataclass

import pytest

from telegram_bot import allowed_ids, make_handler


@dataclass
class Msg:
    content: str
    conversation_id: str


def _run_now(fn):
    fn()


@pytest.fixture
def sent():
    return []


def _handler(sent, allowed, replies=None):
    replies = replies if replies is not None else []

    def brain_reply(text):
        replies.append(text)
        return f"reply to {text}"

    return make_handler(brain_reply, lambda chat, text: sent.append((chat, text)), allowed, spawn=_run_now), replies


def test_allowed_chat_gets_brain_reply(sent):
    handle, replies = _handler(sent, {"111"})
    handle(Msg("what time is it", "111"))
    assert replies == ["what time is it"]
    assert sent == [("111", "reply to what time is it")]


def test_other_chats_are_ignored(sent):
    handle, replies = _handler(sent, {"111"})
    handle(Msg("shutdown", "999"))
    assert replies == []
    assert sent == []


def test_setup_mode_only_reveals_chat_id(sent):
    handle, replies = _handler(sent, set())
    handle(Msg("open youtube", "555"))
    assert replies == []
    assert len(sent) == 1 and sent[0][0] == "555"
    assert "555" in sent[0][1] and "TELEGRAM_ALLOWED_CHAT_ID" in sent[0][1]


def test_blank_messages_ignored(sent):
    handle, replies = _handler(sent, {"111"})
    handle(Msg("   ", "111"))
    assert replies == [] and sent == []


@pytest.mark.parametrize(
    "raw, ids",
    [("", set()), ("123", {"123"}), (" 123 , -456 ", {"123", "-456"}), ("abc", set())],
)
def test_allowed_ids_parsing(raw, ids):
    assert allowed_ids(raw) == ids
