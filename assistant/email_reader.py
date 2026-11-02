"""Read recent Gmail messages aloud. Strictly read-only.

The inbox is opened with ``readonly=True`` and bodies are fetched with
``BODY.PEEK[]``, so nothing is marked as read, moved, or deleted.

Needs user env vars ``GMAIL_ADDRESS`` and ``GMAIL_APP_PASSWORD`` (a Google
app password: https://myaccount.google.com/apppasswords, requires 2-step
verification).
"""

from __future__ import annotations

import email as email_lib
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Callable

from openjarvis.connectors.gmail_imap import _decode_header, _extract_text_body, _parse_date
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

MAX_COUNT = 10
SNIPPET_CHARS = 120
_SAFE_SENDER = re.compile(r"^[\w@.\- ]{1,80}$")


@dataclass
class Mail:
    sender: str
    subject: str
    date: datetime
    body: str


def search_criteria(unread_only: bool, sender: str) -> list[str]:
    """IMAP SEARCH criteria. Sender is restricted to plain characters."""
    criteria = ["UNSEEN" if unread_only else "ALL"]
    sender = sender.strip()
    if sender:
        if not _SAFE_SENDER.match(sender):
            raise ValueError("Sender can only contain letters, numbers, spaces, @ . - _")
        criteria += ["FROM", f'"{sender}"']
    return criteria


def speakable(mails: list[Mail]) -> str:
    if not mails:
        return "No matching emails."
    lines = []
    for i, m in enumerate(mails, 1):
        name, address = parseaddr(m.sender)
        who = name or address or "unknown sender"
        snippet = " ".join(m.body.split())[:SNIPPET_CHARS]
        lines.append(f"{i}. From {who}: {m.subject or '(no subject)'} — {snippet}")
    return "\n".join(lines)


def fetch_emails(address: str, password: str, criteria: list[str], count: int) -> list[Mail]:
    """Newest ``count`` inbox messages matching ``criteria``, newest first."""
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=20)
    try:
        imap.login(address, password)
        imap.select("INBOX", readonly=True)
        status, data = imap.uid("SEARCH", None, *criteria)
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()[-count:][::-1]
        mails = []
        for uid in uids:
            status, parts = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if status != "OK" or raw is None:
                continue
            msg = email_lib.message_from_bytes(raw)
            mails.append(Mail(
                sender=_decode_header(msg.get("From", "")),
                subject=_decode_header(msg.get("Subject", "")),
                date=_parse_date(msg),
                body=_extract_text_body(msg),
            ))
        return mails
    finally:
        try:
            imap.logout()
        except Exception:
            pass


class EmailReaderTool(BaseTool):
    tool_id = "read_emails"

    def __init__(self, fetch: Callable[..., list[Mail]] = fetch_emails) -> None:
        self._fetch = fetch

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_emails",
            description=(
                "Read the user's recent Gmail inbox messages (read-only). Returns "
                "sender, subject and a short snippet; summarize them briefly."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "How many (1-10, default 5)."},
                    "unread_only": {"type": "boolean", "description": "Default true."},
                    "sender": {"type": "string", "description": "Only emails from this name or address."},
                },
            },
            category="communication",
        )

    def _result(self, content: str, success: bool = True) -> ToolResult:
        return ToolResult(tool_name="read_emails", content=content, success=success)

    def execute(self, **params: Any) -> ToolResult:
        address = os.environ.get("GMAIL_ADDRESS", "").strip()
        password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
        if not address or not password:
            return self._result(
                "Email reading is not set up. The user must set GMAIL_ADDRESS and "
                "GMAIL_APP_PASSWORD environment variables, then restart Jarvis.",
                False,
            )
        try:
            count = max(1, min(MAX_COUNT, int(params.get("count") or 5)))
        except (TypeError, ValueError):
            count = 5
        unread_only = params.get("unread_only", True) is not False
        try:
            criteria = search_criteria(unread_only, str(params.get("sender") or ""))
        except ValueError as exc:
            return self._result(str(exc), False)
        try:
            mails = self._fetch(address, password, criteria, count)
        except (imaplib.IMAP4.error, OSError):
            # Never echo the server message: it can contain the credentials.
            return self._result(
                "Couldn't read Gmail. Check GMAIL_ADDRESS, the app password, and "
                "that IMAP is enabled in Gmail settings.",
                False,
            )
        return self._result(speakable(mails))
