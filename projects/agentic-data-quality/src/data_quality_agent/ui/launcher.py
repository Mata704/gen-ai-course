from __future__ import annotations

import sys
from pathlib import Path

APP_PATH = Path(__file__).with_name("app.py")


def main() -> None:
    from streamlit.web import cli as streamlit_cli

    options = sys.argv[1:]
    if not any(option.startswith("--server.address") for option in options):
        options = ["--server.address", "localhost", *options]
    sys.argv = ["streamlit", "run", str(APP_PATH), *options]
    streamlit_cli.main()
