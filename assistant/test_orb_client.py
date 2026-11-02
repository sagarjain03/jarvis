"""Tests for the orb client: JSON-line messages, and never crashing Jarvis."""

import io
import json

from orb_client import OrbClient


class FakeProc:
    def __init__(self, broken=False):
        self.stdin = io.StringIO()
        self.broken = broken
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def test_messages_are_json_lines():
    proc = FakeProc()
    orb = OrbClient(spawn=lambda: proc)
    orb.state("listening")
    orb.level(0.42)
    orb.speaking([0.1, 0.5], fps=30)
    orb.hide()
    lines = [json.loads(line) for line in proc.stdin.getvalue().splitlines()]
    assert lines == [
        {"cmd": "state", "state": "listening"},
        {"cmd": "level", "value": 0.42},
        {"cmd": "speak", "env": [0.1, 0.5], "fps": 30},
        {"cmd": "hide"},
    ]


def test_orb_failing_to_start_is_harmless():
    def boom():
        raise OSError("no display")

    orb = OrbClient(spawn=boom)
    orb.state("listening")  # must not raise
    orb.hide()
    orb.close()


def test_broken_pipe_disables_orb_quietly():
    class Broken(FakeProc):
        def __init__(self):
            super().__init__()

            class Pipe:
                def write(self, _):
                    raise BrokenPipeError

                def flush(self):
                    pass

            self.stdin = Pipe()

    orb = OrbClient(spawn=Broken)
    orb.state("listening")
    orb.state("thinking")  # still must not raise


def test_close_terminates_process():
    proc = FakeProc()
    orb = OrbClient(spawn=lambda: proc)
    orb.state("listening")
    orb.close()
    assert proc.terminated


def test_tray_menu_events_reach_jarvis():
    import threading

    proc = FakeProc()
    proc.stdout = io.StringIO('{"event": "pause"}\nnot json\n{"event": "quit"}\n')
    got, done = [], threading.Event()

    def on_event(event):
        got.append(event)
        if event == "quit":
            done.set()

    orb = OrbClient(spawn=lambda: proc, on_event=on_event)
    orb.tray(paused=True)
    assert done.wait(2)
    assert got == ["pause", "quit"]
    assert json.loads(proc.stdin.getvalue()) == {"cmd": "tray", "paused": True}
