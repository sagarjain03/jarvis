@echo off
title Jarvis
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
uv run --project "D:\jarvis\OpenJarvis" --with openwakeword --with PySide6 --with edge-tts --with pycaw python hey_jarvis.py
pause
