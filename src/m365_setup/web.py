"""The local setup page: 127.0.0.1 only, one random token per run, polled state.

Every request must carry the run's token (query on the page, header on the API) and a loopback Host
header, so another site in the browser cannot drive the installer or read the device code.
"""

from __future__ import annotations

import secrets
import socket
import threading
import webbrowser
from importlib import resources
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from m365_setup.clients import RegistrationError
from m365_setup.session import Session

TOKEN_HEADER = "x-setup-token"


def serve(session: Session, *, port: int = 0, open_browser: bool = True) -> None:
    """Serve the page until the person closes it from the page or presses Ctrl+C."""
    port = port or _free_port()
    token = secrets.token_urlsafe(24)
    server = uvicorn.Server(
        uvicorn.Config(
            build_app(session, token, port, lambda: _stop(server)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    url = f"http://127.0.0.1:{port}/?token={token}"
    print(f"Setup page: {url}\nKeep this window open until the page says you are done.", flush=True)
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    server.run()


def build_app(session: Session, token: str, port: int, stop: Any) -> Starlette:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def authorized(request: Request, supplied: str | None) -> bool:
        host = request.headers.get("host", "")
        return host in allowed_hosts and supplied is not None and secrets.compare_digest(supplied, token)

    async def page(request: Request) -> Response:
        if not authorized(request, request.query_params.get("token")):
            return Response("Open the link printed by lrh-m365-setup.", status_code=403)
        html = resources.files("m365_setup").joinpath("page.html").read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    async def state(request: Request) -> Response:
        if not authorized(request, request.headers.get(TOKEN_HEADER)):
            return Response(status_code=403)
        return JSONResponse(session.snapshot(), headers={"Cache-Control": "no-store"})

    async def start(request: Request) -> Response:
        if not authorized(request, request.headers.get(TOKEN_HEADER)):
            return Response(status_code=403)
        body = await request.json()
        clients = body.get("clients", []) if isinstance(body, dict) else None
        if not isinstance(clients, list) or not all(isinstance(key, str) for key in clients):
            return JSONResponse({"error": "clients must be a list of names"}, status_code=400)
        try:
            started = session.start(clients, install=bool(body.get("install", True)))
        except RegistrationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"started": started})

    async def quit_(request: Request) -> Response:
        if not authorized(request, request.headers.get(TOKEN_HEADER)):
            return Response(status_code=403)
        stop()
        return JSONResponse({"stopping": True})

    return Starlette(
        routes=[
            Route("/", page),
            Route("/api/state", state),
            Route("/api/start", start, methods=["POST"]),
            Route("/api/quit", quit_, methods=["POST"]),
        ]
    )


def _stop(server: uvicorn.Server) -> None:
    server.should_exit = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
