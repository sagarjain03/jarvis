"""Tests for the look_at_screen tool. No real screenshots or network."""

import base64
import io
from dataclasses import dataclass

from PIL import Image

from vision import VISION_MODEL, ScreenTool, encode_screenshot


@dataclass
class _Resp:
    status_code: int
    payload: dict

    def json(self):
        return self.payload


def test_screenshot_is_shrunk_to_a_small_jpeg():
    jpeg = encode_screenshot(Image.new("RGB", (3840, 2160), "white"))
    img = Image.open(io.BytesIO(jpeg))
    assert img.format == "JPEG"
    assert max(img.size) == 1280


def test_tool_sends_question_and_image_and_returns_answer():
    sent = {}

    def post(url, **kw):
        sent.update(url=url, **kw)
        return _Resp(200, {"choices": [{"message": {"content": "VS Code is open."}}]})

    tool = ScreenTool(api_key="k", grab=lambda: Image.new("RGB", (100, 50)), post=post)
    result = tool.execute(question="What is on my screen?")
    assert result.success and result.content == "VS Code is open."
    body = sent["json"]
    assert body["model"] == VISION_MODEL
    parts = body["messages"][-1]["content"]
    assert any("What is on my screen?" in p.get("text", "") for p in parts)
    url = next(p["image_url"]["url"] for p in parts if p["type"] == "image_url")
    assert url.startswith("data:image/jpeg;base64,")
    base64.b64decode(url.split(",", 1)[1])
    assert sent["headers"]["Authorization"] == "Bearer k"


def test_tool_reports_failure_without_leaking_details():
    tool = ScreenTool(api_key="k", grab=lambda: Image.new("RGB", (10, 10)),
                      post=lambda url, **kw: _Resp(500, {"error": "secret details"}))
    result = tool.execute(question="?")
    assert not result.success and "secret" not in result.content


def test_tool_without_key_or_screen_fails_gracefully():
    assert not ScreenTool(api_key="", grab=lambda: None, post=None).execute(question="?").success

    def broken():
        raise OSError("screen locked")

    assert not ScreenTool(api_key="k", grab=broken, post=None).execute(question="?").success
