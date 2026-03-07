# LangSmith tracing setup. Load .env so LANGSMITH_* vars apply before LangGraph/audit run.

from __future__ import annotations

import os
from pathlib import Path


def ensure_env_loaded() -> None:
    """
    Load .env from cwd or project root so LANGSMITH_* and other vars are set
    before LangGraph/audit runs. Safe to call multiple times.
    """
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        env_file = base / ".env"
        if not env_file.is_file():
            continue
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
        except OSError:
            pass
        break


def is_langsmith_enabled() -> bool:
    """True if LangSmith tracing would be active (API key set and tracing not disabled)."""
    key = (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or "").strip()
    disabled = (os.environ.get("LANGSMITH_TRACING", "true").lower() in ("false", "0", "no"))
    return bool(key) and not disabled
