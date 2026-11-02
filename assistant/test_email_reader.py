"""Tests for the read-only email tool. No network; fetching is faked."""

from datetime import datetime

import pytest

from email_reader import EmailReaderTool, Mail, search_criteria, speakable


def test_search_criteria_unread_default():
    assert search_criteria(unread_only=True, sender="") == ["UNSEEN"]


def test_search_criteria_all():
    assert search_criteria(unread_only=False, sender="") == ["ALL"]


def test_search_criteria_with_sender_is_quoted():
    assert search_criteria(unread_only=True, sender="Amazon") == ["UNSEEN", "FROM", '"Amazon"']


@pytest.mark.parametrize("sender", ['amazon" OR ALL', "a)b", "x\r\nDELETE"])
def test_search_criteria_rejects_imap_injection(sender):
    with pytest.raises(ValueError):
        search_criteria(unread_only=True, sender=sender)


def _mail(sender="Amazon <ship@amazon.in>", subject="Your order shipped", body="Hello,\n\nYour package is on the way and arrives Monday."):
    return Mail(sender=sender, subject=subject, date=datetime(2026, 10, 31, 9, 5), body=body)


def test_speakable_uses_display_name_and_short_snippet():
    text = speakable([_mail(body="word " * 100)])
    assert text.startswith("1. From Amazon: Your order shipped")
    assert "ship@amazon.in" not in text
    assert len(text) < 260


def test_speakable_empty():
    assert speakable([]) == "No matching emails."


def test_tool_without_credentials_explains_setup(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    r = EmailReaderTool(fetch=lambda *a: pytest.fail("must not fetch")).execute()
    assert r.success is False
    assert "GMAIL_APP_PASSWORD" in r.content


def test_tool_fetches_with_clamped_count(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    calls = []

    def fake_fetch(address, password, criteria, count):
        calls.append((address, password, criteria, count))
        return [_mail()]

    r = EmailReaderTool(fetch=fake_fetch).execute(count=50, unread_only=False, sender="amazon")
    assert r.success
    assert "Your order shipped" in r.content
    assert calls == [("me@gmail.com", "abcdefghijklmnop", ["ALL", "FROM", '"amazon"'], 10)]


def test_tool_reports_login_failure_without_leaking_password(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secretpass")

    def failing(*a):
        raise OSError("LOGIN failed for secretpass")

    r = EmailReaderTool(fetch=failing).execute()
    assert r.success is False
    assert "secretpass" not in r.content
