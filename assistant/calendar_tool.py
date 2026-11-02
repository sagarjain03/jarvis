"""Read-only Google Calendar via its private iCal link.

Google Calendar → Settings → your calendar → "Secret address in iCal format".
Save it as the GOOGLE_CALENDAR_ICS_URL environment variable; it is a password,
so it's never printed or spoken.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Callable

import httpx
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@dataclass(frozen=True)
class Event:
    start: datetime  # local time
    summary: str
    all_day: bool


def events_between(ics_text: str, start: datetime, end: datetime, tz: tzinfo) -> list[Event]:
    """Events (recurring ones expanded) in [start, end), in local time."""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics_text)
    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        dt = comp["DTSTART"].dt
        summary = str(comp.get("SUMMARY", "Untitled event"))
        if isinstance(dt, datetime):
            if dt.tzinfo is None:  # "floating" time: already local
                dt = dt.replace(tzinfo=tz)
            events.append(Event(dt.astimezone(tz), summary, False))
        else:
            events.append(Event(datetime(dt.year, dt.month, dt.day, tzinfo=tz), summary, True))
    return sorted(events, key=lambda e: (e.start.date(), not e.all_day, e.start))


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def speak_events(events: list[Event], label: str) -> str:
    if not events:
        return f"{label}: no events."
    parts = [f"all day {e.summary}" if e.all_day else f"{_clock(e.start)} {e.summary}" for e in events]
    return f"{label}: {'; '.join(parts)}."


def _fetch(url: str) -> str:
    r = httpx.get(url, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text


class CalendarTool(BaseTool):
    tool_id = "calendar"

    def __init__(
        self,
        url: str | None = None,
        fetch: Callable[[str], str] = _fetch,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._url = (os.environ.get("GOOGLE_CALENDAR_ICS_URL", "") if url is None else url).strip()
        self._fetch = fetch
        self._now = now

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calendar",
            description="Read the user's Google Calendar: events today, tomorrow, or this week.",
            parameters={
                "type": "object",
                "properties": {"day": {"type": "string", "enum": ["today", "tomorrow", "week"]}},
                "required": ["day"],
            },
            category="productivity",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="calendar", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        if not self._url:
            return self._result("The calendar is not set up (GOOGLE_CALENDAR_ICS_URL).", False)
        now = self._now()
        tz = now.tzinfo
        midnight = datetime.combine(now.date(), datetime.min.time(), tzinfo=tz)
        day = params.get("day", "today")
        try:
            ics = self._fetch(self._url)
            if day == "week":
                events = events_between(ics, midnight, midnight + timedelta(days=7), tz)
                return self._result(self._week(events))
            offset = 1 if day == "tomorrow" else 0
            start = midnight + timedelta(days=offset)
            events = events_between(ics, start, start + timedelta(days=1), tz)
        except Exception:  # network or a malformed calendar; never echo the secret URL
            return self._result("Couldn't reach your calendar right now.", False)
        return self._result(speak_events(events, "Tomorrow" if offset else "Today"))

    @staticmethod
    def _week(events: list[Event]) -> str:
        if not events:
            return "This week: no events."
        days: dict[date, list[Event]] = {}
        for e in events:
            days.setdefault(e.start.date(), []).append(e)
        return " ".join(speak_events(evs, d.strftime("%a %d %b")) for d, evs in days.items())


class CalendarFeed:
    """Calendar events for background checks, re-downloaded at most every ``ttl`` s."""

    def __init__(
        self,
        url: str | None = None,
        fetch: Callable[[str], str] = _fetch,
        now: Callable[[], float] = time.monotonic,
        ttl: float = 600,
    ) -> None:
        self._url = (os.environ.get("GOOGLE_CALENDAR_ICS_URL", "") if url is None else url).strip()
        self._fetch = fetch
        self._now = now
        self._ttl = ttl
        self._ics = ""
        self._fetched_at: float | None = None

    def events(self, start: datetime, end: datetime) -> list[Event]:
        if not self._url:
            return []
        if self._fetched_at is None or self._now() - self._fetched_at > self._ttl:
            try:
                self._ics = self._fetch(self._url)
            except Exception:
                return []  # offline: try again next check
            self._fetched_at = self._now()
        return events_between(self._ics, start, end, start.tzinfo)
