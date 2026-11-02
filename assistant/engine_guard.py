"""Rate-limit handling for each model call, not for the whole request.

Retrying a whole request re-runs tools that already ran (night mode twice,
text typed twice). Here only the failed model call is repeated: first on a
backup Groq model (each model has its own free quota, so no waiting), and
only if all are limited, after the wait Groq asks for.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from brain import _rate_limit_wait

GROQ_BACKUPS = ["groq/openai/gpt-oss-20b", "groq/qwen/qwen3.8-27b"]


class ResilientEngine:
    def __init__(
        self,
        engine: Any,
        backups: list[str] = GROQ_BACKUPS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine = engine
        self._backups = backups
        self._sleep = sleep

    def __getattr__(self, name: str) -> Any:  # health(), engine_id, ... of the real engine
        return getattr(self._engine, name)

    def generate(self, messages: Any, *, model: str, **kwargs: Any) -> Any:
        models = [model] + [m for m in self._backups if m != model]
        wait = None
        for candidate in models:
            try:
                return self._engine.generate(messages, model=candidate, **kwargs)
            except Exception as exc:
                wait = _rate_limit_wait(exc)
                if wait is None:
                    raise  # offline or a real error: not ours to retry
        self._sleep(wait)
        return self._engine.generate(messages, model=model, **kwargs)
