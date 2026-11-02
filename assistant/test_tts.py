"""Tests for text-to-speech selection: Edge TTS first, Kokoro fallback. No network."""

import numpy as np

from tts import EDGE_ENGLISH, EDGE_HINDI, Speaker

AUDIO = (np.zeros(10, dtype=np.float32), 24000)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_english_uses_edge_english_voice():
    calls = []
    s = Speaker(cloud=lambda text, voice: calls.append((text, voice)) or AUDIO,
                local=lambda text: AUDIO)
    assert s.synthesize("Hello Master.") is AUDIO
    assert calls == [("Hello Master.", EDGE_ENGLISH)]


def test_hindi_uses_edge_hindi_voice():
    calls = []
    s = Speaker(cloud=lambda text, voice: calls.append(voice) or AUDIO, local=lambda text: AUDIO)
    s.synthesize("आज धूप है।")
    assert calls == [EDGE_HINDI]


def test_falls_back_to_local_when_cloud_fails():
    def cloud(text, voice):
        raise OSError("offline")

    local_calls = []
    s = Speaker(cloud=cloud, local=lambda text: local_calls.append(text) or AUDIO)
    assert s.synthesize("Hi.") is AUDIO
    assert local_calls == ["Hi."]


def test_skips_cloud_for_a_while_after_failure_then_retries():
    clock = Clock()
    cloud_calls = []

    def cloud(text, voice):
        cloud_calls.append(text)
        raise OSError("offline")

    s = Speaker(cloud=cloud, local=lambda text: AUDIO, now=clock, retry_after=60)
    s.synthesize("one")
    clock.t = 30
    s.synthesize("two")  # offline: don't wait for another timeout
    assert cloud_calls == ["one"]
    clock.t = 61
    s.synthesize("three")
    assert cloud_calls == ["one", "three"]


def test_cloud_disabled_uses_local_only():
    def cloud(text, voice):
        raise AssertionError("must not call Edge")

    s = Speaker(cloud=cloud, local=lambda text: AUDIO, use_cloud=False)
    assert s.synthesize("Hi.") is AUDIO
