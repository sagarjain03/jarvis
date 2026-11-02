"""Tests for the conversation-session logic (pure; no audio devices)."""

import threading

import numpy as np
import pytest

from session import (
    SILENCE_CHUNKS,
    Session,
    SpeechGate,
    calibrate_threshold,
    envelope,
    is_stop_command,
    play_all,
    split_sentences,
)


# --- barge-in playback ---------------------------------------------------------

def test_play_all_plays_everything_when_not_interrupted():
    played = []
    done = play_all(iter(["a", "b", "c"]), lambda x: played.append(x) or True, threading.Event())
    assert done and played == ["a", "b", "c"]


def test_play_all_skips_rest_after_interrupt():
    stop = threading.Event()
    played = []

    def play(x):
        played.append(x)
        stop.set()  # user said "Jarvis" during the first sentence
        return False

    assert not play_all(iter(["a", "b", "c"]), play, stop)
    assert played == ["a"]


def test_play_all_plays_nothing_if_already_interrupted():
    stop = threading.Event()
    stop.set()
    played = []
    assert not play_all(iter(["a"]), lambda x: played.append(x) or True, stop)
    assert played == []


# --- noise calibration ---------------------------------------------------------

def test_quiet_room_keeps_default_threshold():
    assert calibrate_threshold([40, 60, 50, 55]) == 500


def test_noisy_room_raises_threshold():
    assert calibrate_threshold([300, 320, 310, 290]) == pytest.approx(305 * 3)  # median 305


def test_calibration_ignores_a_short_spike():
    # a door slam in the sample should not make Jarvis deaf
    assert calibrate_threshold([300, 300, 300, 9000, 300]) == pytest.approx(900)


def test_calibration_is_capped_and_handles_no_data():
    assert calibrate_threshold([5000] * 10) == 3000
    assert calibrate_threshold([]) == 500


def test_default_silence_is_under_a_second():
    # 1024-sample chunks at 16 kHz = 64 ms each
    assert SILENCE_CHUNKS * 1024 / 16000 < 1.0
    gate = SpeechGate()
    _feed(gate, [900, 900])
    states = [gate.feed(10) for _ in range(SILENCE_CHUNKS)]
    assert states[-1] == "done" and "done" not in states[:-1]


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
