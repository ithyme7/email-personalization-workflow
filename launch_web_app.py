from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _choose_port(start: int = 8501, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        if _port_available(port):
            return port
    raise RuntimeError("No free local port found for the web app.")


def _wait_until_ready(url: str, timeout_seconds: int = 45) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return 200 <= response.status < 500
        except Exception:  # Connection errors, timeouts - retry
            time.sleep(0.6)
    return False


def main() -> int:
    port = _choose_port()
    url = f"http://localhost:{port}"
    print("Starting Email Personalizer Web App...")
    print(f"Project folder: {ROOT}")
    print(f"URL: {url}")
    print("Close this window or press Ctrl+C to stop the app.")
    print()

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "web_app.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ],
        cwd=ROOT,
    )
    try:
        if _wait_until_ready(url):
            webbrowser.open(url)
        else:
            print("The app took longer than expected to start. Try opening the URL manually:")
            print(url)
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
