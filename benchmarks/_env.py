"""Load .env from the project root before any benchmark module reads os.environ."""
from __future__ import annotations

from pathlib import Path


def _load() -> None:
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass  # python-dotenv not installed — env vars must be set manually


_load()
