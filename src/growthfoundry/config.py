"""Centralised runtime configuration loaded from environment variables.

All GF_* knobs are read once here; every module imports `load_config()` instead
of calling os.getenv() directly.  This keeps .env.example in sync with actual code.

Usage:
    from growthfoundry.config import load_config
    cfg = load_config()
    print(cfg.max_candidates_per_run)
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GFConfig:
    # Track A — product factory
    enable_auto_publish: bool = False
    max_candidates_per_run: int = 3
    daily_usd_budget: float = 0.0

    # Network / retry
    github_token: str = ""
    max_retries: int = 3

    # Track B — local model training
    hf_home: str = ""

    # Regression gate
    regression_repetition_threshold: int = 3
    regression_overlap_floor: float = 0.15


def load_config() -> GFConfig:
    """Read all GF_* environment variables and return an immutable config object.

    Callers should normally obtain a singleton via ``get_config()`` rather than
    calling this directly, to avoid re-parsing os.environ on every call.
    """
    def _bool(key: str, default: bool) -> bool:
        val = os.getenv(key, "").strip().lower()
        if val in ("1", "true", "yes"):
            return True
        if val in ("0", "false", "no"):
            return False
        return default

    def _int(key: str, default: int) -> int:
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(os.getenv(key, str(default)))
        except ValueError:
            return default

    return GFConfig(
        enable_auto_publish=_bool("GF_ENABLE_AUTO_PUBLISH", False),
        max_candidates_per_run=_int("GF_MAX_CANDIDATES_PER_RUN", 3),
        daily_usd_budget=_float("GF_DAILY_USD_BUDGET", 0.0),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        max_retries=_int("GF_MAX_RETRIES", 3),
        hf_home=os.getenv("HF_HOME", ""),
        regression_repetition_threshold=_int("GF_REGRESSION_REPETITION_THRESHOLD", 3),
        regression_overlap_floor=_float("GF_REGRESSION_OVERLAP_FLOOR", 0.15),
    )


# Module-level singleton — imported once per process.
_config: GFConfig | None = None


def get_config() -> GFConfig:
    """Return the process-wide config singleton (lazy-initialised)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
