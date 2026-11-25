from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

from eu_security_navigator.main import app

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _find_available_port(host: str, preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((host, preferred_port)) != 0:
            return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _open_browser_when_ready(host: str, port: int, path: str = "/search") -> None:
    url = f"http://{host}:{port}{path}"
    deadline = time.monotonic() + 15.0

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.15)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="DocumentIntelligenceNavigator",
        description="Launch Document Intelligence Navigator offline on localhost.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind (default: 8000, or next free port if 8000 is busy).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the default browser automatically.",
    )
    parser.add_argument(
        "--allow-non-local",
        action="store_true",
        help="Allow binding to a non-loopback address (not recommended for sensitive data).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.host not in LOOPBACK_HOSTS and not args.allow_non_local:
        raise SystemExit(
            f"Refusing to bind non-loopback host '{args.host}' in offline mode. "
            "Use 127.0.0.1 or pass --allow-non-local explicitly."
        )

    port = args.port if args.port is not None else _find_available_port(args.host, 8000)
    url = f"http://{args.host}:{port}/search"

    print(f"Document Intelligence Navigator (Offline) running at: {url}", flush=True)
    print("All uploaded PDF and JSON files remain in memory only.", flush=True)
    print("Press Ctrl+C to stop and clear the session.", flush=True)

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(args.host, port),
            daemon=True,
        ).start()

    uvicorn.run(
        app,
        host=args.host,
        port=port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
