@echo off
title Jarvis
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
uv run --project "D:\jarvis\OpenJarvis" --with openwakeword python hey_jarvis.py
pause
