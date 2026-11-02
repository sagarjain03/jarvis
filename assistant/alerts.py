"""Proactive alerts: low battery, a meeting about to start, the evening summary.

Each watcher is pure (fed readings, returns what to say) so it's testable;
``start_alert_thread`` polls them once a minute.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Callable

from calendar_tool import Event, speak_events


class BatteryWatch:
    """Warns once when the battery runs low on battery power; re-arms on charge."""

    def __init__(self, low: int = 20) -> None:
        self._low = low
        self._armed = True

    def check(self, percent: float | None, plugged: bool | None) -> str | None:
        if percent is None:
            return None  # no battery (desktop PC)
        if plugged:
            self._armed = True
            return None
        if percent < self._low and self._armed:
            self._armed = False
            return f"Battery is at {percent:.0f}%. Please plug in the charger, Master."
        return None


class MeetingWatch:
    """Announces each timed event once, within ``lead_minutes`` of its start."""

    def __init__(self, lead_minutes: int = 10) -> None:
        self._lead = timedelta(minutes=lead_minutes)
        self._announced: set[tuple[str, datetime]] = set()

    def check(self, events: list[Event], now: datetime) -> list[str]:
        messages = []
        for e in events:
            key = (e.summary, e.start)
            left = e.start - now
            if e.all_day or key in self._announced or not timedelta(0) <= left <= self._lead:
                continue
            self._announced.add(key)
            minutes = int(left.total_seconds() // 60)
            messages.append(f"{e.summary} starts now." if minutes == 0 else f"{e.summary} starts in {minutes} minutes.")
        return messages


class DailyAt:
    """True once a day at ``hhmm`` (within a 30-minute window, so a late start skips it)."""

    def __init__(self, hhmm: str, window_minutes: int = 30) -> None:
        h, m = map(int, hhmm.split(":"))
        self._at = dtime(h, m)
        self._window = timedelta(minutes=window_minutes)
        self._last_day = None

    def due(self, now: datetime) -> bool:
        start = datetime.combine(now.date(), self._at, tzinfo=now.tzinfo)
        if self._last_day == now.date() or not start <= now < start + self._window:
            return False
        self._last_day = now.date()
        return True


def evening_summary(open_todos: list[str], tomorrow: list[Event]) -> str:
    if open_todos:
        todo = f"You have {len(open_todos)} open to-dos: {'; '.join(open_todos)}."
    else:
        todo = "Your to-do list is clear."
    return f"Good evening, Master. {todo} {speak_events(tomorrow, 'Tomorrow')}"


def start_alert_thread(
    check: Callable[[], list[str]],
    on_alert: Callable[[str], None],
    interval: float = 60.0,
) -> threading.Thread:
    def loop() -> None:
        while True:
            try:
                messages = check()
            except Exception:  # a failed check (no network...) just skips a round
                messages = []
            for message in messages:
                try:
                    on_alert(message)
                except Exception:
                    pass
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="alerts", daemon=True)
    thread.start()
    return thread
