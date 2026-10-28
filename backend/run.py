"""Start Trinetra and open the dashboard in the browser once the server answers.

  python run.py            (from the backend folder; start.bat / start.sh do this for you)
  python run.py --no-browser
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402

from trinetra import config  # noqa: E402


def free_port(start: int) -> int:
    """Use the configured port, or the next free one if another program already has it."""
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((config.HOST, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port between {start} and {start + 19}")


config.PORT = free_port(config.PORT)
URL = f"http://localhost:{config.PORT}"


def open_when_ready() -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config.PORT}/api/health", timeout=2):
                break
        except Exception:
            time.sleep(0.5)
    print(f"\n  Trinetra AI is running:  {URL}\n  Press Ctrl+C in this window to stop.\n", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)


if __name__ == "__main__":
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("trinetra.main:app", host=config.HOST, port=config.PORT, log_level="warning")
