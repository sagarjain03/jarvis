"""Tests for the to-do list store and tool."""

import threading

from todo_list import TodoStore, TodoTool


def test_add_list_and_persist(tmp_path):
    path = tmp_path / "todo.json"
    store = TodoStore(path)
    store.add("buy milk")
    store.add("दूध लाना")
    again = TodoStore(path)  # survives restart, Hindi intact
    assert [i.text for i in again.open_items()] == ["buy milk", "दूध लाना"]


def test_complete_by_words_or_number(tmp_path):
    store = TodoStore(tmp_path / "t.json")
    store.add("buy milk")
    store.add("call Rahul about the project")
    assert store.complete("rahul").text == "call Rahul about the project"
    assert store.complete("1").text == "buy milk"  # number as heard in the list
    assert store.open_items() == []
    assert store.complete("nothing like this") is None


def test_clear_removes_done_items_or_everything(tmp_path):
    store = TodoStore(tmp_path / "t.json")
    store.add("a")
    store.add("b")
    store.complete("a")
    assert store.clear() == 1
    assert [i.text for i in store.open_items()] == ["b"]
    assert store.clear(everything=True) == 1
    assert store.open_items() == []


def test_parallel_adds_are_not_lost(tmp_path):
    store = TodoStore(tmp_path / "t.json")
    threads = [threading.Thread(target=store.add, args=(f"item {n}",)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(TodoStore(tmp_path / "t.json").open_items()) == 20


def test_tool_actions(tmp_path):
    tool = TodoTool(TodoStore(tmp_path / "t.json"))
    assert tool.execute(action="add", text="buy milk").success
    assert not tool.execute(action="add", text=" ").success
    listing = tool.execute(action="list").content
    assert "1. buy milk" in listing
    assert tool.execute(action="done", text="milk").success
    assert "empty" in tool.execute(action="list").content.lower()
    assert not tool.execute(action="done", text="milk").success
    assert tool.execute(action="clear").success
    assert not tool.execute(action="fly").success
