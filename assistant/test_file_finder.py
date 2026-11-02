"""Tests for finding and opening files by name, in allowlisted folders only."""

import os
import time

from file_finder import FileFinderTool, find_files


def touch(path, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    t = time.time() - age_days * 86400
    os.utime(path, (t, t))
    return path


def test_finds_by_words_and_extension(tmp_path):
    pdf = touch(tmp_path / "docs" / "Sagar_Resume_2026.pdf")
    touch(tmp_path / "docs" / "resume-notes.docx")
    touch(tmp_path / "holiday.jpg")
    hits = find_files("resume pdf", [tmp_path])
    assert hits[0] == pdf
    assert all(h.name != "holiday.jpg" for h in hits)


def test_newer_file_wins_a_tie(tmp_path):
    old = touch(tmp_path / "report.pdf", age_days=30)
    new = touch(tmp_path / "sub" / "report.pdf", age_days=1)
    assert find_files("report", [tmp_path])[:2] == [new, old]


def test_no_match_and_limit(tmp_path):
    for i in range(10):
        touch(tmp_path / f"photo{i}.png")
    assert find_files("invoice", [tmp_path]) == []
    assert len(find_files("photo", [tmp_path], limit=3)) == 3


def test_skips_hidden_and_dependency_folders(tmp_path):
    touch(tmp_path / ".git" / "resume.pdf")
    touch(tmp_path / "node_modules" / "resume.pdf")
    keep = touch(tmp_path / "resume.pdf")
    assert find_files("resume", [tmp_path]) == [keep]


def test_missing_root_is_ignored(tmp_path):
    keep = touch(tmp_path / "resume.pdf")
    assert find_files("resume", [tmp_path / "nope", tmp_path]) == [keep]


def test_open_opens_best_safe_match(tmp_path):
    touch(tmp_path / "setup_resume.exe", age_days=0)  # never run programs
    pdf = touch(tmp_path / "resume.pdf", age_days=5)
    opened = []
    tool = FileFinderTool(roots=[tmp_path], opener=opened.append)
    r = tool.execute(action="open", query="resume")
    assert r.success and opened == [str(pdf)]


def test_open_refuses_when_only_programs_match(tmp_path):
    touch(tmp_path / "resume.bat")
    opened = []
    tool = FileFinderTool(roots=[tmp_path], opener=opened.append)
    r = tool.execute(action="open", query="resume")
    assert not r.success and opened == []


def test_search_lists_names_and_bad_queries_fail(tmp_path):
    touch(tmp_path / "budget.xlsx")
    tool = FileFinderTool(roots=[tmp_path], opener=lambda p: None)
    r = tool.execute(action="search", query="budget")
    assert r.success and "budget.xlsx" in r.content
    assert not tool.execute(action="search", query="  ").success
    assert not tool.execute(action="search", query="nothing-like-this").success
