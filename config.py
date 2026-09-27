"""Central configuration — environment & campaign defaults.

Everything degrades gracefully to a zero-budget mock mode when no API keys
are present, so the full flow can be evaluated without spending anything.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- paths --
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "outreach.db"

load_dotenv(PROJECT_ROOT / ".env")

# ------------------------------------------------------------------ llm --
LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

def llm_configured() -> bool:
    return bool(OPENAI_API_KEY)

# -------------------------------------------------------------- linkedin --
LINKEDIN_DRIVER: str = os.getenv("LINKEDIN_DRIVER", "mock").lower().strip()
PHANTOMBUSTER_API_KEY: str = os.getenv("PHANTOMBUSTER_API_KEY", "")
PHANTOMBUSTER_AGENT_ID: str = os.getenv("PHANTOMBUSTER_AGENT_ID", "")
DRIFIPI_API_KEY: str = os.getenv("DRIFIPI_API_KEY", "")
TINYFISH_API_KEY: str = os.getenv("TINYFISH_API_KEY", "")

# -------------------------------------------------------------- webhook --
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PORT: int = int(os.getenv("API_PORT", "8001"))
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "change-me")
CALENDLY_LINK: str = os.getenv(
    "CALENDLY_LINK", "https://cal.com/genai-fund/hackathon-sponsor"
)

DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
