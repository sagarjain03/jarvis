"""Always-listening "Jarvis" voice assistant built on OpenJarvis.

Say "Jarvis" (or "Hey Jarvis"): Jarvis answers "Yes Master" and the orb
appears. Keep talking — no wake word needed — until you say "Stop Jarvis"
or stay quiet for IDLE_SECONDS. Say "Jarvis" while it talks to cut it off.
Ctrl+C to quit.
"""

from __future__ import annotations

import io
import logging
import os
import queue
import threading
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402
import soundfile as sf  # noqa: E402
from openwakeword.model import Model  # noqa: E402
from rich.console import Console  # noqa: E402

from openjarvis.cli._voice_chat import VoiceSession  # noqa: E402
from openjarvis.core.config import load_config  # noqa: E402
from openjarvis.speech.voice_io import _frames_to_wav, _rms  # noqa: E402

from brain import FACTS_PATH, Brain, build_agent, is_hindi  # noqa: E402
from ducking import Ducker  # noqa: E402
from email_reader import EmailReaderTool  # noqa: E402
from orb_client import OrbClient  # noqa: E402
from pc_control import POWER_GATE, PcControlTool  # noqa: E402
from reminders import ReminderStore, ReminderTool, start_reminder_thread  # noqa: E402
from session import (  # noqa: E402
    Session,
    SpeechGate,
    calibrate_threshold,
    envelope,
    is_stop_command,
    play_all,
    split_sentences,
)
from sounds import chime  # noqa: E402
from stt import Transcriber  # noqa: E402
from telegram_bot import start_telegram  # noqa: E402
from tts import Speaker, edge_synth  # noqa: E402
from wrapped_tools import CompactWebSearch, LockedMemoryTool  # noqa: E402

# "Hey Jarvis" scores ~1.0 and plain "Jarvis" 0.3-1.0 on openWakeWord's
# hey_jarvis model, while ordinary speech scores ~0. Raise if it wakes by mistake.
WAKE_THRESHOLD = 0.3
# Stricter while Jarvis is talking, so its own voice from the speakers
# doesn't cut itself off. Lower if interrupting is hard, raise if it self-stops.
BARGE_THRESHOLD = 0.6
WAKE_CHUNK = 1280  # 80 ms at 16 kHz, what openWakeWord expects
LISTEN_CHUNK = 1024
SAMPLE_RATE = 16000
IDLE_SECONDS = 60  # close the orb after this long without you speaking
# Speech-to-text via Groq (0.3 s, sends your command audio to Groq). False =
# local whisper only: private, but ~3 s ("base") to ~12 s ("small") per command.
CLOUD_STT = True
# Voice via Microsoft Edge (free, ~1.6 s a sentence, sends reply text to
# Microsoft). False = local Kokoro only: private, but up to ~10 s a sentence here.
CLOUD_TTS = True
DUCK_OTHER_APPS = True  # turn music/videos down while you talk to Jarvis
HINDI_VOICE = "hm_omega"  # Kokoro Hindi male; "h" prefix selects the Hindi pipeline
ORB_FPS = 30

console = Console()
orb = OrbClient()
_speech_lock = threading.Lock()  # one voice at a time (replies vs. reminders)
_in_session = threading.Event()
CHIME = chime()


def _kokoro(text: str, voice: VoiceSession) -> tuple[np.ndarray, int]:
    # Reuse the session's already-loaded backend: creating a new Kokoro
    # backend reloads the whole model (seconds per reply on this CPU).
    backend = voice.get_tts_backend()
    if backend is None:
        raise RuntimeError("No text-to-speech backend available.")
    voice_id, speed = voice.voice_for_backend(backend, console)
    if is_hindi(text) and getattr(backend, "backend_id", "") == "kokoro":
        voice_id = HINDI_VOICE
    kwargs = {"output_format": "wav", "speed": speed}
    if voice_id:
        kwargs["voice_id"] = voice_id
    try:
        result = backend.synthesize(text, **kwargs)
    except Exception:
        voice.discard_tts_backend()
        raise
    data, sr = sf.read(io.BytesIO(result.audio), dtype="float32")
    return data, sr


PHRASES = ("Yes Master.", "Goodbye, Master.", "Jarvis online.")
_phrase_audio: dict[str, tuple[np.ndarray, int]] = {}  # filled at start-up


def _audio_for(text: str, speaker: Speaker) -> tuple[np.ndarray, int]:
    return _phrase_audio.get(text) or speaker.synthesize(text)


def _watch_for_wake_word(detector: Model, interrupted: threading.Event, finished: threading.Event) -> None:
    """While Jarvis talks, listen for "Jarvis" and cut the speech off."""
    detector.reset()
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=WAKE_CHUNK) as mic:
            while not finished.is_set():
                frames, _ = mic.read(WAKE_CHUNK)
                if max(detector.predict(np.squeeze(frames)).values()) >= BARGE_THRESHOLD:
                    interrupted.set()
                    sd.stop()
                    return
    except Exception:
        return  # mic unavailable: no barge-in, Jarvis just finishes talking


def _play(item: tuple[np.ndarray, int], interrupted: threading.Event) -> bool:
    data, sr = item
    orb.speaking(envelope(data, sr, fps=ORB_FPS), fps=ORB_FPS)
    sd.play(data, sr)
    if interrupted.wait(len(data) / sr):
        sd.stop()
        return False
    sd.wait()
    return True


def say(text: str, speaker: Speaker, caption: str | None = None, detector: Model | None = None) -> bool:
    """Speak ``text`` while the orb pulses with the voice. False if cut off.

    Sentences are synthesized ahead of playback, so speech starts as soon as
    the first sentence is ready. With a ``detector``, saying "Jarvis" stops it.
    """
    with _speech_lock:
        orb.caption(caption if caption is not None else text)
        sentences = split_sentences(text) or [text]
        ready: queue.Queue = queue.Queue()
        interrupted = threading.Event()
        finished = threading.Event()

        def produce() -> None:
            for sentence in sentences:
                if finished.is_set():
                    break
                try:
                    ready.put(_audio_for(sentence, speaker))
                except Exception as exc:
                    console.print(f"[dim yellow]Voice failed: {exc}[/dim yellow]")
                    break
            ready.put(None)

        threading.Thread(target=produce, name="tts", daemon=True).start()
        watcher = None
        if detector is not None:
            watcher = threading.Thread(
                target=_watch_for_wake_word, args=(detector, interrupted, finished), name="barge-in", daemon=True
            )
            watcher.start()
        try:
            return play_all(iter(ready.get, None), lambda item: _play(item, interrupted), interrupted)
        finally:
            finished.set()
            if watcher is not None:
                watcher.join(timeout=1)


def load_wake_detector() -> Model:
    """Load the "hey jarvis" model, downloading it first if this env lacks it.

    openWakeWord keeps models inside its own package folder, so every new uv
    environment (e.g. after adding a --with package) starts without them.
    """
    try:
        return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception:
        from openwakeword.utils import download_models

        console.print("[dim]Downloading the wake-word model (one time)…[/dim]")
        download_models(["hey_jarvis"])
        return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")


def wait_for_wake_word(detector: Model) -> None:
    detector.reset()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=WAKE_CHUNK) as mic:
        while True:
            frames, _ = mic.read(WAKE_CHUNK)
            scores = detector.predict(np.squeeze(frames))
            if max(scores.values()) >= WAKE_THRESHOLD:
                return


def measure_threshold(seconds: float = 1.0) -> float:
    """Listen to the room briefly and set the speech threshold above its noise."""
    levels = []
    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=LISTEN_CHUNK) as mic:
            for _ in range(int(seconds * SAMPLE_RATE / LISTEN_CHUNK)):
                raw, _ = mic.read(LISTEN_CHUNK)
                levels.append(_rms(bytes(raw)))
    except Exception:
        pass  # no mic yet: calibrate_threshold falls back to the default
    return calibrate_threshold(levels)


def listen(threshold: float) -> bytes | None:
    """Record one utterance (WAV bytes), or None if nothing was said for ~8 s."""
    gate = SpeechGate(threshold=threshold)
    frames: list[bytes] = []
    with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=LISTEN_CHUNK) as mic:
        while True:
            raw, _ = mic.read(LISTEN_CHUNK)
            data = bytes(raw)
            frames.append(data)
            level = _rms(data)
            orb.level(min(1.0, level / 3000))
            state = gate.feed(level)
            if state == "no_speech":
                return None
            if state == "done":
                orb.level(0)
                return _frames_to_wav(frames, SAMPLE_RATE)
            if state == "waiting":
                frames = frames[-8:]  # keep a little lead-in before speech starts


def converse(
    brain: Brain, speaker: Speaker, stt: Transcriber, detector: Model, threshold: float, ducker: Ducker | None
) -> None:
    """One wake-up: keep listening and answering until stop or inactivity."""
    _in_session.set()
    if ducker is not None:
        ducker.duck()
    orb.state("listening")
    say("Yes Master.", speaker)
    session = Session(idle_seconds=IDLE_SECONDS)
    try:
        while True:
            orb.state("listening")
            orb.caption("")
            console.print("[dim cyan]Listening…[/dim cyan]")
            sd.play(*CHIME)  # "your turn"
            sd.wait()
            audio = listen(threshold)
            text = stt.transcribe(audio) if audio else ""
            if len(text) < 2:  # silence, or a stray noise transcribed as "."
                if session.expired():
                    console.print("[dim]No activity — going to sleep.[/dim]")
                    return
                continue
            session.touch()
            console.print(f"[bold]You:[/bold] {text}")
            if is_stop_command(text):
                say("Goodbye, Master.", speaker)
                return

            orb.state("thinking")
            orb.caption(text)
            reply = brain.reply(text)
            if brain.last_error is not None:
                console.print(f"[red]Error: {brain.last_error}[/red]")
            console.print(f"[bold cyan]Jarvis:[/bold cyan] {reply}")
            if not say(reply, speaker, detector=detector):
                console.print("[dim](interrupted)[/dim]")
            session.touch()  # the idle clock starts after Jarvis finishes talking
    finally:
        if ducker is not None:
            ducker.restore()
        orb.hide()
        _in_session.clear()


def main() -> None:
    config = load_config()
    store = ReminderStore()
    tools = [
        PcControlTool(),
        CompactWebSearch(),
        ReminderTool(store),
        EmailReaderTool(),
        LockedMemoryTool(memory_path=FACTS_PATH),
    ]
    agent, engine_key, model = build_agent(config, tools)
    brain = Brain(agent, on_turn=POWER_GATE.new_turn)
    voice = VoiceSession(config)
    speaker = Speaker(cloud=edge_synth, local=lambda text: _kokoro(text, voice), use_cloud=CLOUD_TTS)
    detector = load_wake_detector()
    stt = Transcriber(
        os.environ.get("GROQ_API_KEY", ""),
        local=voice.get_stt_backend,
        use_cloud=CLOUD_STT,
        language=voice.get_stt_language() or None,
    )
    ducker = Ducker() if DUCK_OTHER_APPS else None

    console.print("[dim]Measuring room noise (stay quiet for a second)…[/dim]")
    threshold = measure_threshold()
    console.print(f"[dim]Speech threshold: {threshold:.0f}[/dim]")

    console.print("[dim]Warming up the voice…[/dim]")
    try:
        if not CLOUD_TTS:
            _kokoro("तैयार।", voice)  # loads the Hindi pipeline now, not mid-reply (~30 s)
        for phrase in PHRASES:  # pre-recorded so they play instantly
            _phrase_audio[phrase] = speaker.synthesize(phrase)
    except Exception as exc:
        console.print(f"[dim yellow]Voice warm-up failed: {exc}[/dim yellow]")

    telegram = start_telegram(brain.reply)
    if telegram is None:
        console.print("[dim]Telegram: off (set TELEGRAM_BOT_TOKEN to enable)[/dim]")
    elif not telegram[1]:
        console.print("[yellow]Telegram: setup mode — message your bot to get your chat ID[/yellow]")
    else:
        console.print("[green]Telegram: on[/green]")

    def on_reminder(r) -> None:
        console.print(f"\n[bold yellow]⏰ Reminder:[/bold yellow] {r.message}")
        if telegram is not None:
            for chat in telegram[1]:
                telegram[0].send(chat, f"⏰ Reminder: {r.message}")
        say(f"Reminder, Master: {r.message}", speaker, caption=f"⏰ {r.message}")
        if not _in_session.is_set():
            orb.hide()

    start_reminder_thread(store, on_reminder)

    console.print(f"[green bold]Jarvis is ready[/green bold]  ({engine_key}: {model})")
    say("Jarvis online.", speaker)
    orb.hide()

    try:
        while True:
            console.print("\n[dim]Say \"Jarvis\"…  (Ctrl+C to quit)[/dim]")
            wait_for_wake_word(detector)
            converse(brain, speaker, stt, detector, threshold, ducker)
    finally:
        orb.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
