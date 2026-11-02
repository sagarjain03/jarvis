"""Tests for reading the user's calendar from a private ICS link. No network."""

from datetime import date, datetime, timedelta, timezone

from calendar_tool import CalendarTool, events_between, speak_events

IST = timezone(timedelta(hours=5, minutes=30))

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:1
SUMMARY:Team standup
DTSTART:20261102T043000Z
DTEND:20261102T044500Z
RRULE:FREQ=DAILY;COUNT=5
END:VEVENT
BEGIN:VEVENT
UID:2
SUMMARY:Dentist
DTSTART:20261103T090000Z
DTEND:20261103T100000Z
END:VEVENT
BEGIN:VEVENT
UID:3
SUMMARY:Mom's birthday
DTSTART;VALUE=DATE:20261102
DTEND;VALUE=DATE:20261103
END:VEVENT
END:VCALENDAR
"""


def day(y, m, d):
    start = datetime(y, m, d, tzinfo=IST)
    return start, start + timedelta(days=1)


def test_events_today_in_local_time_sorted_all_day_first():
    events = events_between(ICS, *day(2026, 11, 2), tz=IST)
    assert [(e.summary, e.all_day) for e in events] == [("Mom's birthday", True), ("Team standup", False)]
    assert events[1].start == datetime(2026, 11, 2, 10, 0, tzinfo=IST)  # 04:30 UTC = 10:00 IST


def test_recurring_event_repeats_and_ends():
    assert [e.summary for e in events_between(ICS, *day(2026, 11, 3), tz=IST)] == ["Team standup", "Dentist"]
    assert events_between(ICS, *day(2026, 11, 10), tz=IST) == []


def test_speak_events():
    events = events_between(ICS, *day(2026, 11, 3), tz=IST)
    assert speak_events(events, "Tomorrow") == "Tomorrow: 10:00 AM Team standup; 2:30 PM Dentist."
    assert speak_events([], "Today") == "Today: no events."


def test_tool_today_tomorrow_week():
    now = datetime(2026, 11, 2, 8, 0, tzinfo=IST)
    tool = CalendarTool(url="https://x/private.ics", fetch=lambda url: ICS, now=lambda: now)
    assert "Team standup" in tool.execute(day="today").content
    assert "Dentist" in tool.execute(day="tomorrow").content
    week = tool.execute(day="week").content
    assert "Dentist" in week and "Tue" in week


def test_tool_not_set_up_or_fetch_failure():
    assert "not set up" in CalendarTool(url="", fetch=None).execute(day="today").content

    def fail(url):
        raise OSError("offline")

    r = CalendarTool(url="https://x/private.ics", fetch=fail).execute(day="today")
    assert not r.success and "private.ics" not in r.content  # never reveal the secret link


def test_multi_day_range():
    events = events_between(ICS, datetime(2026, 11, 2, tzinfo=IST), datetime(2026, 11, 4, tzinfo=IST), tz=IST)
    assert {e.start.date() for e in events} == {date(2026, 11, 2), date(2026, 11, 3)}


def test_feed_caches_the_calendar_for_ten_minutes():
    from calendar_tool import CalendarFeed

    clock, fetches = [0.0], []
    feed = CalendarFeed("https://x/private.ics", fetch=lambda u: fetches.append(u) or ICS,
                        now=lambda: clock[0], ttl=600)
    start, end = day(2026, 11, 2)
    assert [e.summary for e in feed.events(start, end)] == ["Mom's birthday", "Team standup"]
    clock[0] = 300
    feed.events(start, end)
    assert len(fetches) == 1
    clock[0] = 601
    feed.events(start, end)
    assert len(fetches) == 2


def test_feed_without_link_or_network_is_empty():
    from calendar_tool import CalendarFeed

    def fail(url):
        raise OSError("offline")

    start, end = day(2026, 11, 2)
    assert CalendarFeed("", fetch=fail).events(start, end) == []
    assert CalendarFeed("https://x", fetch=fail).events(start, end) == []
