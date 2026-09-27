"""PhantomBuster driver — free-tier friendly API wrapper.

PhantomBuster's free trial offers limited execution time; this wrapper keeps
all calls behind one small surface and degrades gracefully to safe no-ops
when no API key is configured so nothing accidental is ever triggered.
"""
from __future__ import annotations

from typing import List

import httpx

from config import PHANTOMBUSTER_API_KEY, PHANTOMBUSTER_AGENT_ID
from database.models import Prospect
from drivers.linkedin_base import InboundMessage, LinkedInProvider, ScanResult, SendResult


class PhantomBusterDriver(LinkedInProvider):
    name = "phantombuster"
    BASE = "https://api.phantombuster.com/api/v2"

    def __init__(self, api_key: str = "", agent_id: str = "") -> None:
        self.api_key = api_key or PHANTOMBUSTER_API_KEY
        self.agent_id = agent_id or PHANTOMBUSTER_AGENT_ID
        if not self.api_key:
            raise RuntimeError(
                "PhantomBuster API key missing. Set PHANTOMBUSTER_API_KEY in .env "
                "or select the mock driver for zero-budget simulation."
            )

    def _headers(self) -> dict:
        return {"X-Phantombuster-Key": self.api_key, "Content-Type": "application/json"}

    def search_prospects(self, query: dict) -> List[Prospect]:
        # Real usage: launch a "LinkedIn Search Export" phantom with the query
        # and poll its output CSV. Kept as an explicit TODO because running it
        # costs free-tier execution minutes; research agent handles enrichment.
        raise NotImplementedError(
            "Wire a LinkedIn Search Export phantom: launch with query, poll container "
            "id, then map result rows onto Prospect. See README (PhantomBuster section)."
        )

    def send_message(self, prospect: Prospect, text: str) -> SendResult:
        self._validate(text)
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{self.BASE}/agents/launch",
                headers=self._headers(),
                json={"id": self.agent_id, "arguments": {
                    "action": "sendMessage",
                    "profileUrl": prospect.contact_linkedin,
                    "message": text,
                }},
            )
        r.raise_for_status()
        data = r.json()
        return SendResult(ok=True, driver=self.name,
                          external_id=str(data.get("containerId", "")),
                          note="Phantom launched", simulated=False)

    def check_replies(self) -> ScanResult:
        with httpx.Client(timeout=30) as client:
            r = client.get(
                f"{self.BASE}/agents/fetch",
                headers=self._headers(),
                params={"id": self.agent_id},
            )
        r.raise_for_status()
        items = [
            InboundMessage(
                prospect_name=row.get("firstName", "") + " " + row.get("lastName", ""),
                text=row.get("message", ""),
                external_id=str(row.get("id", "")),
                raw=row,
            )
            for row in r.json().get("output", {}).get("messages", [])
            if row.get("direction") == "in"
        ]
        return ScanResult(ok=True, driver=self.name, items=items)
