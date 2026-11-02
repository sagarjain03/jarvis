"""Tests for the clipboard tool, using a fake clipboard."""

from clipboard_tool import MAX_CLIP_CHARS, ClipboardTool


class FakeClip:
    def __init__(self, text=""):
        self.text = text

    def read(self):
        return self.text

    def write(self, text):
        self.text = text


def make(text=""):
    clip = FakeClip(text)
    return ClipboardTool(read=clip.read, write=clip.write), clip


def test_read_returns_clipboard_text():
    tool, _ = make("Meeting moved to 5 pm.")
    r = tool.execute(action="read")
    assert r.success and "Meeting moved to 5 pm." in r.content


def test_read_long_text_is_capped():
    tool, _ = make("x" * (MAX_CLIP_CHARS + 500))
    r = tool.execute(action="read")
    assert r.content.count("x") == MAX_CLIP_CHARS and "truncated" in r.content


def test_empty_clipboard():
    tool, _ = make("   ")
    r = tool.execute(action="read")
    assert not r.success and "empty" in r.content.lower()


def test_write_puts_text_on_clipboard():
    tool, clip = make()
    r = tool.execute(action="write", text="नमस्ते, see you at 5.")
    assert r.success and clip.text == "नमस्ते, see you at 5."


def test_write_needs_text_and_unknown_action_fails():
    tool, _ = make()
    assert not tool.execute(action="write", text="").success
    assert not tool.execute(action="delete").success


def test_clipboard_errors_are_reported():
    def broken(*args):
        raise OSError("clipboard busy")

    tool = ClipboardTool(read=broken, write=broken)
    assert not tool.execute(action="read").success
    assert not tool.execute(action="write", text="hi").success
