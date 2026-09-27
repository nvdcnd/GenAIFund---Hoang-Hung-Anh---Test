"""Abstract base class for all LinkedIn provider integrations.

Every driver implements the same surface so the outreach engine can swap
PhantomBuster / Dripify / TinyFish / Mock with zero code changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import List, Optional

from database.models import Prospect


@dataclass
class SendResult:
    ok: bool
    driver: str
    external_id: str = ""
    note: str = ""
    simulated: bool = True


@dataclass
class ScanResult:
    """A batch of inbound messages detected on LinkedIn."""

    ok: bool
    driver: str
    items: List["InboundMessage"] = field(default_factory=list)
    note: str = ""


@dataclass
class InboundMessage:
    prospect_email: str = ""
    prospect_name: str = ""
    text: str = ""
    external_id: str = ""
    raw: Optional[dict] = None


class LinkedInProvider(abc.ABC):
    """Common interface: search prospects, send, check replies."""

    name: str = "abstract"

    @abc.abstractmethod
    def search_prospects(self, query: dict) -> List[Prospect]:
        """Run a prospect search and return enriched Prospect objects (unsaved)."""

    @abc.abstractmethod
    def send_message(self, prospect: Prospect, text: str) -> SendResult:
        """Deliver a message (DM or connection note depending on degree)."""

    @abc.abstractmethod
    def check_replies(self) -> ScanResult:
        """Poll for new inbound messages."""

    # ── optional shared helpers ──────────────────────────────────────────
    def _connection_note(self, prospect: Prospect) -> str:
        return (prospect.draft_message or "").strip()

    def _validate(self, text: str, limit: int = 1300) -> str:
        t = (text or "").strip()
        if len(t) > limit:
            raise ValueError(f"Message exceeds {limit} chars ({len(t)}).")
        if not t:
            raise ValueError("Message is empty.")
        return t
