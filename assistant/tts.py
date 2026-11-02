"""Text-to-speech: Microsoft Edge neural voices first (free, ~1.6 s a sentence),
local Kokoro as fallback when offline or disabled.

On this 4-core CPU Kokoro needed up to ~10 s for one sentence. Edge TTS sends
the reply text to Microsoft; set use_cloud=False to keep everything local.
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Callable

import numpy as np
import soundfile as sf

from brain import is_hindi

EDGE_ENGLISH = "en-GB-RyanNeural"  # British male, very Jarvis
EDGE_HINDI = "hi-IN-MadhurNeural"

Audio = tuple[np.ndarray, int]


def edge_synth(text: str, voice: str) -> Audio:
    import edge_tts

    async def fetch() -> bytes:
        comm = edge_tts.Communicate(text, voice, connect_timeout=4, receive_timeout=15)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return bytes(buf)

    mp3 = asyncio.run(fetch())
    if not mp3:
        raise RuntimeError("Edge TTS returned no audio")
    return sf.read(io.BytesIO(mp3), dtype="float32")


class Speaker:
    def __init__(
        self,
        cloud: Callable[[str, str], Audio],
        local: Callable[[str], Audio],
        *,
        use_cloud: bool = True,
        now: Callable[[], float] = time.monotonic,
        retry_after: float = 60,
    ) -> None:
        self._cloud = cloud
        self._local = local
        self._use_cloud = use_cloud
        self._now = now
        self._retry_after = retry_after
        self._cloud_failed_at: float | None = None

    def _cloud_ok(self) -> bool:
        if not self._use_cloud:
            return False
        failed = self._cloud_failed_at
        return failed is None or self._now() - failed > self._retry_after

    def synthesize(self, text: str) -> Audio:
        if self._cloud_ok():
            try:
                audio = self._cloud(text, EDGE_HINDI if is_hindi(text) else EDGE_ENGLISH)
                self._cloud_failed_at = None
                return audio
            except Exception:
                # Offline: don't wait for a timeout on every sentence for a while.
                self._cloud_failed_at = self._now()
        return self._local(text)
