"""Jarvis's brain: one agent plus short-term memory, shared by voice and Telegram."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from openjarvis.agents._stubs import AgentContext
from openjarvis.core.types import Conversation, Message, Role

RESET_PHRASES = {"new topic", "forget that", "start over"}

SYSTEM_PROMPT = (
    "You are Jarvis, a smart, helpful voice assistant on the user's Windows PC. "
    "Pick the reply language from the user's LATEST message only: if it is in "
    "English, reply in simple English; only if it is in Hindi or Hinglish, reply "
    "in simple Hindi written in Devanagari script. Your replies are spoken aloud, so keep them to one to three short "
    "sentences with no markdown, lists, URLs, or emojis. Use the conversation "
    "so far to understand follow-ups like 'and tomorrow?' or 'play the next one'.\n"
    "- Answer general questions from your own knowledge.\n"
    "- For news, scores, prices, or anything current, call web_search and "
    "summarize the answer.\n"
    "- For weather, call pc_control with get_weather.\n"
    "- To play a specific song or video, use pc_control play_youtube.\n"
    "- To open mail use open_website 'gmail'; to find an email use search_gmail.\n"
    "- When asked to ask or chat with ChatGPT or Claude, use ask_chatgpt or "
    "ask_claude with the user's question.\n"
    "- For reminders and timers ('remind me in 20 minutes', 'set a timer'), use "
    "the reminders tool; pass the time exactly as the user said it, in English, "
    "like 'in 20 minutes', 'at 6:30 pm', or 'tomorrow 9 am'.\n"
    "- For opening sites, apps, or folders, typing text, closing a window, "
    "volume, brightness, media, screenshot, lock, time, or battery, call "
    "pc_control, then briefly confirm what you did.\n"
    "- To check or read emails ('any new mail?', 'read my emails', 'emails from "
    "Amazon'), use read_emails and summarize who wrote and what about.\n"
    "- When the user tells you a lasting personal fact or preference (their "
    "name, city, favourite music, family), save it with memory_manage action "
    "'add' as a short English sentence, and use known facts in your answers.\n"
    "- To see what's on the screen ('what's this error?', 'summarize this page'), "
    "use look_at_screen.\n"
    "- For text the user copied ('summarize what I copied', 'translate this'), "
    "use clipboard read; to hand them text to paste, use clipboard write.\n"
    "- To find or open the user's own files ('open my resume'), use find_file.\n"
    "- For 'work mode', 'night mode' or other named routines, use routine run.\n"
    "- For meetings, schedule, or 'what's on my calendar', use calendar.\n"
    "- For the to-do or shopping list ('add milk to my list', 'what's on my "
    "list?', 'milk done'), use todo.\n"
    "- When the user says good morning or asks for a briefing: get the weather "
    "for their city, search the web for 'top news India today', check today's "
    "calendar, their reminders, to-do list and unread emails, then give a short, friendly spoken briefing. "
    "Mention the actual news stories in a few words each, never just the names "
    "of news websites.\n"
    "- For shutdown, restart, or sleep: call pc_control with that action, then "
    "ask 'Are you sure?' and STOP. Only if the user's next message says yes, "
    "call pc_control confirm_power. Never call confirm_power in the same reply.\n"
    "If a tool fails or is not set up (for example email), say that part is "
    "unavailable instead of guessing. If something is impossible with your "
    "tools, say so plainly."
)


FACTS_PATH = Path.home() / ".openjarvis" / "jarvis_facts.md"


def facts_prompt(path: Path = FACTS_PATH) -> str:
    """Saved personal facts, formatted for the system prompt ('' if none)."""
    if not path.exists():
        return ""
    facts = path.read_text(encoding="utf-8").strip()
    return f"\n\nThings you know about the user:\n{facts}" if facts else ""


def _make_agent(engine: Any, model: str, tools: list) -> Any:
    import openjarvis.agents  # noqa: F401  (registers agents)
    from openjarvis.core.registry import AgentRegistry

    return AgentRegistry.get("orchestrator")(
        engine,
        model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT + facts_prompt(),
        max_turns=6,
        temperature=0.3,  # steadier tool use and fewer garbled replies
    )


def build_agent(config: Any, tools: list) -> tuple[Any, str, str]:
    """Create the orchestrator agent for the configured engine and model."""
    from openjarvis.engine._discovery import get_engine

    resolved = get_engine(config)
    if resolved is None:
        raise SystemExit("No inference engine available. Check Groq key or Ollama.")
    engine_key, engine = resolved
    model = config.intelligence.default_model
    if model.startswith("groq/"):
        from engine_guard import ResilientEngine  # imported here: it imports brain

        engine = ResilientEngine(engine)  # rate limit -> backup Groq model, per call
    return _make_agent(engine, model, tools), engine_key, model


LOCAL_MODEL = "qwen3.5:2b"  # used through Ollama when the internet/Groq is down


def build_local_agent(config: Any, tools: list, model: str = LOCAL_MODEL) -> Any | None:
    """Agent on the local Ollama model, or None if Ollama isn't running."""
    from openjarvis.engine._discovery import get_engine

    resolved = get_engine(config, "ollama")
    return None if resolved is None else _make_agent(resolved[1], model, tools)


_JUNK_RUN = re.compile(r"(?:\s+[.…?]+){2,}")  # e.g. " ... ........ … …"
_REPEATED = re.compile(r"^(.+?)(?:\s*\1)+$", re.DOTALL)  # "Done.Done." -> "Done."
_GAVE_UP = "Maximum turns reached"  # OpenJarvis's message when the tool loop runs out
_RETRY_AFTER = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")
MAX_RATE_LIMIT_WAIT = 20.0


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def is_hindi(text: str) -> bool:
    """True if the text contains Devanagari, so it should be spoken in Hindi."""
    return bool(_DEVANAGARI.search(text))


def clean_reply(text: str) -> str:
    """Collapse stray dot/ellipsis runs and an answer repeated back-to-back."""
    text = _JUNK_RUN.sub(" …", text).strip()
    return _REPEATED.sub(r"\1", text)


def _rate_limit_wait(exc: Exception) -> float | None:
    """Seconds to wait if ``exc`` is a provider rate limit, else None."""
    msg = f"{type(exc).__name__} {exc}".lower()
    if "ratelimit" not in msg and "rate limit" not in msg:
        return None
    m = _RETRY_AFTER.search(msg)
    told = (int(m[1] or 0) * 60 + float(m[2])) if m else 4.0
    return min(told + 1.0, MAX_RATE_LIMIT_WAIT)


_OFFLINE_MARKERS = (
    "apiconnectionerror", "connecterror", "connection error", "connection refused",
    "getaddrinfo", "name resolution", "network is unreachable", "timed out", "timeout",
)


def _is_offline(exc: Exception) -> bool:
    """True if ``exc`` means the cloud model couldn't be reached at all."""
    msg = f"{type(exc).__name__} {exc}".lower()
    return any(marker in msg for marker in _OFFLINE_MARKERS)


class Brain:
    """Answers one request at a time, remembering recent turns for follow-ups."""

    def __init__(
        self,
        agent: Any,
        *,
        now: Callable[[], float] = time.monotonic,
        on_turn: Callable[[], None] = lambda: None,
        max_turns: int = 10,
        idle_seconds: float = 180,
        fallback: Callable[[], Any] | None = None,
    ) -> None:
        self._agent = agent
        self._make_fallback = fallback  # builds a local agent for when offline
        self._fallback_agent: Any = None
        self._now = now
        self._on_turn = on_turn
        self._max_messages = max_turns * 2
        self._idle_seconds = idle_seconds
        self._history: list[Message] = []
        self._last_turn: float | None = None
        self._lock = threading.Lock()  # voice and Telegram may call at once
        self.last_error: Exception | None = None

    def reset(self) -> None:
        self._history.clear()
        self._last_turn = None

    def reply(self, text: str) -> str:
        with self._lock:
            if text.lower().strip(" .!?") in RESET_PHRASES:
                self.reset()
                return "Okay, starting fresh."
            if self._last_turn is not None and (
                self._now() - self._last_turn > self._idle_seconds
            ):
                self.reset()

            self._on_turn()
            try:
                result = self._run(text)
            except Exception as exc:  # one failed request must not kill Jarvis
                self.last_error = exc
                if _rate_limit_wait(exc) is not None:
                    return "I'm a bit busy right now, please try again in a minute."
                if self._make_fallback is None or not _is_offline(exc):
                    return "Sorry, something went wrong."
                local = self._local_agent()
                if local is None:
                    return "I'm offline and the local model isn't running."
                try:
                    result = self._run(text, agent=local)
                except Exception as local_exc:
                    self.last_error = local_exc
                    return "Sorry, something went wrong."
            self.last_error = None

            content = clean_reply(result.content or "") or "Done."
            if content.startswith(_GAVE_UP):
                return "Sorry, I couldn't finish that. Please try asking again."
            self._history += [
                Message(role=Role.USER, content=text),
                Message(role=Role.ASSISTANT, content=content),
            ]
            self._history = self._history[-self._max_messages :]
            self._last_turn = self._now()
            return content

    def _local_agent(self) -> Any:
        if self._fallback_agent is None and self._make_fallback is not None:
            self._fallback_agent = self._make_fallback()  # None if Ollama is down; retried next time
        return self._fallback_agent

    def _run(self, text: str, agent: Any = None) -> Any:
        """Run the agent once. Never rerun a request: tools that already ran
        would run again. Rate limits are retried per call in engine_guard."""
        context = AgentContext(conversation=Conversation(messages=list(self._history)))
        return (agent or self._agent).run(text, context=context)
