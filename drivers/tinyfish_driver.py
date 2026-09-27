"""TinyFish driver — marketplace-style LinkedIn automation wrapper.

TinyFish exposes a simple job-based API: submit an automation job, poll for
results. This wrapper maps those jobs onto our provider surface. Without a
key it refuses loudly rather than silently no-oping.
"""
from __future__ import annotations

from typing import List

import httpx

from config import TINYFISH_API_KEY
from database.models import Prospect
from drivers.linkedin_base import InboundMessage, LinkedInProvider, ScanResult, SendResult


class TinyFishDriver(LinkedInProvider):
    name = "tinyfish"
    BASE = "https://api.tinyfish.ai/v1"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key or TINYFISH_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "TinyFish API key missing. Set TINYFISH_API_KEY in .env or use the mock "
                "driver for zero-budget simulation."
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def search_prospects(self, query: dict) -> List[Prospect]:
        raise NotImplementedError(
            "Create a TinyFish 'LinkedIn people search' job and map its output rows to "
            "Prospect. See README (TinyFish section) for the mapping table."
        )

    def send_message(self, prospect: Prospect, text: str) -> SendResult:
        self._validate(text)
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{self.BASE}/jobs",
                headers=self._headers(),
                json={
                    "type": "linkedin.message",
                    "params": {
                        "profile_url": prospect.contact_linkedin,
                        "message": text,
                    },
                },
            )
        r.raise_for_status()
        return SendResult(ok=True, driver=self.name,
                          external_id=str(r.json().get("jobId", "")),
                          note="TinyFish job submitted", simulated=False)

    def check_replies(self) -> ScanResult:
        with httpx.Client(timeout=30) as client:
            r = client.get(f"{self.BASE}/jobs?type=linkedin.inbox",
                           headers=self._headers())
        r.raise_for_status()
        items = [
            InboundMessage(
                prospect_name=m.get("from", {}).get("name", ""),
                text=m.get("text", ""),
                external_id=str(m.get("id", "")),
                raw=m,
            )
            for m in r.json().get("messages", [])
        ]
        return ScanResult(ok=True, driver=self.name, items=items)
