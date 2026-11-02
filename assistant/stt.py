"""Speech-to-text: Groq's hosted Whisper first (fast, good with Hindi/Hinglish),
local faster-whisper as fallback when offline, rate-limited, or disabled.

On a 4-core CPU a 3.5 s command took 12 s with local whisper "small" and
0.3 s on Groq, which is why cloud is the default here.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
# No vocabulary prompt: an English one turned Hinglish into wrong English
# words ("Indore ka weather" -> "Indoor Car Weather").


class Transcriber:
    def __init__(
        self,
        api_key: str,
        local: Callable[[], Any],
        *,
        use_cloud: bool = True,
        post: Callable[..., Any] = httpx.post,
        language: str | None = None,
    ) -> None:
        self._key = api_key.strip()
        self._make_local = local
        self._local: Any = None
        self._use_cloud = use_cloud and bool(self._key)
        self._post = post
        self._language = language

    def _groq(self, audio: bytes) -> str | None:
        try:
            resp = self._post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("speech.wav", audio, "audio/wav")},
                data={"model": GROQ_MODEL, "temperature": "0"},
                timeout=15,
            )
        except (OSError, httpx.HTTPError):
            return None
        if resp.status_code != 200:
            return None  # e.g. 429 rate limit: fall back to local
        return str(resp.json().get("text", "")).strip()

    def transcribe(self, audio: bytes) -> str:
        if self._use_cloud:
            text = self._groq(audio)
            if text is not None:
                return text
        try:
            if self._local is None:
                self._local = self._make_local()
            return self._local.transcribe(audio, format="wav", language=self._language).text.strip()
        except Exception:
            return ""
