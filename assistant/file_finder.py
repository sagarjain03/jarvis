"""Find and open the user's files by name, only inside their personal folders.

Only documents and media are ever opened, never programs or scripts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_HOME = Path.home()
DEFAULT_ROOTS = [
    _HOME / name
    for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
] + [_HOME / "OneDrive" / name for name in ("Desktop", "Documents", "Pictures")]

SAFE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".txt", ".md", ".rtf", ".odt",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic",
    ".mp3", ".wav", ".m4a", ".flac", ".mp4", ".mkv", ".avi", ".mov", ".webm",
}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", "AppData", "$RECYCLE.BIN"}
MAX_DEPTH = 5
MAX_FILES = 50_000  # keeps a search to a second or two on huge folders

_WORD = re.compile(r"[^\W_]+")


def _walk(roots: Iterable[Path]) -> Iterable[Path]:
    seen = 0
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            dirs[:] = [] if depth >= MAX_DEPTH else [
                d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
            ]
            for name in files:
                seen += 1
                if seen > MAX_FILES:
                    return
                yield Path(dirpath) / name


def find_files(query: str, roots: Iterable[Path], limit: int = 5) -> list[Path]:
    """Best matches first: most query words in the file name, then newest."""
    words = _WORD.findall(query.lower())
    if not words:
        return []
    scored = []
    for path in _walk(roots):
        name = path.name.lower()
        hits = sum(w in name for w in words)
        if hits:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            scored.append((hits, mtime, path))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [path for _, _, path in scored[:limit]]


class FileFinderTool(BaseTool):
    tool_id = "find_file"

    def __init__(
        self,
        roots: Iterable[Path] = DEFAULT_ROOTS,
        opener: Callable[[str], Any] = os.startfile,
    ) -> None:
        self._roots = list(roots)
        self._open = opener

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="find_file",
            description=(
                "Find the user's files by name in Desktop, Documents, Downloads, "
                "Pictures, Music and Videos. 'search' lists matches; 'open' opens "
                "the best match (documents and media only)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["search", "open"]},
                    "query": {
                        "type": "string",
                        "description": "Key words of the file name in English, plus type if said, e.g. 'resume pdf'.",
                    },
                },
                "required": ["action", "query"],
            },
            category="system",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="find_file", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action")
        query = str(params.get("query") or "").strip()
        if not query:
            return self._result("Which file? Tell me a word from its name.", False)
        hits = find_files(query, self._roots, limit=10)
        if not hits:
            return self._result(f"No file matching {query!r} in your folders.", False)
        if action == "search":
            return self._result("; ".join(f"{p.name} (in {p.parent.name})" for p in hits[:5]))
        if action == "open":
            safe = [p for p in hits if p.suffix.lower() in SAFE_EXTENSIONS]
            if not safe:
                return self._result("Only programs or scripts matched; I don't open those.", False)
            try:
                self._open(str(safe[0]))
            except OSError as exc:
                return self._result(f"Couldn't open it: {exc}", False)
            return self._result(f"Opened {safe[0].name}.")
        return self._result(f"Unknown action {action!r}.", False)
