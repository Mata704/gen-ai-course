"""Report local runtime prerequisites."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(REPO_ROOT / ".env")
REQUIRED_FILES = [
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "uv.lock",
    REPO_ROOT / ".dockerignore",
    Path(__file__).resolve().parent / "app" / "api.py",
    Path(__file__).resolve().parent / "app" / "ui.py",
    Path(__file__).resolve().parent / "Dockerfile",
    Path(__file__).resolve().parent / "compose.yaml",
]


def inspect_runtime() -> dict:
    api_url = os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000")
    parsed_url = urlparse(api_url)
    missing_files = [str(path.relative_to(REPO_ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    docker_cli = shutil.which("docker")
    docker_engine_ready = False
    if docker_cli:
        try:
            result = subprocess.run(
                [docker_cli, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            docker_engine_ready = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "docker_available": docker_cli is not None,
        "docker_engine_ready": docker_engine_ready,
        "api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
        "api_url": api_url,
        "api_url_valid": parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc),
        "missing_files": missing_files,
    }


def main() -> None:
    report = inspect_runtime()
    print(json.dumps(report, indent=2))
    ready = (
        report["docker_engine_ready"] and report["api_key_configured"]
        and report["api_url_valid"] and not report["missing_files"]
    )
    print(f"\nRuntime checks: {'PASS' if ready else 'FAIL'}")
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
