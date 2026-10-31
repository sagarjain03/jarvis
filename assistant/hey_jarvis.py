"""Always-listening "Hey Jarvis" voice assistant built on OpenJarvis.

Say "Hey Jarvis", wait for the beep, then speak your request.
Ctrl+C to quit.
"""

from __future__ import annotations

import logging
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402
import winsound  # noqa: E402
from openwakeword.model import Model  # noqa: E402
from rich.console import Console  # noqa: E402

import openjarvis.agents  # noqa: E402,F401  (registers agents)
from openjarvis.cli._voice_chat import VOICE_EXIT, VoiceSession, record_voice, speak  # noqa: E402
from openjarvis.core.config import load_config  # noqa: E402
from openjarvis.core.registry import AgentRegistry  # noqa: E402
from openjarvis.engine._discovery import get_engine  # noqa: E402
from openjarvis.tools.web_search import WebSearchTool  # noqa: E402

from pc_control import PcControlTool  # noqa: E402

WAKE_THRESHOLD = 0.5
CHUNK = 1280  # 80 ms at 16 kHz, what openWakeWord expects

SYSTEM_PROMPT = (
    "You are Jarvis, a smart, helpful voice assistant on the user's Windows PC. "
    "The user may speak English, Hindi, or Hinglish; always reply in simple "
    "English. Your replies are spoken aloud, so keep them to one to three short "
    "sentences with no markdown, lists, URLs, or emojis.\n"
    "- Answer general questions from your own knowledge.\n"
    "- For news, scores, prices, or anything current, call web_search and "
    "summarize the answer.\n"
    "- For weather, call pc_control with get_weather.\n"
    "- To play a specific song or video, use pc_control play_youtube.\n"
    "- To open mail use open_website 'gmail'; to find an email use search_gmail.\n"
    "- When asked to ask or chat with ChatGPT or Claude, use ask_chatgpt or "
    "ask_claude with the user's question.\n"
    "- For opening sites or apps, volume, media, screenshot, lock, time, or "
    "battery, call pc_control, then briefly confirm what you did.\n"
    "If something is impossible with your tools, say so plainly."
)


def build_agent(config):
    resolved = get_engine(config)
    if resolved is None:
        raise SystemExit("No inference engine available. Is Ollama running?")
    engine_key, engine = resolved
    model = config.intelligence.default_model
    agent = AgentRegistry.get("orchestrator")(
        engine,
        model,
        tools=[PcControlTool(), WebSearchTool()],
        system_prompt=SYSTEM_PROMPT,
        max_turns=4,
    )
    return agent, engine_key, model


def wait_for_wake_word(detector: Model) -> None:
    detector.reset()
    with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=CHUNK) as mic:
        while True:
            frames, _ = mic.read(CHUNK)
            scores = detector.predict(np.squeeze(frames))
            if max(scores.values()) >= WAKE_THRESHOLD:
                return


def main() -> None:
    console = Console()
    config = load_config()
    agent, engine_key, model = build_agent(config)
    session = VoiceSession(config)
    detector = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

    console.print(f"[green bold]Jarvis is ready[/green bold]  ({engine_key}: {model})")
    speak("Jarvis online.", console, session)

    while True:
        console.print("\n[dim]Say \"Hey Jarvis\"…  (Ctrl+C to quit)[/dim]")
        wait_for_wake_word(detector)
        winsound.Beep(880, 150)

        text = record_voice(console, session)
        if text is VOICE_EXIT:
            break
        if not text:
            continue

        try:
            reply = agent.run(text).content.strip() or "Done."
        except Exception as exc:  # keep listening even if one request fails
            console.print(f"[red]Error: {exc}[/red]")
            reply = "Sorry, something went wrong."
        console.print(f"[bold cyan]Jarvis:[/bold cyan] {reply}")
        speak(reply, console, session)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
