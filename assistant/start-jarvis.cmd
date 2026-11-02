@echo off
title Jarvis
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
uv run --project "D:\jarvis\OpenJarvis" --with openwakeword --with PySide6 --with edge-tts --with pycaw --with pillow --with icalendar --with recurring-ical-events python hey_jarvis.py
if not defined JARVIS_HIDDEN pause
