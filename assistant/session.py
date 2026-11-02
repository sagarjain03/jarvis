"""Conversation-session logic: stop phrases, inactivity, speech detection, orb envelope.

All pure so it can be tested without a microphone.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Iterable

import numpy as np

# Spoken around a command without changing it: "okay, stop Jarvis, thanks".
_FILLER = {"jarvis", "okay", "ok", "hey", "thanks", "thank", "you", "please", "now"}
_STOP = {
    "stop", "bye", "goodbye", "good bye", "bye bye", "that's all", "thats all",
    "go to sleep", "band ho jao", "band ho ja", "so jao", "chup ho jao",
    "बंद हो जाओ", "बंद करो", "बंद", "बाय", "सो जाओ",
}
_PUNCT = re.compile(r"[,.!?।;:\"]+")


def is_stop_command(text: str) -> bool:
    """True only for a whole-message stop ('stop Jarvis'), not 'stop the music'."""
    words = _PUNCT.sub(" ", text.lower().replace("’", "'")).split()
    while words and words[0] in _FILLER:
        words.pop(0)
    while words and words[-1] in _FILLER:
        words.pop()
    return " ".join(words) in _STOP


class ListenControl:
    """Pause / resume / quit requests from the tray menu, shared with the voice loop.

    While paused the microphone is closed entirely.
    """

    def __init__(self, on_change: Callable[[bool], None] = lambda paused: None) -> None:
        self._paused = threading.Event()
        self._quit = threading.Event()
        self._on_change = on_change

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def quitting(self) -> bool:
        return self._quit.is_set()

    def should_stop(self) -> bool:
        """True when the voice loop should stop using the microphone."""
        return self.paused or self.quitting

    def _set_paused(self, paused: bool) -> None:
        if paused == self.paused:
            return
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
        self._on_change(paused)

    def handle(self, event: str) -> None:
        if event == "pause":
            self._set_paused(True)
        elif event == "resume":
            self._set_paused(False)
        elif event == "toggle":
            self._set_paused(not self.paused)
        elif event == "quit":
            self._quit.set()


class Session:
    """Ends after ``idle_seconds`` without the user saying anything."""

    def __init__(self, idle_seconds: float = 60, now: Callable[[], float] = time.monotonic) -> None:
        self._idle = idle_seconds
        self._now = now
        self._last = now()

    def touch(self) -> None:
        self._last = self._now()

    def expired(self) -> bool:
        return self._now() - self._last > self._idle


SILENCE_CHUNKS = 12  # ~0.8 s of quiet (1024-sample chunks at 16 kHz) ends your turn
DEFAULT_THRESHOLD = 500
MAX_THRESHOLD = 3000  # never so high that normal speech can't get through


def calibrate_threshold(levels: list[float]) -> float:
    """Speech threshold from ~1 s of room noise: 3x the typical (median) level.

    The median ignores a one-off spike like a door slam during calibration.
    """
    if not levels:
        return DEFAULT_THRESHOLD
    return min(MAX_THRESHOLD, max(DEFAULT_THRESHOLD, float(np.median(levels)) * 3))


def play_all(items: Iterable, play: Callable[[object], bool], interrupted: threading.Event) -> bool:
    """Play items in order; ``play`` returns False if cut off. True if all played."""
    for item in items:
        if interrupted.is_set() or not play(item):
            return False
    return True


class SpeechGate:
    """Feed one RMS level per audio chunk; reports when an utterance is complete.

    States: "waiting" (no speech yet), "speaking", "done" (speech then
    silence, or max length), "no_speech" (nothing said before the timeout).
    """

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        silence_chunks: int = SILENCE_CHUNKS,
        start_timeout_chunks: int = 125,  # ~8 s
        max_chunks: int = 470,  # ~30 s
        min_speech_chunks: int = 2,  # ignore single clicks
    ) -> None:
        self._threshold = threshold
        self._silence_chunks = silence_chunks
        self._start_timeout = start_timeout_chunks
        self._max = max_chunks
        self._min_speech = min_speech_chunks
        self._count = 0
        self._loud_run = 0
        self._silence = 0
        self.started = False

    def feed(self, level: float) -> str:
        self._count += 1
        loud = level > self._threshold
        if not self.started:
            self._loud_run = self._loud_run + 1 if loud else 0
            if self._loud_run >= self._min_speech:
                self.started = True
            elif self._count >= min(self._start_timeout, self._max):
                return "no_speech"
            else:
                return "waiting"
        self._silence = 0 if loud else self._silence + 1
        if self._silence >= self._silence_chunks or self._count >= self._max:
            return "done"
        return "speaking"


_SENTENCE_END = re.compile(r"(?<=[.!?।…])\s+")


def split_sentences(text: str) -> list[str]:
    """Split a reply so speech can start after the first sentence is ready.

    Splits only at end punctuation followed by whitespace, so "26.5" stays whole.
    """
    return [s for s in (p.strip() for p in _SENTENCE_END.split(text.strip())) if s]


def envelope(samples: np.ndarray, sample_rate: int, fps: int = 30) -> list[float]:
    """Loudness per animation frame, normalized to 0..1, for the speaking orb."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    hop = max(1, int(sample_rate / fps))
    frames = max(1, round(len(samples) / hop))
    levels = [
        float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
        for chunk in (samples[i * hop:(i + 1) * hop] for i in range(frames))
    ]
    peak = max(levels)
    if peak <= 0:
        return [0.0] * frames
    return [round(v / peak, 3) for v in levels]
