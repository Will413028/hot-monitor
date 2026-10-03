import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)


def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"true", "1", "yes"}


def interval_seconds() -> int:
    return max(10, int(os.getenv("MONITOR_INTERVAL_SECONDS", "300")))


def email_configured() -> bool:
    return flag("EMAIL_ENABLED") and all(os.getenv(key) for key in ("SMTP_HOST", "SMTP_FROM", "SMTP_TO"))
