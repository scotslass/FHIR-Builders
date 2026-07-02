"""Settings for the local web UI, read from ``config/web.cfg``.

Mirrors how the rest of the app loads ``config/*.cfg`` (configparser). The bind
host is deliberately omitted — the server is localhost-only by design (see
``run_web.py`` / the README), so it is not a configurable parameter here.

Precedence for a value: CLI flag (handled by the caller) > ``config/web.cfg`` >
built-in default. ``WEB_DEFAULT_CAP`` in the environment still overrides the cap
for back-compat.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "web.cfg"

# Fixed: the security model depends on binding to loopback only.
HOST = "127.0.0.1"


@dataclass(frozen=True)
class WebConfig:
    port: int = 8000
    default_cap: int = 500
    log_level: str = "info"


def load_web_config(path: Path | None = None) -> WebConfig:
    """Load ``[web]`` settings, falling back to defaults when absent."""
    cfg = configparser.ConfigParser()
    config_path = path or DEFAULT_CONFIG
    if config_path.exists():
        cfg.read(config_path)

    defaults = WebConfig()
    port = cfg.getint("web", "port", fallback=defaults.port)
    default_cap = cfg.getint("web", "default_cap", fallback=defaults.default_cap)
    log_level = cfg.get("web", "log_level", fallback=defaults.log_level)

    # Env override kept for back-compat with the original WEB_DEFAULT_CAP.
    default_cap = int(os.getenv("WEB_DEFAULT_CAP", str(default_cap)))

    return WebConfig(port=port, default_cap=default_cap, log_level=log_level)
