"""Small adjustments to OpenJarvis tools for Jarvis.

- LockedMemoryTool: the agent runs tools in parallel, and the stock memory
  tool does read-modify-write without a lock (two adds lose one). It also
  uses the platform default encoding, which breaks Hindi on Windows.
- CompactWebSearch: fewer, shorter results so requests stay under Groq's
  free-tier tokens-per-minute limit.
"""

from __future__ import annotations

import threading
from typing import Any

from openjarvis.core.types import ToolResult
from openjarvis.tools.memory_manage import MemoryManageTool
from openjarvis.tools.web_search import WebSearchTool

_MEMORY_LOCK = threading.Lock()


class LockedMemoryTool(MemoryManageTool):
    """Same spec as memory_manage, but serialized and always UTF-8."""

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="memory_manage", content=content, success=success)

    def _lines(self) -> list[str]:
        if not self._memory_path.exists():
            return []
        text = self._memory_path.read_text(encoding="utf-8")
        return [line for line in text.splitlines() if line.strip()]

    def _write(self, lines: list[str]) -> None:
        self._memory_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "read")
        entry = str(params.get("entry") or "").strip()
        new_entry = str(params.get("new_entry") or "").strip()
        with _MEMORY_LOCK:
            lines = self._lines()
            if action == "read":
                return self._result("\n".join(lines) or "(empty)")
            if not entry:
                return self._result("Entry cannot be empty.", False)
            if action == "add":
                self._write(lines + [f"- {entry}"])
                return self._result(f"Added: {entry}")
            matches = [i for i, line in enumerate(lines) if entry.lower() in line.lower()]
            if not matches:
                return self._result(f"No memory entry matching {entry!r}.", False)
            if action == "remove":
                self._write([line for i, line in enumerate(lines) if i not in matches])
                return self._result(f"Removed {len(matches)} entry.")
            if action == "update" and new_entry:
                lines[matches[0]] = f"- {new_entry}"
                self._write(lines)
                return self._result(f"Updated: {new_entry}")
            return self._result(f"Unknown or incomplete action {action!r}.", False)


class CompactWebSearch(WebSearchTool):
    MAX_RESULTS = 3
    MAX_CHARS = 1200

    def execute(self, **params: Any) -> ToolResult:
        params["max_results"] = self.MAX_RESULTS
        result = super().execute(**params)
        if len(result.content) > self.MAX_CHARS:
            result.content = result.content[: self.MAX_CHARS] + " [truncated]"
        return result
