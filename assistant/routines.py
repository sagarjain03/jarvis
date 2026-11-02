"""Routines: one phrase ("work mode") runs several safe pc_control actions.

Edit ~/.openjarvis/jarvis_routines.json to make your own, e.g.
{"gym mode": [["play_youtube", "workout songs"], ["volume_up", ""]]}
Power actions are never allowed in a routine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

from pc_control import ACTIONS, POWER_ACTIONS, PcControlTool

DEFAULT_PATH = Path.home() / ".openjarvis" / "jarvis_routines.json"
FORBIDDEN = set(POWER_ACTIONS) | {"confirm_power"}

DEFAULT_ROUTINES = {
    "work mode": [["open_website", "gmail"], ["open_website", "github"], ["set_brightness", "80"]],
    "study mode": [["open_website", "wikipedia"], ["play_youtube", "lofi study music"]],
    "night mode": [["set_brightness", "30"], ["volume_down", ""], ["volume_down", ""]],
}

Routines = dict[str, list[tuple[str, str]]]


class RoutineError(ValueError):
    pass


def validate(raw: dict) -> Routines:
    routines: Routines = {}
    for name, steps in raw.items():
        checked = []
        for step in steps:
            action, target = (list(step) + [""])[:2]
            if action not in ACTIONS or action in FORBIDDEN:
                raise RoutineError(f"Routine {name!r}: action {action!r} is not allowed.")
            checked.append((str(action), str(target)))
        routines[str(name).strip().lower()] = checked
    return routines


def load_routines(path: Path = DEFAULT_PATH) -> Routines:
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_ROUTINES, indent=2), encoding="utf-8")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def run_pc_step(action: str, target: str) -> str:
    result = PcControlTool().execute(action=action, target=target)
    if not result.success:
        raise RuntimeError(result.content)
    return result.content


class RoutineTool(BaseTool):
    tool_id = "routine"

    def __init__(self, routines: Routines, run_step: Callable[[str, str], str] = run_pc_step) -> None:
        self._routines = routines
        self._run_step = run_step

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="routine",
            description=(
                "Run a named routine of PC actions ('work mode', 'night mode'...) "
                f"or list them. Routines: {', '.join(sorted(self._routines))}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["run", "list"]},
                    "name": {"type": "string"},
                },
                "required": ["action"],
            },
            category="system",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="routine", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        available = ", ".join(sorted(self._routines)) or "none"
        if params.get("action") == "list":
            return self._result(f"Routines: {available}.")
        name = str(params.get("name") or "").strip().lower()
        steps = self._routines.get(name)
        if steps is None:
            return self._result(f"No routine called {name!r}. Available: {available}.", False)
        failed = []
        for action, target in steps:
            try:
                self._run_step(action, target)
            except Exception:  # one broken step must not stop the rest
                failed.append(f"{action} {target}".strip())
        done = len(steps) - len(failed)
        summary = f"Ran {name}: {done} of {len(steps)} steps done."
        if failed:
            summary += f" Failed: {', '.join(failed)}."
        return self._result(summary, success=done > 0)
