#!/usr/bin/env python3
"""Launch the local data-quality web UI.

Binds to 127.0.0.1 only — this tool is unauthenticated and must not be exposed
on the network. Open the printed URL in a browser.

Settings come from ``config/web.cfg`` (port, default cap, log level); a ``--port``
flag overrides the configured port for a single run.

Usage:
    python src/run_web.py                 # uses config/web.cfg (default :8000)
    python src/run_web.py --port 8080     # override the port
    python src/run_web.py --config path/to/web.cfg
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make sibling modules (quality_service, medplum_client, …) importable whether
# run as `python src/run_web.py` or `python -m`.
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402

# Reuse the CLI's .env loader so MEDPLUM_* creds are available server-side.
from run_quality_check import _load_env  # noqa: E402
from web.config import HOST, load_web_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local data-quality web UI.")
    parser.add_argument("--port", type=int, default=None,
                        help="Override the port from config/web.cfg.")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to web.cfg (default: config/web.cfg).")
    args = parser.parse_args(argv)

    cfg = load_web_config(args.config)
    port = args.port if args.port is not None else cfg.port

    # The app is imported in-process by uvicorn; pass the resolved cap through so
    # a custom --config is honored there too (app.py reads WEB_DEFAULT_CAP).
    os.environ["WEB_DEFAULT_CAP"] = str(cfg.default_cap)

    _load_env()
    print(f"Data-quality UI (localhost-only) → http://{HOST}:{port}")
    uvicorn.run("web.app:app", host=HOST, port=port, log_level=cfg.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
