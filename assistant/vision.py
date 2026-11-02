"""look_at_screen: answer questions about what's on the screen right now.

Takes a screenshot only when asked, shrinks it to a small JPEG and sends it
to a Groq vision model (~1 s). The screenshot leaves the PC; nothing is saved.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any, Callable

import httpx
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
VISION_MODEL = "qwen/qwen3.8-27b"  # the Groq model that accepts images (checked 2026-11)
MAX_SIDE = 1280  # readable text, ~50 KB upload

_INSTRUCTIONS = (
    "This is a screenshot of the user's Windows screen. Answer their question "
    "about it in one to three short spoken sentences, no markdown. Ignore the "
    "glowing orb overlay near the bottom; that is the assistant itself.\n"
    "Question: "
)


def _grab() -> Any:
    from PIL import ImageGrab

    return ImageGrab.grab()


def encode_screenshot(img: Any) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


class ScreenTool(BaseTool):
    tool_id = "look_at_screen"

    def __init__(
        self,
        api_key: str | None = None,
        grab: Callable[[], Any] = _grab,
        post: Callable[..., Any] = httpx.post,
    ) -> None:
        self._key = (os.environ.get("GROQ_API_KEY", "") if api_key is None else api_key).strip()
        self._grab = grab
        self._post = post

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="look_at_screen",
            description=(
                "Look at the user's screen right now and answer a question about "
                "it: what's open, read or explain an error, summarize the page."
            ),
            parameters={
                "type": "object",
                "properties": {"question": {"type": "string", "description": "What to find out, in English."}},
                "required": ["question"],
            },
            category="system",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="look_at_screen", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        if not self._key:
            return self._result("Screen reading needs GROQ_API_KEY.", False)
        try:
            jpeg = encode_screenshot(self._grab())
        except Exception:
            return self._result("Couldn't take a screenshot (is the screen locked?).", False)
        question = str(params.get("question") or "What is on the screen?")
        try:
            resp = self._post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": VISION_MODEL,
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": _INSTRUCTIONS + question},
                        {"type": "image_url", "image_url": {
                            "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
                    ]}],
                },
                timeout=30,
            )
        except (OSError, httpx.HTTPError):
            return self._result("Screen reading is unavailable right now (network).", False)
        if resp.status_code != 200:
            return self._result("Screen reading is unavailable right now.", False)
        answer = resp.json()["choices"][0]["message"].get("content") or ""
        return self._result(answer.strip() or "I couldn't make out the screen.")
