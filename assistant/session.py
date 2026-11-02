"""Conversation-session logic: stop phrases, inactivity, speech detection, orb envelope.

All pure so it can be tested without a microphone.
"""

from __future__ import annotations

import re
import time
from typing import Callable

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


class SpeechGate:
    """Feed one RMS level per audio chunk; reports when an utterance is complete.

    States: "waiting" (no speech yet), "speaking", "done" (speech then
    silence, or max length), "no_speech" (nothing said before the timeout).
    """

    def __init__(
        self,
        threshold: float = 500,
        silence_chunks: int = 23,  # ~1.5 s at 1024-sample chunks, 16 kHz
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
