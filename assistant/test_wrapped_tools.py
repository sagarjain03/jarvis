"""Tests for the thread-safe memory tool and the compact web search."""

import threading

from openjarvis.core.types import ToolResult

from wrapped_tools import CompactWebSearch, LockedMemoryTool


def test_parallel_adds_are_all_kept(tmp_path):
    tool = LockedMemoryTool(memory_path=tmp_path / "facts.md")
    facts = [f"fact number {i}" for i in range(20)]
    threads = [threading.Thread(target=tool.execute, kwargs={"action": "add", "entry": f}) for f in facts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = (tmp_path / "facts.md").read_text(encoding="utf-8")
    assert all(f in saved for f in facts)


def test_memory_handles_hindi(tmp_path):
    tool = LockedMemoryTool(memory_path=tmp_path / "facts.md")
    assert tool.execute(action="add", entry="पसंदीदा गाना केसरिया है").success
    assert "केसरिया" in tool.execute(action="read").content


def test_compact_web_search_truncates_long_results(monkeypatch):
    long = "x" * 5000
    monkeypatch.setattr(
        "openjarvis.tools.web_search.WebSearchTool.execute",
        lambda self, **p: ToolResult(tool_name="web_search", content=long),
    )
    r = CompactWebSearch().execute(query="news")
    assert len(r.content) <= CompactWebSearch.MAX_CHARS + 20
    assert r.content.endswith("[truncated]")


def test_compact_web_search_keeps_short_results(monkeypatch):
    monkeypatch.setattr(
        "openjarvis.tools.web_search.WebSearchTool.execute",
        lambda self, **p: ToolResult(tool_name="web_search", content="short"),
    )
    assert CompactWebSearch().execute(query="news").content == "short"


def test_compact_web_search_asks_for_few_results(monkeypatch):
    seen = {}

    def fake(self, **p):
        seen.update(p)
        return ToolResult(tool_name="web_search", content="ok")

    monkeypatch.setattr("openjarvis.tools.web_search.WebSearchTool.execute", fake)
    CompactWebSearch().execute(query="news", max_results=10)
    assert seen["max_results"] == 3
