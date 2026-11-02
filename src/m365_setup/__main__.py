"""Command line: open the setup page, or run the same steps in the console with `--no-ui`."""

from __future__ import annotations

import argparse
import logging
import sys

from m365_setup.clients import CLIENTS, Client
from m365_setup.session import Session


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.no_ui:
        return _console(args)
    from m365_setup import web

    web.serve(Session(CLIENTS), port=args.port, open_browser=not args.no_browser)
    return 0


def _console(args: argparse.Namespace) -> int:
    """The CLI fallback: same run, printed step by step."""
    clients = _selected_clients(args.client)
    printed: dict[str, str] = {}
    session: Session

    def report() -> None:
        state = session.snapshot()
        for group in ("connectors", "clients", "profiles"):
            for item in state[group]:
                key = f"{group}:{item['key']}"
                line = f"{item['state']:>8}  {item['title']}" + (
                    f"  {item['detail']}" if item["detail"] else ""
                )
                if item["state"] != "waiting" and printed.get(key) != line:
                    printed[key] = line
                    print(line, flush=True)
                    for duplicate in item.get("duplicates") or ():
                        print(f"          note: '{duplicate}' also runs this connector; remove it if unused")
        prompt = state["prompt"]
        if prompt and printed.get("prompt") != prompt["user_code"]:
            printed["prompt"] = prompt["user_code"]
            print(
                f"\nApprove sign-in for {prompt['app']}:\n"
                f"  1. Open {prompt['verification_uri']}\n"
                f"  2. Enter the code {prompt['user_code']} and click Next.\n"
                "  3. Pick your work account. When Microsoft asks if you are signing in to\n"
                f"     {prompt['app']}, click Continue. The connectors use that Microsoft app's sign-in.\n"
                "  Only enter a code this window shows you.\n",
                flush=True,
            )
        if printed.get("message") != state["message"]:
            printed["message"] = state["message"]
            print(state["message"], flush=True)

    session = Session(clients, on_change=report)
    session.start([client.key for client in clients], install=not args.skip_install)
    session.wait()
    return 0 if session.snapshot()["phase"] == "done" else 1


def _selected_clients(keys: list[str] | None) -> list[Client]:
    if keys:
        return [client for client in CLIENTS if client.key in keys]
    return [client for client in CLIENTS if client.detected()]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lrh-m365-setup",
        description="Install the Microsoft 365 connectors, add them to your AI apps and sign in.",
    )
    parser.add_argument("--no-ui", action="store_true", help="Run in this console instead of a web page.")
    parser.add_argument(
        "--client",
        action="append",
        choices=[client.key for client in CLIENTS],
        help="With --no-ui: an AI app to configure (repeatable). Default: every app found.",
    )
    parser.add_argument(
        "--skip-install", action="store_true", help="With --no-ui: only register and sign in."
    )
    parser.add_argument("--port", type=int, default=0, help="Page port on 127.0.0.1 (default: a free one).")
    parser.add_argument("--no-browser", action="store_true", help="Print the page link without opening it.")
    return parser


if __name__ == "__main__":
    sys.exit(main())
