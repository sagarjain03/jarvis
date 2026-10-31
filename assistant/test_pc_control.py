"""Tests for the safe PC-control tool. Only planning is tested; nothing runs."""

import pytest

from pc_control import (
    ACTIONS,
    APPS,
    PcControlTool,
    Plan,
    PlanError,
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
        plan("shutdown", "")


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
