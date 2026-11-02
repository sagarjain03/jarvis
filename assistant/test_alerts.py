"""Tests for proactive alerts: battery, upcoming meetings, evening summary."""

from datetime import datetime, timedelta, timezone

from alerts import BatteryWatch, DailyAt, MeetingWatch, evening_summary
from calendar_tool import Event

IST = timezone(timedelta(hours=5, minutes=30))


def at(h, m=0, day=2):
    return datetime(2026, 11, day, h, m, tzinfo=IST)


# --- battery ----------------------------------------------------------------

def test_battery_alerts_once_when_low_and_unplugged():
    w = BatteryWatch(low=20)
    assert w.check(50, plugged=False) is None
    assert "19%" in w.check(19, plugged=False)
    assert w.check(15, plugged=False) is None  # not again


def test_battery_rearms_after_charging():
    w = BatteryWatch(low=20)
    w.check(19, plugged=False)
    w.check(19, plugged=True)  # charger in
    assert w.check(18, plugged=False) is not None


def test_battery_plugged_or_unknown_is_quiet():
    w = BatteryWatch(low=20)
    assert w.check(10, plugged=True) is None
    assert w.check(None, plugged=None) is None  # desktop PC, no battery


# --- meetings -------------------------------------------------------------------

def test_meeting_announced_once_about_ten_minutes_before():
    w = MeetingWatch(lead_minutes=10)
    standup = Event(at(10, 0), "Standup", False)
    assert w.check([standup], at(9, 40)) == []
    assert w.check([standup], at(9, 51)) == ["Standup starts in 9 minutes."]
    assert w.check([standup], at(9, 52)) == []


def test_meeting_ignores_all_day_and_past_events():
    w = MeetingWatch(lead_minutes=10)
    events = [Event(at(0), "Birthday", True), Event(at(9, 0), "Old", False)]
    assert w.check(events, at(9, 55)) == []


def test_meeting_starting_now():
    w = MeetingWatch(lead_minutes=10)
    assert w.check([Event(at(10, 0), "Demo", False)], at(10, 0)) == ["Demo starts now."]


# --- evening summary --------------------------------------------------------------

def test_daily_at_fires_once_per_day_within_window():
    d = DailyAt("21:00")
    assert not d.due(at(20, 59))
    assert d.due(at(21, 0))
    assert not d.due(at(21, 5))
    assert not d.due(at(23, 0))  # started Jarvis late: too long after, skip
    assert d.due(at(21, 1, day=3))


def test_evening_summary_text():
    tomorrow = [Event(at(10, day=3), "Standup", False)]
    text = evening_summary(["buy milk", "call Rahul"], tomorrow)
    assert text == ("Good evening, Master. You have 2 open to-dos: buy milk; call Rahul. "
                    "Tomorrow: 10:00 AM Standup.")
    assert evening_summary([], []) == "Good evening, Master. Your to-do list is clear. Tomorrow: no events."
