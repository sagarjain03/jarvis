"""Reminders and timers that survive restarts.

``parse_when`` turns "in 20 minutes" / "at 6:30 pm" / "tomorrow 9 am" into a
datetime; ``ReminderStore`` keeps them in a JSON file; a background thread
fires them via a callback.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

DEFAULT_PATH = Path.home() / ".openjarvis" / "jarvis_reminders.json"

_UNITS = {
    "s": "seconds", "sec": "seconds", "secs": "seconds",
    "second": "seconds", "seconds": "seconds",
    "m": "minutes", "min": "minutes", "mins": "minutes",
    "minute": "minutes", "minutes": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
}
_REL_PART = r"(\d+)\s*(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b"
_REL_RE = re.compile(rf"^(?:in\s+)?(?:{_REL_PART}\s*(?:and\s+)?)+$")
_ABS_RE = re.compile(
    r"^(?P<tom1>tomorrow\s+)?(?:at\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*"
    r"(?P<ampm>am|pm|a\.m\.|p\.m\.)?(?P<tom2>\s+tomorrow)?$"
)


class WhenError(ValueError):
    """The time could not be understood."""


def parse_when(text: str, now: datetime) -> datetime:
    t = " ".join(text.lower().split())
    if _REL_RE.match(t):
        delta = timedelta()
        for amount, unit in re.findall(_REL_PART, t):
            delta += timedelta(**{_UNITS[unit]: int(amount)})
        if delta.total_seconds() <= 0:
            raise WhenError("The time must be in the future.")
        return now + delta

    m = _ABS_RE.match(t)
    if not m:
        raise WhenError(f"I couldn't understand the time {text!r}.")
    hour, minute = int(m["h"]), int(m["m"] or 0)
    ampm = (m["ampm"] or "").replace(".", "")
    if minute > 59:
        raise WhenError(f"Invalid time {text!r}.")
    if ampm:
        if not 1 <= hour <= 12:
            raise WhenError(f"Invalid time {text!r}.")
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif hour > 23:
        raise WhenError(f"Invalid time {text!r}.")

    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if m["tom1"] or m["tom2"]:
        due += timedelta(days=1)
    elif due <= now:
        due += timedelta(days=1)
    return due


def describe(due: datetime, now: datetime) -> str:
    clock = due.strftime("%I:%M %p").lstrip("0")
    if due.date() == now.date():
        return clock
    if due.date() == now.date() + timedelta(days=1):
        return f"{clock} tomorrow"
    return due.strftime(f"{clock} on %d %B")


@dataclass
class Reminder:
    id: str
    due: str  # ISO datetime, local time
    message: str

    @property
    def due_at(self) -> datetime:
        return datetime.fromisoformat(self.due)


class ReminderStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._items: list[Reminder] = []
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
            self._items = [Reminder(**r) for r in raw]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([asdict(r) for r in self._items], indent=2), encoding="utf-8"
        )

    def add(self, due: datetime, message: str) -> str:
        with self._lock:
            rid = uuid.uuid4().hex[:6]
            self._items.append(Reminder(rid, due.isoformat(), message))
            self._save()
            return rid

    def pending(self) -> list[Reminder]:
        with self._lock:
            return sorted(self._items, key=lambda r: r.due_at)

    def cancel(self, rid: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [r for r in self._items if r.id != rid]
            if len(self._items) == before:
                return False
            self._save()
            return True

    def pop_due(self, now: datetime) -> list[Reminder]:
        with self._lock:
            due = [r for r in self._items if r.due_at <= now]
            if due:
                self._items = [r for r in self._items if r.due_at > now]
                self._save()
            return due


def start_reminder_thread(
    store: ReminderStore,
    on_fire: Callable[[Reminder], None],
    interval: float = 5.0,
) -> threading.Thread:
    """Check every few seconds and call ``on_fire`` for each due reminder."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            for r in store.pop_due(datetime.now()):
                try:
                    on_fire(r)
                except Exception:  # a failed alert must not stop later ones
                    pass

    thread = threading.Thread(target=loop, name="reminders", daemon=True)
    thread.start()
    return thread


class ReminderTool(BaseTool):
    tool_id = "reminders"

    def __init__(
        self, store: ReminderStore, now: Callable[[], datetime] = datetime.now
    ) -> None:
        self._store = store
        self._now = now

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="reminders",
            description=(
                "Set, list, or cancel reminders and timers. For 'set', 'when' is "
                "like 'in 20 minutes', 'in 1 hour 30 minutes', 'at 6:30 pm', or "
                "'tomorrow 9 am', and 'message' is what to remind about."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "list", "cancel"]},
                    "when": {"type": "string"},
                    "message": {"type": "string"},
                    "id": {"type": "string", "description": "Reminder id to cancel."},
                },
                "required": ["action"],
            },
            category="productivity",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="reminders", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action")
        now = self._now()
        if action == "set":
            message = str(params.get("message") or "").strip()
            if not message:
                return self._result("What should I remind you about?", False)
            try:
                due = parse_when(str(params.get("when") or ""), now)
            except WhenError as exc:
                return self._result(str(exc), False)
            self._store.add(due, message)
            return self._result(f"Reminder set for {describe(due, now)}: {message}.")
        if action == "list":
            items = self._store.pending()
            if not items:
                return self._result("You have no reminders.")
            return self._result(
                "; ".join(f"[{r.id}] {describe(r.due_at, now)}: {r.message}" for r in items)
            )
        if action == "cancel":
            if self._store.cancel(str(params.get("id") or "")):
                return self._result("Reminder cancelled.")
            return self._result("No reminder with that id.", False)
        return self._result(f"Unknown action {action!r}.", False)
