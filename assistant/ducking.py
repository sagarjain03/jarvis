"""Turn other apps down (music, videos) while you talk to Jarvis, then back up.

Uses per-app volumes, so Jarvis's own voice stays at full volume.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable


def _all_sessions() -> Iterable[Any]:
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetAllSessions()


class Ducker:
    def __init__(
        self,
        sessions: Callable[[], Iterable[Any]] = _all_sessions,
        own_pid: int = os.getpid(),
        level: float = 0.3,
    ) -> None:
        self._sessions = sessions
        self._own_pid = own_pid
        self._level = level
        self._saved: list[tuple[Any, float]] = []  # (volume control, original level)

    def duck(self) -> None:
        if self._saved:
            return  # already ducked; don't lower twice
        try:
            sessions = list(self._sessions())
        except Exception:
            return
        for s in sessions:
            if s.ProcessId in (0, self._own_pid):  # system sounds, Jarvis itself
                continue
            try:
                vol = s.SimpleAudioVolume
                original = vol.GetMasterVolume()
                vol.SetMasterVolume(original * self._level, None)
                self._saved.append((vol, original))
            except Exception:
                continue  # app closed meanwhile

    def restore(self) -> None:
        saved, self._saved = self._saved, []
        for vol, original in saved:
            try:
                vol.SetMasterVolume(original, None)
            except Exception:
                continue
