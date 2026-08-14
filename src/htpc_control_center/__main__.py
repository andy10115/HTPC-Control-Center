"""Entry point for GUI and the per-user TV watcher."""
from __future__ import annotations

import asyncio
import logging
import sys

from . import __version__


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "watcher":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s htpc-control-center: %(message)s",
        )
        from .tv.lifecycle import run_watcher

        asyncio.run(run_watcher())
        return 0
    if len(sys.argv) > 1 and sys.argv[1] in {"--version", "-V"}:
        print(__version__)
        return 0

    from .application import HTPCControlCenterApplication

    app = HTPCControlCenterApplication()
    return int(app.run(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
