"""Safe PC control for Jarvis: a fixed set of actions, no arbitrary commands.

``plan()`` turns a request into one allowed ``Plan`` (or raises ``PlanError``);
``_run()`` is the only code that touches the system.
"""

from __future__ import annotations

import ctypes
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

import httpx
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

ACTIONS = (
    "open_website", "search_google", "search_youtube", "play_youtube",
    "search_gmail", "ask_chatgpt", "ask_claude", "get_weather", "open_app",
    "volume_up", "volume_down", "mute",
    "play_pause", "next_track", "previous_track",
    "screenshot", "lock_screen", "get_time", "get_battery",
)

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "mail": "https://mail.google.com",
    "email": "https://mail.google.com",
    "claude": "https://claude.ai",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "chatgpt": "https://chatgpt.com",
    "wikipedia": "https://www.wikipedia.org",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.in",
}

# Spoken name -> what Windows is asked to open. Nothing outside this list runs.
APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "settings": "ms-settings:",
    "task manager": "taskmgr.exe",
    "camera": "microsoft.windows.camera:",
    "edge": "msedge.exe",
    "chrome": "chrome.exe",
    "spotify": "spotify:",
}

# Windows virtual-key codes.
_VK = {
    "volume_up": [0xAF] * 5,  # each press is ~2%
    "volume_down": [0xAE] * 5,
    "mute": [0xAD],
    "play_pause": [0xB3],
    "next_track": [0xB0],
    "previous_track": [0xB1],
}
_VK_LWIN, _VK_SNAPSHOT, _KEYUP = 0x5B, 0x2C, 0x0002

_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)


class PlanError(ValueError):
    """The request is not one of the allowed actions."""


@dataclass(frozen=True)
class Plan:
    kind: str  # open_url | open_app | keys | lock | info
    payload: str


def _website_url(target: str) -> str:
    t = target.strip()
    if t.lower() in SITES:
        return SITES[t.lower()]
    if "://" in t:
        parts = urlsplit(t)
        if parts.scheme.lower() in ("http", "https") and parts.netloc:
            return t
        raise PlanError(f"Only http/https websites can be opened, not {t!r}.")
    if _DOMAIN_RE.match(t):
        return f"https://{t}"
    raise PlanError(f"{t!r} is not a website address.")


def plan(action: str, target: str = "") -> Plan:
    target = (target or "").strip()
    if action == "open_website":
        return Plan("open_url", _website_url(target))
    if action in ("search_google", "search_youtube"):
        if not target:
            raise PlanError("Say what to search for.")
        if action == "search_google":
            return Plan("open_url", f"https://www.google.com/search?q={quote_plus(target)}")
        return Plan(
            "open_url",
            f"https://www.youtube.com/results?search_query={quote_plus(target)}",
        )
    if action in ("play_youtube", "search_gmail", "ask_chatgpt", "ask_claude"):
        if not target:
            raise PlanError("Say what you want.")
        if action == "play_youtube":
            return Plan("youtube_play", target)
        if action == "search_gmail":
            return Plan("open_url", f"https://mail.google.com/mail/u/0/#search/{quote(target)}")
        if action == "ask_chatgpt":
            return Plan("open_url", f"https://chatgpt.com/?q={quote_plus(target)}")
        return Plan("open_url", f"https://claude.ai/new?q={quote_plus(target)}")
    if action == "get_weather":
        return Plan("weather", target)
    if action == "open_app":
        app = APPS.get(target.lower())
        if app is None:
            raise PlanError(
                f"I can only open these apps: {', '.join(sorted(APPS))}."
            )
        return Plan("open_app", app)
    if action in _VK or action == "screenshot":
        return Plan("keys", action)
    if action == "lock_screen":
        return Plan("lock", "")
    if action in ("get_time", "get_battery"):
        return Plan("info", action)
    raise PlanError(f"Unknown action {action!r}.")


_UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"}
_VIDEO_ID_RE = re.compile(r'"videoId":"([\w-]{11})"')


def _fetch_youtube_results(query: str) -> str:
    r = httpx.get(
        "https://www.youtube.com/results",
        params={"search_query": query},
        headers=_UA,
        timeout=15,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.text


def first_youtube_video(query: str, fetch=_fetch_youtube_results) -> str:
    """URL of the top search result, or the results page if none is found."""
    match = _VIDEO_ID_RE.search(fetch(query))
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def format_weather(data: dict) -> str:
    now = data["current_condition"][0]
    area = data["nearest_area"][0]["areaName"][0]["value"]
    return (
        f"Weather in {area}: {now['weatherDesc'][0]['value']}, {now['temp_C']}°C "
        f"(feels like {now['FeelsLikeC']}°C), humidity {now['humidity']}%."
    )


def _tap(*codes: int) -> None:
    user32 = ctypes.windll.user32
    for c in codes:
        user32.keybd_event(c, 0, 0, 0)
    for c in reversed(codes):
        user32.keybd_event(c, 0, _KEYUP, 0)


def _run(p: Plan) -> str:
    if p.kind in ("open_url", "open_app"):
        os.startfile(p.payload)  # noqa: S606 - payload comes only from plan()
        return f"Opened {p.payload}."
    if p.kind == "youtube_play":
        url = first_youtube_video(p.payload)
        os.startfile(url)  # noqa: S606 - always a youtube.com URL
        return f"Playing the top YouTube result for {p.payload!r}."
    if p.kind == "weather":
        # wttr.in: keyless; an empty city means "where this PC is".
        r = httpx.get(
            f"https://wttr.in/{quote(p.payload)}",
            params={"format": "j1"},
            headers={"User-Agent": "curl/8"},
            timeout=15,
        )
        r.raise_for_status()
        return format_weather(r.json())
    if p.kind == "keys":
        if p.payload == "screenshot":
            _tap(_VK_LWIN, _VK_SNAPSHOT)
            return "Screenshot saved to Pictures\\Screenshots."
        for code in _VK[p.payload]:
            _tap(code)
            time.sleep(0.02)
        return f"Done: {p.payload.replace('_', ' ')}."
    if p.kind == "lock":
        ctypes.windll.user32.LockWorkStation()
        return "Screen locked."
    if p.payload == "get_time":
        return datetime.now().strftime("It is %I:%M %p on %A, %d %B %Y.")
    import psutil

    battery = psutil.sensors_battery()
    if battery is None:
        return "No battery found on this device."
    state = "charging" if battery.power_plugged else "not charging"
    return f"Battery is at {battery.percent:.0f}% and {state}."


class PcControlTool(BaseTool):
    tool_id = "pc_control"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="pc_control",
            description=(
                "Control the user's Windows PC. Actions: open a website or a known "
                "app; search Google or YouTube; play_youtube plays a specific "
                "video or song (target = what to play); open Gmail (open_website "
                "'gmail') or search_gmail for specific emails; ask_chatgpt / "
                "ask_claude open that chatbot with the user's prompt; get_weather "
                "(target = city, empty = current location); change volume; "
                "control media playback; take a screenshot; lock the screen; "
                f"tell the time or battery level. Known apps: {', '.join(sorted(APPS))}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "target": {
                        "type": "string",
                        "description": (
                            "Website (e.g. youtube.com), app name, or search "
                            "query. Empty for other actions."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="system",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            p = plan(str(params.get("action", "")), str(params.get("target", "") or ""))
        except PlanError as exc:
            return ToolResult(tool_name="pc_control", content=str(exc), success=False)
        try:
            return ToolResult(tool_name="pc_control", content=_run(p))
        except (OSError, httpx.HTTPError, KeyError, ValueError) as exc:
            return ToolResult(
                tool_name="pc_control", content=f"Failed: {exc}", success=False
            )
