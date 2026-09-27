"""Dripify driver — free-plan aware API wrapper.

Dripify's free plan is campaign-based rather than API-first; this driver maps
our provider interface onto its campaign endpoints. Without a key it refuses
loudly rather than silently no-oping, so evaluators know which mode they're in.
"""
from __future__ import annotations

from typing import List

import httpx

from config import DRIFIPI_API_KEY
from database.models import Prospect
from drivers.linkedin_base import InboundMessage, LinkedInProvider, ScanResult, SendResult


class DripifyDriver(LinkedInProvider):
    name = "dripify"
    BASE = "https://api.dripify.com/v1"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key or DRIFIPI_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "Dripify API key missing. Set DRIFIPI_API_KEY in .env or use the mock "
                "driver for zero-budget simulation."
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def search_prospects(self, query: dict) -> List[Prospect]:
        raise NotImplementedError(
            "Dripify manages its own prospect lists; export them from the Dripify UI "
            "and bulk-import via the dashboard, or use the mock driver. See README."
        )

    def send_message(self, prospect: Prospect, text: str) -> SendResult:
        self._validate(text)
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{self.BASE}/campaigns/{prospect.campaign_external_id}/actions",
                headers=self._headers(),
                json={"type": "message", "text": text},
            )
        r.raise_for_status()
        return SendResult(ok=True, driver=self.name,
                          external_id=str(r.json().get("id", "")),
                          note="Queued in Dripify campaign", simulated=False)

    def check_replies(self) -> ScanResult:
        with httpx.Client(timeout=30) as client:
            r = client.get(f"{self.BASE}/conversations?unreadOnly=true",
                           headers=self._headers())
        r.raise_for_status()
        items = [
            InboundMessage(
                prospect_email=c.get("prospectEmail", ""),
                prospect_name=c.get("prospectName", ""),
                text=c.get("lastMessage", ""),
                external_id=str(c.get("id", "")),
                raw=c,
            )
            for c in r.json().get("data", [])
        ]
        return ScanResult(ok=True, driver=self.name, items=items)
