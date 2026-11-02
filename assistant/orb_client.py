"""Talks to the orb window (orb.py) over its stdin, one JSON message per line.

The orb process also owns the tray icon; menu clicks come back on its stdout
as {"event": "pause"|"resume"|"quit"} lines and go to ``on_event``.
The orb is decoration: if it can't start or dies, Jarvis keeps working.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable


def _spawn_orb() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("orb.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


class OrbClient:
    def __init__(
        self,
        spawn: Callable[[], Any] = _spawn_orb,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self._spawn = spawn
        self.on_event = on_event
        self._proc: Any = None
        self._disabled = False
        self._lock = threading.Lock()

    def _read_events(self, stdout: Any) -> None:
        for line in stdout:
            try:
                event = json.loads(line).get("event")
            except (json.JSONDecodeError, AttributeError):
                continue
            if event and self.on_event is not None:
                self.on_event(event)

    def _send(self, msg: dict) -> None:
        with self._lock:  # voice loop and reminder thread both send
            if self._disabled:
                return
            try:
                if self._proc is None:
                    self._proc = self._spawn()
                    stdout = getattr(self._proc, "stdout", None)
                    if stdout is not None:
                        threading.Thread(
                            target=self._read_events, args=(stdout,), name="orb-events", daemon=True
                        ).start()
                self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError):  # includes BrokenPipeError
                self._disabled = True

    def state(self, state: str) -> None:
        """listening | thinking | speaking — also shows the orb."""
        self._send({"cmd": "state", "state": state})

    def level(self, value: float) -> None:
        self._send({"cmd": "level", "value": round(float(value), 3)})

    def speaking(self, env: list[float], fps: int = 30) -> None:
        self._send({"cmd": "speak", "env": env, "fps": fps})

    def caption(self, text: str) -> None:
        self._send({"cmd": "caption", "text": text[:140]})

    def tray(self, paused: bool) -> None:
        """Show the tray icon (starting the orb process) with the current state."""
        self._send({"cmd": "tray", "paused": paused})

    def hide(self) -> None:
        self._send({"cmd": "hide"})

    def close(self) -> None:
        if self._proc is None:
            return
        self._send({"cmd": "quit"})
        try:
            self._proc.terminate()
        except OSError:
            pass
        self._proc = None
