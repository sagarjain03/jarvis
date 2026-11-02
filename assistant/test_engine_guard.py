"""Tests for per-call rate-limit handling (backup models, then wait). No network."""

import pytest

from engine_guard import ResilientEngine

LIMITED = RuntimeError("RateLimitError: Rate limit reached. Please try again in 4.5s.")


class FakeEngine:
    engine_id = "litellm"

    def __init__(self, limited=()):
        self.limited = set(limited)  # models that are rate-limited
        self.calls = []

    def generate(self, messages, *, model, **kw):
        self.calls.append(model)
        if model in self.limited:
            raise LIMITED
        return {"content": f"from {model}", "tools": kw.get("tools")}


def make(limited=(), backups=("b1", "b2")):
    engine, sleeps = FakeEngine(limited), []
    return ResilientEngine(engine, backups=list(backups), sleep=sleeps.append), engine, sleeps


def test_success_uses_requested_model_and_passes_kwargs():
    guard, engine, sleeps = make()
    out = guard.generate(["m"], model="main", temperature=0.3, tools=["t"])
    assert out == {"content": "from main", "tools": ["t"]}
    assert engine.calls == ["main"] and sleeps == []


def test_rate_limited_model_falls_to_backup_without_waiting():
    guard, engine, sleeps = make(limited={"main"})
    assert guard.generate(["m"], model="main")["content"] == "from b1"
    assert engine.calls == ["main", "b1"] and sleeps == []


def test_all_limited_waits_once_then_retries():
    guard, engine, sleeps = make(limited={"main", "b1", "b2"})
    engine_calls_before_wait = 3

    def unlock(seconds):
        sleeps.append(seconds)
        engine.limited.clear()

    guard._sleep = unlock
    assert guard.generate(["m"], model="main")["content"] == "from main"
    assert len(engine.calls) == engine_calls_before_wait + 1
    assert sleeps == [pytest.approx(5.5)]


def test_still_limited_after_waiting_raises():
    guard, _, sleeps = make(limited={"main", "b1", "b2"})
    with pytest.raises(RuntimeError, match="RateLimit"):
        guard.generate(["m"], model="main")
    assert len(sleeps) == 1


def test_other_errors_are_not_retried():
    guard, engine, _ = make()

    def offline(messages, *, model, **kw):
        engine.calls.append(model)
        raise OSError("APIConnectionError: getaddrinfo failed")

    engine.generate = offline
    with pytest.raises(OSError):
        guard.generate(["m"], model="main")
    assert engine.calls == ["main"]  # Brain's offline fallback takes over


def test_backup_equal_to_main_is_skipped_and_attributes_pass_through():
    guard, engine, _ = make(limited={"main"}, backups=("main", "b2"))
    assert guard.generate(["m"], model="main")["content"] == "from b2"
    assert engine.calls == ["main", "b2"]
    assert guard.engine_id == "litellm"
