"""Tests for the safe PC-control tool. Only planning is tested; nothing runs."""

import pytest

from pc_control import (
    ACTIONS,
    APPS,
    PcControlTool,
    Plan,
    PlanError,
    PowerGate,
    first_youtube_video,
    format_weather,
    plan,
)


# --- websites ---------------------------------------------------------------

@pytest.mark.parametrize(
    "target, url",
    [
        ("youtube.com", "https://youtube.com"),
        ("https://www.google.com/maps", "https://www.google.com/maps"),
        ("http://example.org", "http://example.org"),
        ("  github.com  ", "https://github.com"),
    ],
)
def test_open_website_normalizes_to_http_url(target, url):
    assert plan("open_website", target) == Plan("open_url", url)


@pytest.mark.parametrize("name", ["youtube", "YouTube", "google", "gmail"])
def test_open_website_accepts_known_site_names(name):
    p = plan("open_website", name)
    assert p.kind == "open_url"
    assert p.payload.startswith("https://")


@pytest.mark.parametrize(
    "target",
    [
        "file:///C:/Windows/System32",
        "javascript:alert(1)",
        "C:\\Windows\\System32\\cmd.exe",
        "ms-settings:",
        "ftp://example.com",
        "not a website",
        "",
    ],
)
def test_open_website_rejects_non_web_targets(target):
    with pytest.raises(PlanError):
        plan("open_website", target)


# --- search -----------------------------------------------------------------

def test_search_youtube_builds_encoded_search_url():
    p = plan("search_youtube", "lofi music & rain")
    assert p == Plan(
        "open_url",
        "https://www.youtube.com/results?search_query=lofi+music+%26+rain",
    )


def test_search_google_builds_encoded_search_url():
    p = plan("search_google", "weather in delhi")
    assert p == Plan("open_url", "https://www.google.com/search?q=weather+in+delhi")


def test_search_requires_query():
    with pytest.raises(PlanError):
        plan("search_google", "   ")


def test_search_gmail_opens_gmail_search():
    p = plan("search_gmail", "amazon order")
    assert p == Plan("open_url", "https://mail.google.com/mail/u/0/#search/amazon%20order")


@pytest.mark.parametrize("name", ["mail", "email", "gmail"])
def test_mail_names_open_gmail(name):
    assert plan("open_website", name) == Plan("open_url", "https://mail.google.com")


@pytest.mark.parametrize(
    "action, url",
    [
        ("ask_chatgpt", "https://chatgpt.com/?q=write+a+poem"),
        ("ask_claude", "https://claude.ai/new?q=write+a+poem"),
    ],
)
def test_ask_ai_opens_chat_with_prompt(action, url):
    assert plan(action, "write a poem") == Plan("open_url", url)


# --- play a specific YouTube video -------------------------------------------

def test_play_youtube_plans_a_lookup():
    assert plan("play_youtube", "kesariya song") == Plan("youtube_play", "kesariya song")


def test_play_youtube_requires_query():
    with pytest.raises(PlanError):
        plan("play_youtube", "")


def test_first_youtube_video_picks_first_id():
    html = 'x "videoId":"BddP6PYo2gs" y "videoId":"aaaaaaaaaaa"'
    assert first_youtube_video("q", fetch=lambda q: html) == (
        "https://www.youtube.com/watch?v=BddP6PYo2gs"
    )


def test_first_youtube_video_falls_back_to_search_page():
    assert first_youtube_video("lofi mix", fetch=lambda q: "no ids") == (
        "https://www.youtube.com/results?search_query=lofi+mix"
    )


# --- weather ------------------------------------------------------------------

def test_weather_plan_keeps_city_or_empty():
    assert plan("get_weather", "Delhi") == Plan("weather", "Delhi")
    assert plan("get_weather", "") == Plan("weather", "")


def test_format_weather_summarizes_wttr_json():
    data = {
        "current_condition": [{
            "temp_C": "30", "FeelsLikeC": "33", "humidity": "40",
            "weatherDesc": [{"value": "Sunny"}],
        }],
        "nearest_area": [{"areaName": [{"value": "Delhi"}]}],
    }
    assert format_weather(data) == (
        "Weather in Delhi: Sunny, 30°C (feels like 33°C), humidity 40%."
    )
    # wttr.in's "nearest area" can be a nearby town; say the city the user asked for
    assert format_weather(data, "Mumbai").startswith("Weather in Mumbai:")


# --- folders, typing, brightness, close -------------------------------------

@pytest.mark.parametrize(
    "name, shell",
    [("downloads", "shell:Downloads"), ("Documents", "shell:Personal"),
     ("desktop", "shell:Desktop"), ("pictures", "shell:My Pictures"),
     ("music", "shell:My Music"), ("videos", "shell:My Video")],
)
def test_open_folder_allowlist(name, shell):
    assert plan("open_folder", name) == Plan("open_app", shell)


@pytest.mark.parametrize("name", ["C:\\Windows", "system32", "..", ""])
def test_open_folder_rejects_others(name):
    with pytest.raises(PlanError):
        plan("open_folder", name)


def test_type_text():
    assert plan("type_text", "hello world") == Plan("type", "hello world")


@pytest.mark.parametrize("text", ["", "x" * 501])
def test_type_text_rejects_empty_or_long(text):
    with pytest.raises(PlanError):
        plan("type_text", text)


@pytest.mark.parametrize(
    "action, target, payload",
    [("set_brightness", "70", "70"), ("set_brightness", "150", "100"),
     ("set_brightness", "-5", "0"), ("set_brightness", "40%", "40"),
     ("brightness_up", "", "+10"), ("brightness_down", "", "-10")],
)
def test_brightness(action, target, payload):
    assert plan(action, target) == Plan("brightness", payload)


def test_set_brightness_needs_number():
    with pytest.raises(PlanError):
        plan("set_brightness", "bright")


def test_close_window():
    assert plan("close_window", "") == Plan("keys", "close_window")


# --- power: request, then confirm in a later turn ---------------------------

@pytest.mark.parametrize("action", ["shutdown", "restart", "sleep"])
def test_power_actions_only_request(action):
    assert plan(action, "") == Plan("power_request", action)


def test_confirm_power_plan():
    assert plan("confirm_power", "") == Plan("power_confirm", "")


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_gate_confirms_in_next_turn_within_30s():
    clock = _Clock()
    gate = PowerGate(now=clock)
    gate.new_turn()
    gate.request("shutdown")
    gate.new_turn()
    clock.t = 10
    assert gate.confirm() == "shutdown"
    assert gate.confirm() is None  # used up


def test_gate_refuses_confirm_in_same_turn():
    gate = PowerGate(now=_Clock())
    gate.new_turn()
    gate.request("shutdown")
    assert gate.confirm() is None


def test_gate_expires_after_30s():
    clock = _Clock()
    gate = PowerGate(now=clock)
    gate.new_turn()
    gate.request("restart")
    gate.new_turn()
    clock.t = 31
    assert gate.confirm() is None


def test_gate_confirm_without_request():
    gate = PowerGate(now=_Clock())
    gate.new_turn()
    assert gate.confirm() is None


def test_power_request_never_runs_power(monkeypatch):
    calls = []
    monkeypatch.setattr("pc_control._power", lambda kind: calls.append(kind))
    monkeypatch.setattr("pc_control.POWER_GATE", PowerGate(now=_Clock()))
    tool = PcControlTool()
    r = tool.execute(action="shutdown")
    assert r.success and "sure" in r.content.lower()
    r = tool.execute(action="confirm_power")  # same turn
    assert r.success is False
    assert calls == []


# --- apps -------------------------------------------------------------------

@pytest.mark.parametrize("name", ["notepad", "Calculator", "  file explorer "])
def test_open_app_accepts_allowlisted_apps(name):
    p = plan("open_app", name)
    assert p.kind == "open_app"
    assert p.payload in APPS.values()


@pytest.mark.parametrize(
    "name",
    ["cmd", "powershell", "regedit", "format c:", "notepad & del *", "C:\\evil.exe"],
)
def test_open_app_rejects_anything_not_allowlisted(name):
    with pytest.raises(PlanError):
        plan("open_app", name)


# --- keys / system ----------------------------------------------------------

@pytest.mark.parametrize(
    "action",
    ["volume_up", "volume_down", "mute", "play_pause", "next_track",
     "previous_track", "screenshot"],
)
def test_key_actions_need_no_target(action):
    assert plan(action, "").kind == "keys"


def test_lock_screen_and_info_actions():
    assert plan("lock_screen", "") == Plan("lock", "")
    assert plan("get_time", "").kind == "info"
    assert plan("get_battery", "").kind == "info"


def test_unknown_action_is_rejected():
    with pytest.raises(PlanError):
        plan("format_disk", "")


# --- tool wrapper -----------------------------------------------------------

def test_spec_lists_every_action_as_enum():
    spec = PcControlTool().spec
    assert spec.name == "pc_control"
    assert spec.parameters["properties"]["action"]["enum"] == list(ACTIONS)
    assert spec.requires_confirmation is False


def test_execute_reports_rejection_without_running(monkeypatch):
    ran = []
    monkeypatch.setattr("pc_control._run", lambda p: ran.append(p) or "ran")
    result = PcControlTool().execute(action="open_app", target="powershell")
    assert result.success is False
    assert ran == []


def test_execute_runs_valid_plan(monkeypatch):
    ran = []
    monkeypatch.setattr("pc_control._run", lambda p: ran.append(p) or "Opened.")
    result = PcControlTool().execute(action="open_website", target="youtube.com")
    assert result.success is True
    assert ran == [Plan("open_url", "https://youtube.com")]
