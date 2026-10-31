"""Runtime configuration. Every secret / environment-specific value comes from env vars."""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("courtvision.config")


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no extra dependency). Real environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    APP_NAME = "CourtVision AI"
    APP_TAGLINE = "NBA Live Intelligence & Predictive Analytics"
    VERSION = "2.0.0"

    ENV = os.environ.get("COURTVISION_ENV", "development")
    DEBUG = _bool("COURTVISION_DEBUG", False)
    HOST = os.environ.get("COURTVISION_HOST", "127.0.0.1")
    PORT = _int("COURTVISION_PORT", 5000)

    SECRET_KEY = os.environ.get("SECRET_KEY") or ""
    # Same-origin only unless explicitly widened, e.g. CORS_ORIGINS="https://example.com"
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

    # Optional AI analyst. Provider order: Gemini -> Anthropic -> rule-based (always labelled in the UI).
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    HTTP_TIMEOUT = _int("COURTVISION_HTTP_TIMEOUT", 30)
    # Optional outbound proxy for stats.nba.com / cdn.nba.com, e.g. http://user:pass@host:port (helps when your ISP/cloud IP is blocked)
    NBA_PROXY = os.environ.get("NBA_PROXY", "") or None
    LIVE_POLL_SECONDS = _int("COURTVISION_LIVE_POLL_SECONDS", 6)
    DISK_CACHE = _bool("COURTVISION_DISK_CACHE", True)
    CACHE_DIR = Path(os.environ.get("COURTVISION_CACHE_DIR", str(ROOT / ".cache")))
    DATA_DIR = ROOT / "data"

    @classmethod
    def resolve_secret(cls) -> str:
        if cls.SECRET_KEY:
            return cls.SECRET_KEY
        if cls.ENV == "production":
            raise RuntimeError("SECRET_KEY must be set when COURTVISION_ENV=production")
        logger.warning("SECRET_KEY not set - using an ephemeral random key for this process.")
        return secrets.token_hex(32)
