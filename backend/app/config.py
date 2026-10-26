"""Settings: paths, the one model we use, and every limit that protects the token budget."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# .env in the repo root first, then the folder above it. override=False (the default) means
# variables already set in the environment always win, and the repo's .env wins over the parent's.
for env_file in (REPO_ROOT / ".env", REPO_ROOT.parent / ".env"):
    if env_file.is_file():
        load_dotenv(env_file, override=False)

DATA_DIR = Path(os.getenv("UMMACARE_DATA_DIR", BACKEND_DIR / "data" / "runtime"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR = DATA_DIR / "media"        # uploaded videos, captured frames, note images
MEDIA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "ummacare.db"
REFERENCES_FILE = BACKEND_DIR / "data" / "references.json"
FIXTURES_DIR = BACKEND_DIR / "data" / "fixtures"

# --- model: the course key permits only gpt-6-luna. Never switch automatically.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
REASONING_EFFORT = "low"

# Bump when prompts or output schemas change: cached video analyses keyed on an older
# version are recomputed instead of reused.
PROCESSING_VERSION = "moments-v3"
CONNECTION_VERSION = "connections-v3"

# --- spending and loop limits
DAILY_BUDGET_USD = float(os.getenv("DAILY_BUDGET_USD", "1.00"))   # hard stop for the whole app per UTC day
MAX_OUTPUT_TOKENS = 6_000          # per model response, reasoning included
RUN_TOKEN_LIMIT = 60_000           # per workflow run, all requests combined
RUN_REQUEST_LIMIT = 6              # model round-trips per workflow run (validation retries count)
CHAT_TOOL_CALL_LIMIT = 8           # tool calls per chat question
MAX_TRANSCRIPT_CHARS = 45_000      # ~11k tokens; longer transcripts are truncated with a visible notice
MAX_MOMENTS = 5
MAX_CHAT_CHARS = 1_500
MAX_UPLOAD_MB = 400


def portkey_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set. Put it in .env in the repo folder or the folder above it.")
    return key


def ai_key_present() -> bool:
    return bool(os.getenv("PORTKEY_API_KEY"))
