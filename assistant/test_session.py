"""Tests for the conversation-session logic (pure; no audio devices)."""

import numpy as np
import pytest

from session import Session, SpeechGate, envelope, is_stop_command, split_sentences


# --- sentence streaming ------------------------------------------------------

@pytest.mark.parametrize(
    "text, parts",
    [
        ("Hello there. How are you?", ["Hello there.", "How are you?"]),
        ("नमस्ते। आप कैसे हैं?", ["नमस्ते।", "आप कैसे हैं?"]),
        ("It is 26.5 °C today! Enjoy.", ["It is 26.5 °C today!", "Enjoy."]),
        ("No punctuation at all", ["No punctuation at all"]),
        ("Yes. Ok", ["Yes.", "Ok"]),
        ("", []),
        ("  Wait...  then go.  ", ["Wait...", "then go."]),
    ],
)
def test_split_sentences(text, parts):
    assert split_sentences(text) == parts


# --- stop commands -----------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    ["Stop Jarvis", "stop, Jarvis.", "Jarvis stop!", "Bye Jarvis", "Goodbye, Jarvis",
     "Okay, stop Jarvis.", "bye", "Goodbye.", "That's all.", "That's all, Jarvis",
     "Jarvis band ho jao", "band ho jao", "बंद हो जाओ", "Jarvis, go to sleep",
     "Thanks Jarvis, that's all"],
)
def test_stop_commands(text):
    assert is_stop_command(text)


@pytest.mark.parametrize(
    "text",
    ["Stop the music", "stop the timer", "What's the bus stop near me?",
     "Play goodbye song by Arijit", "Pause", "Jarvis, open YouTube", ""],
)
def test_not_stop_commands(text):
    assert not is_stop_command(text)


# --- inactivity ----------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_session_expires_after_idle_time():
    clock = Clock()
    s = Session(idle_seconds=60, now=clock)
    clock.t = 59
    assert not s.expired()
    clock.t = 61
    assert s.expired()


def test_activity_resets_idle_timer():
    clock = Clock()
    s = Session(idle_seconds=60, now=clock)
    clock.t = 50
    s.touch()
    clock.t = 100
    assert not s.expired()
    clock.t = 111
    assert s.expired()


# --- speech gate -----------------------------------------------------------------

def _feed(gate, levels):
    states = [gate.feed(level) for level in levels]
    return states[-1]


def test_gate_waits_then_gives_up_without_speech():
    gate = SpeechGate(threshold=500, silence_chunks=3, start_timeout_chunks=5, max_chunks=100)
    assert _feed(gate, [10] * 4) == "waiting"
    assert gate.feed(10) == "no_speech"


def test_gate_ends_after_silence_following_speech():
    gate = SpeechGate(threshold=500, silence_chunks=3, start_timeout_chunks=5, max_chunks=100)
    assert _feed(gate, [10, 900, 800]) == "speaking"
    assert _feed(gate, [10, 10]) == "speaking"
    assert gate.feed(10) == "done"


def test_gate_speech_resets_silence_count():
    gate = SpeechGate(threshold=500, silence_chunks=3, start_timeout_chunks=5, max_chunks=100)
    assert _feed(gate, [900, 900, 10, 10, 900, 10, 10]) == "speaking"
    assert gate.feed(10) == "done"


def test_gate_stops_at_max_length():
    gate = SpeechGate(threshold=500, silence_chunks=3, start_timeout_chunks=5, max_chunks=6)
    assert _feed(gate, [900] * 5) == "speaking"
    assert gate.feed(900) == "done"


def test_gate_ignores_a_single_click():
    # one loud chunk then silence is a click/tap, not speech
    gate = SpeechGate(threshold=500, silence_chunks=3, start_timeout_chunks=8,
                      max_chunks=100, min_speech_chunks=2)
    assert _feed(gate, [900, 10, 10, 10]) == "waiting"


# --- envelope for the orb -------------------------------------------------------

def test_envelope_length_and_range():
    sr = 24000
    t = np.linspace(0, 2, 2 * sr, endpoint=False)
    samples = np.sin(2 * np.pi * 220 * t) * np.linspace(0, 1, t.size)  # fade in
    env = envelope(samples, sr, fps=30)
    assert len(env) == 60
    assert all(0.0 <= v <= 1.0 for v in env)
    assert env[-1] > env[5]  # louder at the end
    assert max(env) == pytest.approx(1.0)


def test_envelope_of_silence_is_zero():
    assert envelope(np.zeros(24000), 24000, fps=30) == [0.0] * 30
