"""A simple to-do list Jarvis keeps for you (voice and Telegram share it)."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

DEFAULT_PATH = Path.home() / ".openjarvis" / "jarvis_todo.json"


@dataclass
class Item:
    id: str
    text: str
    done: bool = False


class TodoStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._items: list[Item] = []
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8") or "[]")
            self._items = [Item(**i) for i in raw]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([asdict(i) for i in self._items], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, text: str) -> Item:
        with self._lock:
            item = Item(uuid.uuid4().hex[:6], text.strip())
            self._items.append(item)
            self._save()
            return item

    def open_items(self) -> list[Item]:
        with self._lock:
            return [i for i in self._items if not i.done]

    def complete(self, ref: str) -> Item | None:
        """Tick off an item by its number in the open list or by words in it."""
        with self._lock:
            open_items = [i for i in self._items if not i.done]
            ref = ref.strip().lower()
            match = None
            if ref.isdigit() and 1 <= int(ref) <= len(open_items):
                match = open_items[int(ref) - 1]
            else:
                match = next((i for i in open_items if ref and ref in i.text.lower()), None)
            if match is not None:
                match.done = True
                self._save()
            return match

    def clear(self, everything: bool = False) -> int:
        """Remove finished items (or all of them). Returns how many went."""
        with self._lock:
            keep = [] if everything else [i for i in self._items if not i.done]
            removed = len(self._items) - len(keep)
            self._items = keep
            self._save()
            return removed


class TodoTool(BaseTool):
    tool_id = "todo"

    def __init__(self, store: TodoStore) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="todo",
            description=(
                "The user's to-do / shopping list. 'add' an item, 'list' open "
                "items, 'done' ticks one off (text = words from it or its "
                "number), 'clear' removes finished items (everything=true "
                "empties the whole list)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list", "done", "clear"]},
                    "text": {"type": "string"},
                    "everything": {"type": "boolean"},
                },
                "required": ["action"],
            },
            category="productivity",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="todo", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action")
        text = str(params.get("text") or "").strip()
        if action == "add":
            if not text:
                return self._result("What should I add?", False)
            self._store.add(text)
            return self._result(f"Added {text!r} to your list.")
        if action == "list":
            items = self._store.open_items()
            if not items:
                return self._result("Your to-do list is empty.")
            return self._result("; ".join(f"{n}. {i.text}" for n, i in enumerate(items, 1)))
        if action == "done":
            item = self._store.complete(text)
            if item is None:
                return self._result(f"No open item matching {text!r}.", False)
            return self._result(f"Ticked off {item.text!r}.")
        if action == "clear":
            removed = self._store.clear(everything=bool(params.get("everything")))
            return self._result(f"Removed {removed} item(s).")
        return self._result(f"Unknown action {action!r}.", False)
