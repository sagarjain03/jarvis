"""Safe PC control for Jarvis: a fixed set of actions, no arbitrary commands.

``plan()`` turns a request into one allowed ``Plan`` (or raises ``PlanError``);
``_run()`` is the only code that touches the system.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
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
    "open_folder", "type_text", "close_window",
    "set_brightness", "brightness_up", "brightness_down",
    "shutdown", "restart", "sleep", "confirm_power",
)

# Known folders, opened through Windows shell names (follows OneDrive redirects).
FOLDERS = {
    "downloads": "shell:Downloads",
    "documents": "shell:Personal",
    "desktop": "shell:Desktop",
    "pictures": "shell:My Pictures",
    "photos": "shell:My Pictures",
    "music": "shell:My Music",
    "videos": "shell:My Video",
}
MAX_TYPE_CHARS = 500
POWER_ACTIONS = ("shutdown", "restart", "sleep")
POWER_CONFIRM_SECONDS = 30.0

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
_VK_LWIN, _VK_SNAPSHOT, _VK_MENU, _VK_F4, _KEYUP = 0x5B, 0x2C, 0x12, 0x73, 0x0002

_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)


class PlanError(ValueError):
    """The request is not one of the allowed actions."""


@dataclass(frozen=True)
class Plan:
    # open_url | open_app | keys | lock | info | youtube_play | weather |
    # type | brightness | power_request | power_confirm
    kind: str
    payload: str


class PowerGate:
    """Shutdown/restart/sleep need a request, then a confirm in a LATER turn.

    ``new_turn()`` is called once per user message, so a model that calls both
    the request and the confirm while answering one message is refused.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._turn = 0
        self._pending: tuple[str, int, float] | None = None  # kind, turn, time

    def new_turn(self) -> None:
        self._turn += 1

    def request(self, kind: str) -> None:
        self._pending = (kind, self._turn, self._now())

    def confirm(self) -> str | None:
        if self._pending is None:
            return None
        kind, turn, at = self._pending
        if turn == self._turn:
            return None  # the user hasn't answered yet
        self._pending = None
        if self._now() - at > POWER_CONFIRM_SECONDS:
            return None
        return kind


POWER_GATE = PowerGate()


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
    if action == "open_folder":
        folder = FOLDERS.get(target.lower())
        if folder is None:
            raise PlanError(f"I can only open these folders: {', '.join(sorted(FOLDERS))}.")
        return Plan("open_app", folder)
    if action == "type_text":
        if not target or len(target) > MAX_TYPE_CHARS:
            raise PlanError(f"Text to type must be 1 to {MAX_TYPE_CHARS} characters.")
        return Plan("type", target)
    if action == "set_brightness":
        m = re.fullmatch(r"(-?\d+)\s*%?", target)
        if not m:
            raise PlanError("Say a brightness level from 0 to 100.")
        return Plan("brightness", str(max(0, min(100, int(m[1])))))
    if action in ("brightness_up", "brightness_down"):
        return Plan("brightness", "+10" if action == "brightness_up" else "-10")
    if action in POWER_ACTIONS:
        return Plan("power_request", action)
    if action == "confirm_power":
        return Plan("power_confirm", "")
    if action in _VK or action in ("screenshot", "close_window"):
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


def format_weather(data: dict, city: str = "") -> str:
    now = data["current_condition"][0]
    area = city.strip() or data["nearest_area"][0]["areaName"][0]["value"]
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


class PowerNotConfirmed(RuntimeError):
    """confirm_power was called without a valid earlier request."""


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        # MOUSEINPUT is the largest member; pad so sizeof matches the Win32 INPUT.
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def _type_unicode(text: str) -> None:
    """Type text into the focused window, character by character."""
    keyeventf_unicode, input_keyboard = 0x0004, 1
    send = ctypes.windll.user32.SendInput
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            _tap(0x0D)  # Enter
            continue
        for unit in _utf16_units(ch):
            for flags in (keyeventf_unicode, keyeventf_unicode | _KEYUP):
                inp = _INPUT(type=input_keyboard)
                inp.ki = _KEYBDINPUT(0, unit, flags, 0, 0)
                send(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        time.sleep(0.005)


def _utf16_units(ch: str) -> list[int]:
    data = ch.encode("utf-16-le")
    return [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]


_PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]


def _brightness(payload: str) -> str:
    """Laptop screen brightness via WMI. payload: '0'-'100', '+10' or '-10'."""
    if payload[0] in "+-":
        current = subprocess.run(
            _PS + ["(Get-CimInstance -Namespace root/WMI -ClassName "
                   "WmiMonitorBrightness).CurrentBrightness"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip().splitlines()
        if not current or not current[0].strip().isdigit():
            raise OSError("This screen's brightness can't be controlled from Windows.")
        level = max(0, min(100, int(current[0]) + int(payload)))
    else:
        level = int(payload)
    result = subprocess.run(
        _PS + ["(Get-CimInstance -Namespace root/WMI -ClassName "
               f"WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise OSError("This screen's brightness can't be controlled from Windows.")
    return f"Brightness set to {level}%."


def _power(kind: str) -> None:
    if kind == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "5"], check=True)
    elif kind == "restart":
        subprocess.run(["shutdown", "/r", "/t", "5"], check=True)
    elif kind == "sleep":
        ctypes.windll.powrprof.SetSuspendState(False, True, False)


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
        return format_weather(r.json(), p.payload)
    if p.kind == "type":
        _type_unicode(p.payload)
        return "Typed it."
    if p.kind == "brightness":
        return _brightness(p.payload)
    if p.kind == "power_request":
        POWER_GATE.request(p.payload)
        return (
            f"Asked the user to confirm {p.payload}. Ask: 'Are you sure you want "
            f"to {p.payload}?' and call confirm_power only after they say yes."
        )
    if p.kind == "power_confirm":
        kind = POWER_GATE.confirm()
        if kind is None:
            raise PowerNotConfirmed(
                "Not confirmed. The user must first ask to shut down, restart, or "
                "sleep, then say yes in their next message within 30 seconds."
            )
        _power(kind)
        return f"Okay, {kind} in a few seconds."
    if p.kind == "keys":
        if p.payload == "screenshot":
            _tap(_VK_LWIN, _VK_SNAPSHOT)
            return "Screenshot saved to Pictures\\Screenshots."
        if p.payload == "close_window":
            _tap(_VK_MENU, _VK_F4)
            return "Closed the current window."
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
                "tell the time or battery level; open_folder (target = "
                f"{', '.join(sorted(FOLDERS))}); type_text types into the active "
                "window; close_window; set_brightness (target = 0-100), "
                "brightness_up, brightness_down; shutdown, restart, sleep only "
                "ASK for confirmation, and confirm_power performs it after the user "
                f"says yes in their next message. Known apps: {', '.join(sorted(APPS))}."
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
        except PowerNotConfirmed as exc:
            return ToolResult(tool_name="pc_control", content=str(exc), success=False)
        except (OSError, httpx.HTTPError, KeyError, ValueError,
                subprocess.SubprocessError) as exc:
            return ToolResult(
                tool_name="pc_control", content=f"Failed: {exc}", success=False
            )
