# Jarvis — Upgrade TODO

Order = priority. Har item: tests pehle (pure logic tested, side effects stubbed), phir code.
Saare tests: `uv run --project D:\jarvis\OpenJarvis --with pytest pytest -q -p no:cacheprovider`
Naye packages → `start-jarvis.cmd` mein `--with <pkg>` add karna (aur us env mein verify).
Koi secret file mein nahi — sirf env vars.

## Phase 1 — Feel like real Jarvis (experience)

- [x] **1. Barge-in (beech mein rokna)**
  - `say()` playback ke dauraan wake-word detector parallel chale; "Jarvis" sunte hi `sd.stop()` + listening.
  - Files: `hey_jarvis.py` (say/converse), `session.py` (interrupt flag logic).
  - Test: interrupt event set hone pe remaining sentences skip hote hain (fake player).
  - Risk: speaker ki apni awaaz se false trigger → threshold barge-in ke liye zyada (e.g. 0.6).

- [x] **2. Edge TTS (free, fast, Hindi voices)**
  - Naya `tts.py`: Edge TTS primary (`en-GB-RyanNeural` / `hi-IN-MadhurNeural`), Kokoro offline fallback.
  - Package: `edge-tts`. Privacy: reply text Microsoft ko jaata hai → `CLOUD_TTS` flag.
  - Test: voice selection (Hindi vs English), fallback on network error (fake synth).

- [x] **3. Faster end-of-speech**
  - `SpeechGate.silence_chunks` 23 (~1.5 s) → ~12 (~0.8 s); constant naam se configurable.
  - Test: existing gate tests update.

- [x] **4. Noise-floor auto-calibration**
  - Start pe ~1 s mic sample → `threshold = max(500, noise_rms * 3)`.
  - `session.py`: pure `calibrate_threshold(levels)`.
  - Test: quiet room / noisy room cases.

- [x] **5. Listening chime**
  - Chhota generated tone (numpy, koi file nahi) jab listening shuru ho.
  - Test: tone generator length/amplitude.

- [x] **6. Audio ducking**
  - Listening ke waqt system volume ~30% tak, baad mein restore (pycaw / Windows Core Audio).
  - Package: `pycaw`. Test: duck/restore state machine (fake volume API), restore on exception.

## Phase 2 — Smart abilities

- [ ] **7. Screen dekhna (vision)**
  - Tool `look_at_screen(question)`: screenshot → Groq vision model → answer.
  - Privacy: screenshot Groq ko jaata hai; sirf jab user khud poochhe.
  - Test: request payload build (fake post), image resize/compress.

- [ ] **8. Clipboard tool**
  - Tool `clipboard(action=read)` → model summarize/translate/reply kare; optional `write`.
  - Test: read/write via fake clipboard, length cap.

- [ ] **9. File finder**
  - Tool `find_file(query)` sirf allowlisted folders (Desktop, Documents, Downloads) mein; best match open.
  - Test: fuzzy match ranking, allowlist ke bahar kuch nahi, max results.

- [ ] **10. Routines**
  - `~/.openjarvis/jarvis_routines.json` (work mode, night mode…) → existing `pc_control` actions ki list.
  - Sirf allowlisted actions; power actions routine mein allowed nahi.
  - Test: routine parsing, unknown action reject.

- [ ] **11. Google Calendar**
  - Tool `calendar(today|tomorrow|next)` read-only (Google Calendar API / ICS secret URL via env var).
  - Morning briefing prompt mein add.
  - Test: event formatting, timezone (UTC → local display).

- [ ] **12. Offline fallback (Ollama)**
  - Groq network error / down → local Ollama model se jawab (`brain.py`).
  - Test: fallback trigger on connection error, not on rate limit.

## Phase 3 — Daily life

- [ ] **13. Notes / to-do list**
  - Tool `todo(add|list|done|clear)` → `~/.openjarvis/jarvis_todo.json`; Telegram se bhi chale.
  - Test: store add/list/done, locking, Hindi text.

- [ ] **14. Proactive alerts**
  - Background thread: battery < 20% (once), meeting 10 min pehle (item 11 ke baad), evening summary (optional time).
  - Test: battery alert sirf ek baar fire, re-arm on charge.

- [ ] **15. System tray icon**
  - PySide6 `QSystemTrayIcon` (already installed): Pause listening / Resume / Quit; console window hide (`pythonw` launcher).
  - Test: pause flag logic; manual check of tray.

## Done criteria (har item)
- [ ] Tests green
- [ ] Launcher env mein import OK
- [ ] Live voice test by user
