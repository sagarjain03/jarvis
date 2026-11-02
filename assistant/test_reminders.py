"""Tests for reminders: time parsing, storage, and the tool. Nothing fires."""

from datetime import datetime, timedelta

import pytest

from reminders import ReminderStore, ReminderTool, WhenError, parse_when

NOW = datetime(2026, 10, 31, 16, 0)  # Saturday 4:00 PM


@pytest.mark.parametrize(
    "text, expected",
    [
        ("in 20 minutes", NOW + timedelta(minutes=20)),
        ("in 1 minute", NOW + timedelta(minutes=1)),
        ("in 2 hours", NOW + timedelta(hours=2)),
        ("in 90 seconds", NOW + timedelta(seconds=90)),
        ("20 min", NOW + timedelta(minutes=20)),
        ("in 1 hour 30 minutes", NOW + timedelta(hours=1, minutes=30)),
        ("at 6:30 pm", datetime(2026, 10, 31, 18, 30)),
        ("at 6 pm", datetime(2026, 10, 31, 18, 0)),
        ("at 18:45", datetime(2026, 10, 31, 18, 45)),
        ("at 9 am", datetime(2026, 11, 1, 9, 0)),  # already past today
        ("tomorrow 9 am", datetime(2026, 11, 1, 9, 0)),
        ("tomorrow at 7:15 pm", datetime(2026, 11, 1, 19, 15)),
    ],
)
def test_parse_when(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["", "someday", "in minus 5 minutes", "at 25:00", "at 13 pm"])
def test_parse_when_rejects_unclear_times(text):
    with pytest.raises(WhenError):
        parse_when(text, NOW)


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "r.json"
    store = ReminderStore(path)
    rid = store.add(NOW + timedelta(minutes=5), "drink water")
    again = ReminderStore(path)
    assert [(r.id, r.message) for r in again.pending()] == [(rid, "drink water")]


def test_pop_due_returns_only_due_and_removes_them(tmp_path):
    store = ReminderStore(tmp_path / "r.json")
    store.add(NOW + timedelta(minutes=1), "soon")
    store.add(NOW + timedelta(hours=1), "later")
    due = store.pop_due(NOW + timedelta(minutes=2))
    assert [r.message for r in due] == ["soon"]
    assert [r.message for r in store.pending()] == ["later"]
    assert [r.message for r in ReminderStore(tmp_path / "r.json").pending()] == ["later"]


def test_cancel(tmp_path):
    store = ReminderStore(tmp_path / "r.json")
    rid = store.add(NOW + timedelta(minutes=1), "x")
    assert store.cancel(rid) is True
    assert store.cancel(rid) is False
    assert store.pending() == []


def test_tool_sets_lists_and_cancels(tmp_path):
    store = ReminderStore(tmp_path / "r.json")
    tool = ReminderTool(store, now=lambda: NOW)
    r = tool.execute(action="set", when="in 20 minutes", message="call mom")
    assert r.success and "4:20 PM" in r.content
    listed = tool.execute(action="list")
    assert "call mom" in listed.content
    rid = store.pending()[0].id
    assert tool.execute(action="cancel", id=rid).success
    assert "no reminders" in tool.execute(action="list").content.lower()


def test_tool_reports_bad_time_without_saving(tmp_path):
    store = ReminderStore(tmp_path / "r.json")
    r = ReminderTool(store, now=lambda: NOW).execute(action="set", when="someday", message="x")
    assert r.success is False
    assert store.pending() == []


def test_tool_requires_message(tmp_path):
    store = ReminderStore(tmp_path / "r.json")
    r = ReminderTool(store, now=lambda: NOW).execute(action="set", when="in 5 minutes", message=" ")
    assert r.success is False
