"""Tests for routines: named lists of safe pc_control actions."""

import json

import pytest

from routines import DEFAULT_ROUTINES, RoutineError, RoutineTool, load_routines, validate


def test_defaults_are_written_when_file_missing(tmp_path):
    path = tmp_path / "routines.json"
    routines = load_routines(path)
    assert routines == validate(DEFAULT_ROUTINES)
    assert "work mode" in routines and "night mode" in routines
    assert json.loads(path.read_text(encoding="utf-8"))


def test_user_file_is_loaded(tmp_path):
    path = tmp_path / "routines.json"
    path.write_text(json.dumps({"Study Mode": [["open_website", "wikipedia"]]}), encoding="utf-8")
    assert load_routines(path) == {"study mode": [("open_website", "wikipedia")]}


@pytest.mark.parametrize(
    "step", [["format_disk", ""], ["shutdown", ""], ["confirm_power", ""], ["restart", ""], ["sleep", ""]]
)
def test_unsafe_or_unknown_actions_are_rejected(step):
    with pytest.raises(RoutineError):
        validate({"bad": [step]})


def test_run_executes_steps_in_order():
    calls = []

    def run_step(action, target):
        calls.append((action, target))
        return f"did {action}"

    tool = RoutineTool({"night mode": [("set_brightness", "30"), ("volume_down", "")]}, run_step)
    r = tool.execute(action="run", name="Night Mode")
    assert r.success
    assert calls == [("set_brightness", "30"), ("volume_down", "")]


def test_failing_step_does_not_stop_the_rest():
    calls = []

    def run_step(action, target):
        calls.append(action)
        if action == "open_website":
            raise OSError("no browser")
        return "ok"

    tool = RoutineTool({"work mode": [("open_website", "gmail"), ("volume_down", "")]}, run_step)
    r = tool.execute(action="run", name="work mode")
    assert calls == ["open_website", "volume_down"]
    assert "1 of 2" in r.content


def test_unknown_routine_lists_available_and_list_action():
    tool = RoutineTool({"work mode": [("volume_down", "")]}, lambda a, t: "ok")
    r = tool.execute(action="run", name="party mode")
    assert not r.success and "work mode" in r.content
    assert "work mode" in tool.execute(action="list").content
