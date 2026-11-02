"""Tests for lowering other apps' volume while Jarvis is in a conversation."""

from dataclasses import dataclass, field

import pytest

from ducking import Ducker


@dataclass
class FakeVolume:
    level: float
    sets: list = field(default_factory=list)

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, value, ctx):
        self.level = value
        self.sets.append(value)


@dataclass
class FakeSession:
    ProcessId: int
    SimpleAudioVolume: FakeVolume


def make(*levels, own_pid=1):
    sessions = [FakeSession(10 + i, FakeVolume(v)) for i, v in enumerate(levels)]
    sessions.append(FakeSession(own_pid, FakeVolume(1.0)))  # Jarvis itself
    sessions.append(FakeSession(0, FakeVolume(1.0)))  # system sounds
    return sessions


def test_duck_lowers_other_apps_and_restore_puts_them_back():
    sessions = make(1.0, 0.5)
    d = Ducker(lambda: sessions, own_pid=1, level=0.3)
    d.duck()
    assert sessions[0].SimpleAudioVolume.level == pytest.approx(0.3)
    assert sessions[1].SimpleAudioVolume.level == pytest.approx(0.15)
    assert sessions[2].SimpleAudioVolume.sets == []  # never ducks Jarvis
    assert sessions[3].SimpleAudioVolume.sets == []  # or system sounds
    d.restore()
    assert sessions[0].SimpleAudioVolume.level == pytest.approx(1.0)
    assert sessions[1].SimpleAudioVolume.level == pytest.approx(0.5)


def test_duck_twice_does_not_compound():
    sessions = make(1.0)
    d = Ducker(lambda: sessions, own_pid=1, level=0.3)
    d.duck()
    d.duck()
    d.restore()
    assert sessions[0].SimpleAudioVolume.level == pytest.approx(1.0)


def test_restore_without_duck_is_harmless():
    sessions = make(0.8)
    Ducker(lambda: sessions, own_pid=1).restore()
    assert sessions[0].SimpleAudioVolume.sets == []


def test_audio_api_errors_never_crash_jarvis():
    def broken():
        raise OSError("no audio service")

    d = Ducker(broken, own_pid=1)
    d.duck()
    d.restore()


def test_one_bad_session_does_not_stop_the_others():
    class Gone:
        ProcessId = 99

        @property
        def SimpleAudioVolume(self):
            raise OSError("app closed")

    good = FakeSession(10, FakeVolume(1.0))
    d = Ducker(lambda: [Gone(), good], own_pid=1, level=0.3)
    d.duck()
    assert good.SimpleAudioVolume.level == pytest.approx(0.3)
    d.restore()
    assert good.SimpleAudioVolume.level == pytest.approx(1.0)
