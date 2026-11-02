"""Clipboard tool: read copied text (to summarize/translate/reply) or copy text."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Callable

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

MAX_CLIP_CHARS = 4000  # enough for an email or article section, not a book
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def _win32() -> tuple[Any, Any]:
    # Private DLL handles so these argtypes don't affect other modules.
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.GetClipboardData.restype = ctypes.c_void_p
    u32.GetClipboardData.argtypes = [wintypes.UINT]
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    return u32, k32


def _read() -> str:
    u32, k32 = _win32()
    if not u32.OpenClipboard(None):
        raise OSError("clipboard is busy")
    try:
        handle = u32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = k32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k32.GlobalUnlock(handle)
    finally:
        u32.CloseClipboard()


def _write(text: str) -> None:
    u32, k32 = _win32()
    data = text.encode("utf-16-le") + b"\0\0"
    handle = k32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
    ptr = k32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    k32.GlobalUnlock(handle)
    if not u32.OpenClipboard(None):
        raise OSError("clipboard is busy")
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(_CF_UNICODETEXT, handle):
            raise OSError("couldn't set clipboard")
    finally:
        u32.CloseClipboard()


class ClipboardTool(BaseTool):
    tool_id = "clipboard"

    def __init__(self, read: Callable[[], str] = _read, write: Callable[[str], None] = _write) -> None:
        self._read = read
        self._write = write

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard",
            description=(
                "'read' gets the text the user copied, so you can summarize, "
                "translate, explain, or reply to it. 'write' copies text (e.g. a "
                "reply you drafted) so the user can paste it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["read", "write"]},
                    "text": {"type": "string", "description": "Text to copy, for 'write'."},
                },
                "required": ["action"],
            },
            category="productivity",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="clipboard", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action")
        try:
            if action == "read":
                text = (self._read() or "").strip()
                if not text:
                    return self._result("The clipboard is empty (or holds no text).", False)
                if len(text) > MAX_CLIP_CHARS:
                    return self._result(text[:MAX_CLIP_CHARS] + " [truncated]")
                return self._result(text)
            if action == "write":
                text = str(params.get("text") or "")
                if not text.strip():
                    return self._result("Nothing to copy.", False)
                self._write(text)
                return self._result("Copied to the clipboard.")
        except OSError as exc:
            return self._result(f"Clipboard unavailable: {exc}", False)
        return self._result(f"Unknown action {action!r}.", False)
