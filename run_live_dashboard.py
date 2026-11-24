"""Launch the KP Cricket live Streamlit dashboard.

    python run_live_dashboard.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "live" / "dashboard" / "app.py"
PORT = 8502


def main() -> None:
    # Bind to localhost only so the URL stays stable when Wi-Fi/VPN changes.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP),
            "--server.headless",
            "true",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(PORT),
        ],
        cwd=str(ROOT),
        check=False,
    )


if __name__ == "__main__":
    main()
