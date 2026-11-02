"""Tests for speech-to-text: Groq first, local whisper as fallback. No network."""

from dataclasses import dataclass

from stt import Transcriber


@dataclass
class _Resp:
    status_code: int
    payload: dict

    def json(self):
        return self.payload


@dataclass
class _LocalResult:
    text: str


class FakeLocal:
    def __init__(self, text="local text"):
        self.calls = 0
        self.text = text

    def transcribe(self, audio, format="wav", language=None):
        self.calls += 1
        return _LocalResult(self.text)


def test_uses_groq_when_available():
    sent = {}

    def post(url, **kw):
        sent.update(url=url, **kw)
        return _Resp(200, {"text": " Jarvis, open YouTube "})

    local = FakeLocal()
    t = Transcriber(api_key="k", local=lambda: local, post=post)
    assert t.transcribe(b"wav") == "Jarvis, open YouTube"
    assert local.calls == 0
    assert sent["url"].endswith("/audio/transcriptions")
    assert sent["data"]["model"] == "whisper-large-v3-turbo"
    # An English vocabulary prompt pushed Hinglish into wrong English words
    # ("Indore ka weather" -> "Indoor Car Weather"), so none is sent.
    assert "prompt" not in sent["data"]
    assert sent["headers"]["Authorization"] == "Bearer k"


def test_falls_back_to_local_on_error_status():
    local = FakeLocal()
    t = Transcriber(api_key="k", local=lambda: local, post=lambda url, **kw: _Resp(429, {}))
    assert t.transcribe(b"wav") == "local text"
    assert local.calls == 1


def test_falls_back_to_local_on_network_error():
    def post(url, **kw):
        raise OSError("offline")

    local = FakeLocal()
    t = Transcriber(api_key="k", local=lambda: local, post=post)
    assert t.transcribe(b"wav") == "local text"


def test_no_key_or_cloud_disabled_uses_local_only():
    def post(url, **kw):
        raise AssertionError("must not call Groq")

    for t in (Transcriber(api_key="", local=FakeLocal, post=post),
              Transcriber(api_key="k", local=FakeLocal, post=post, use_cloud=False)):
        assert t.transcribe(b"wav") == "local text"


def test_local_backend_is_created_once():
    made = []

    def make():
        made.append(1)
        return FakeLocal()

    t = Transcriber(api_key="", local=make)
    t.transcribe(b"a")
    t.transcribe(b"b")
    assert made == [1]


def test_everything_failing_returns_empty():
    class Broken:
        def transcribe(self, *a, **k):
            raise RuntimeError("model missing")

    t = Transcriber(api_key="", local=Broken)
    assert t.transcribe(b"wav") == ""
