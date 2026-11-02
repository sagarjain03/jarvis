"""Tests for Brain's follow-up memory. Uses a fake agent; no model is called."""

from dataclasses import dataclass

import pytest
from openjarvis.core.types import Role

from brain import Brain


@dataclass
class _Result:
    content: str


class FakeAgent:
    def __init__(self):
        self.seen = []  # (input, [(role, content) of history])

    def run(self, text, context=None):
        history = [(m.role, m.content) for m in context.conversation.messages]
        self.seen.append((text, history))
        return _Result(f"answer to {text}")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup():
    agent, clock = FakeAgent(), Clock()
    return Brain(agent, now=clock), agent, clock


def test_first_turn_has_no_history(setup):
    brain, agent, _ = setup
    assert brain.reply("weather in Delhi") == "answer to weather in Delhi"
    assert agent.seen[0][1] == []


def test_follow_up_sees_previous_turn(setup):
    brain, agent, _ = setup
    brain.reply("weather in Delhi")
    brain.reply("and Mumbai?")
    assert agent.seen[1][1] == [
        (Role.USER, "weather in Delhi"),
        (Role.ASSISTANT, "answer to weather in Delhi"),
    ]


def test_history_is_capped_to_last_ten_turns(setup):
    brain, agent, _ = setup
    for i in range(15):
        brain.reply(f"q{i}")
    history = agent.seen[-1][1]
    assert len(history) == 20  # 10 turns x (user + assistant)
    assert history[0] == (Role.USER, "q4")


def test_memory_clears_after_three_minutes_idle(setup):
    brain, agent, clock = setup
    brain.reply("weather in Delhi")
    clock.t += 181
    brain.reply("and Mumbai?")
    assert agent.seen[1][1] == []


def test_memory_kept_within_idle_window(setup):
    brain, agent, clock = setup
    brain.reply("weather in Delhi")
    clock.t += 170
    brain.reply("and Mumbai?")
    assert len(agent.seen[1][1]) == 2


@pytest.mark.parametrize("phrase", ["new topic", "Forget that.", "start over"])
def test_reset_phrases_clear_memory_without_calling_agent(setup, phrase):
    brain, agent, _ = setup
    brain.reply("weather in Delhi")
    reply = brain.reply(phrase)
    assert len(agent.seen) == 1
    assert reply
    brain.reply("hello")
    assert agent.seen[1][1] == []


def test_rate_limit_never_reruns_the_whole_request():
    # A rerun repeats tools that already ran (night mode ran twice, text typed
    # twice). Per-call retries live in engine_guard instead.
    calls = []

    class Limited:
        def run(self, text, context=None):
            calls.append(text)
            raise RuntimeError("RateLimitError: Rate limit reached. Please try again in 4.7s.")

    assert "busy" in Brain(Limited()).reply("turn on night mode").lower()
    assert calls == ["turn on night mode"]


@pytest.mark.parametrize(
    "msg, wait",
    [("RateLimitError: Please try again in 4.7475s.", 5.7475),
     ("RateLimitError: try again in 2m30s", 20),
     ("rate limit reached", 5.0),
     ("network down", None)],
)
def test_rate_limit_wait(msg, wait):
    from brain import _rate_limit_wait

    got = _rate_limit_wait(RuntimeError(msg))
    assert got == (None if wait is None else pytest.approx(wait))


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("The next ... ........ ……… … … one. Playing now.", "The next … one. Playing now."),
        ("Done!", "Done!"),
        ("Wait... okay.", "Wait... okay."),
        ("Done.Done.", "Done."),
        ("Opened it. Opened it.", "Opened it."),
    ],
)
def test_reply_text_cleanup(raw, clean):
    from brain import clean_reply

    assert clean_reply(raw) == clean


def test_on_turn_callback_runs_before_each_request():
    agent, turns = FakeAgent(), []
    brain = Brain(agent, on_turn=lambda: turns.append(len(agent.seen)))
    brain.reply("a")
    brain.reply("b")
    assert turns == [0, 1]


@pytest.mark.parametrize(
    "text, hindi",
    [("नमस्ते, मौसम साफ है।", True), ("Hello there", False), ("Kesariya चल रहा है", True)],
)
def test_is_hindi(text, hindi):
    from brain import is_hindi

    assert is_hindi(text) is hindi


def test_agent_giving_up_is_reported_and_not_remembered(setup):
    brain, agent, _ = setup
    agent.run = lambda text, context=None: _Result("Maximum turns reached without a final answer.")
    assert "couldn't finish" in brain.reply("hard question").lower()
    assert brain._history == []


def test_facts_prompt_lists_saved_facts(tmp_path):
    from brain import facts_prompt

    path = tmp_path / "facts.md"
    assert facts_prompt(path) == ""
    path.write_text("\n- Name is Sagar\n- Lives in Indore\n", encoding="utf-8")
    text = facts_prompt(path)
    assert "Name is Sagar" in text and "Lives in Indore" in text


def test_failed_turn_is_not_remembered(setup):
    brain, agent, _ = setup

    def boom(text, context=None):
        raise RuntimeError("network down")

    agent.run, ok_run = boom, agent.run
    assert "sorry" in brain.reply("weather").lower()
    agent.run = ok_run
    brain.reply("hello")
    assert agent.seen[0][1] == []


# --- offline fallback ----------------------------------------------------------

class RaisingAgent:
    def __init__(self, exc):
        self.exc = exc

    def run(self, text, context=None):
        raise self.exc


def test_offline_falls_back_to_local_model():
    cloud = RaisingAgent(Exception("litellm.APIConnectionError: getaddrinfo failed"))
    local = FakeAgent()
    made = []
    brain = Brain(cloud, fallback=lambda: made.append(1) or local)
    assert brain.reply("what is 2+2") == "answer to what is 2+2"
    assert brain.last_error is None
    brain.reply("and 3+3?")
    assert made == [1]  # local agent built once, reused
    assert local.seen[1][1][0] == (Role.USER, "what is 2+2")  # keeps memory


def test_rate_limit_does_not_use_local_model():
    cloud = RaisingAgent(Exception("RateLimitError: try again in 1s"))
    used = []
    brain = Brain(cloud, fallback=lambda: used.append(1) or FakeAgent())
    assert "busy" in brain.reply("hi")
    assert used == []


def test_offline_without_local_model_says_so():
    cloud = RaisingAgent(Exception("httpx.ConnectError: connection refused"))
    brain = Brain(cloud, fallback=lambda: None)
    assert "offline" in brain.reply("hi").lower()


def test_local_model_failing_too_is_handled():
    cloud = RaisingAgent(Exception("APIConnectionError"))
    local = RaisingAgent(Exception("ollama crashed"))
    brain = Brain(cloud, fallback=lambda: local)
    assert brain.reply("hi") == "Sorry, something went wrong."
