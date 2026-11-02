"""One setup run: install, register, then sign in, with a state snapshot both front ends render.

The run happens on one worker thread. The web page polls `snapshot()`; the CLI prints from the same
callbacks. Device codes are only shown to the person; they are never logged or written to disk.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from m365_auth import AuthError, BootstrapResult, DeviceCodePrompt, TokenProvider
from m365_auth.profiles import (
    MICROSOFT_OFFICE_CLIENT_ID,
    ONE_OUTLOOK_WEB_CLIENT_ID,
    OUTLOOK_MOBILE_CLIENT_ID,
    TEAMS_CLIENT_ID,
)

from m365_setup import tools
from m365_setup.clients import Client, RegistrationError, Server
from m365_setup.manifest import CONNECTORS, Connector

_log = logging.getLogger(__name__)

# The Microsoft app name a person sees on the approval page for each first-party client.
APP_NAMES = {
    OUTLOOK_MOBILE_CLIENT_ID: "Outlook Mobile",
    ONE_OUTLOOK_WEB_CLIENT_ID: "One Outlook Web",
    TEAMS_CLIENT_ID: "Microsoft Teams",
    MICROSOFT_OFFICE_CLIENT_ID: "Microsoft Office",
}


@dataclass
class _Step:
    title: str
    state: str = "waiting"
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, key: str) -> dict[str, Any]:
        return {"key": key, "title": self.title, "state": self.state, "detail": self.detail, **self.extra}


class Session:
    """The state of one installer run. All mutations hold the lock; readers get copies."""

    def __init__(
        self,
        clients: Sequence[Client],
        *,
        provider: TokenProvider | None = None,
        connectors: Sequence[Connector] = CONNECTORS,
        installer: Callable[[Connector], Any] | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._clients = {client.key: client for client in clients}
        self._provider = provider or TokenProvider(login_command="lrh-m365-setup")
        self._connectors = tuple(connectors)
        self._installer = installer
        self._on_change = on_change
        self.phase = "choose"
        self.message = ""
        self.connector_steps = {c.repo: _Step(c.title) for c in self._connectors}
        self.client_steps = {
            c.key: _Step(c.title, extra={"detected": c.detected(), "config": str(c.config_path())})
            for c in clients
        }
        self.profile_steps = {
            name: _Step(name, extra={"app": APP_NAMES.get(spec.client_id, "Microsoft 365")})
            for name, spec in self._provider.profiles.items()
        }
        self.prompt: dict[str, Any] | None = None
        self._executables: dict[str, str] = {}
        self._worker: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "phase": self.phase,
                "message": self.message,
                "connectors": [step.as_dict(key) for key, step in self.connector_steps.items()],
                "clients": [step.as_dict(key) for key, step in self.client_steps.items()],
                "profiles": [step.as_dict(key) for key, step in self.profile_steps.items()],
                "prompt": dict(self.prompt) if self.prompt else None,
            }

    def start(self, client_keys: Sequence[str], *, install: bool = True) -> bool:
        """Start the run on a worker thread; False when one is already running.

        `client_keys` is validated here against the clients this session was built with.
        """
        unknown = [key for key in client_keys if key not in self._clients]
        if unknown:
            raise RegistrationError(f"Unknown clients: {', '.join(unknown)}")
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return False
            self._worker = threading.Thread(
                target=self._run, args=(tuple(client_keys), install), name="lrh-m365-setup", daemon=True
            )
            self._worker.start()
            return True

    def wait(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.join()

    def _run(self, client_keys: tuple[str, ...], install: bool) -> None:
        try:
            if install:
                self._install_connectors()
            self._register(client_keys)
            self._sign_in()
        except _Stop:
            return
        except Exception:  # the worker must always settle the page's state
            _log.exception("Setup stopped unexpectedly")
            self._set(phase="failed", message="Setup stopped unexpectedly. See the console for details.")

    def _install_connectors(self) -> None:
        self._set(phase="installing", message="Installing the connectors.")
        installer = self._installer or _uv_installer()
        for connector in self._connectors:
            self._step(self.connector_steps[connector.repo], "working")
            try:
                executable = installer(connector)
            except tools.InstallError as exc:
                self._step(self.connector_steps[connector.repo], "failed", str(exc))
                return self._fail(str(exc))
            self._executables[connector.repo] = str(executable)
            self._step(self.connector_steps[connector.repo], "done", str(executable))

    def _register(self, client_keys: tuple[str, ...]) -> None:
        for key, step in self.client_steps.items():
            if key not in client_keys:
                self._step(step, "skipped")
        if not client_keys:
            return
        self._set(phase="registering", message="Adding the connectors to your AI apps.")
        servers = self._servers()
        failed = False
        for key in client_keys:
            step = self.client_steps[key]
            self._step(step, "working")
            try:
                registration = self._clients[key].register(servers)
            except (RegistrationError, OSError) as exc:
                self._step(step, "failed", str(exc))
                failed = True
                continue
            with self._lock:
                step.extra["backup"] = str(registration.backup) if registration.backup else ""
                step.extra["duplicates"] = list(registration.duplicates)
            self._step(step, "done", str(registration.config))
        if failed:
            self._fail("Some apps could not be updated. Their settings were left as they were.")

    def _servers(self) -> list[Server]:
        servers = []
        for connector in self._connectors:
            executable = self._executables.get(connector.repo)
            if executable is None:
                uv = tools.find_uv()
                executable = str(tools.tool_bin_dir(uv) / tools.exe(connector.executable))
            servers.append(Server(connector.server_name, Path(executable)))
        return servers

    def _sign_in(self) -> None:
        self._set(phase="signing_in", message="Signing in to Microsoft 365.")
        names = list(self.profile_steps)
        if names:
            self._step(self.profile_steps[names[0]], "working")

        def prompt(code: DeviceCodePrompt) -> None:
            app = self.profile_steps[code.profile].extra.get("app", "")
            with self._lock:
                self.profile_steps[code.profile].state = "code"
                self.prompt = {
                    "profile": code.profile,
                    "app": app,
                    "user_code": code.user_code,
                    "verification_uri": code.verification_uri,
                    "expires_at": code.expires_at,
                }
            self._changed()

        def progress(result: BootstrapResult) -> None:
            with self._lock:
                step = self.profile_steps[result.profile]
                step.state = "done" if result.ready else "failed"
                step.detail = "" if result.ready else _error_text(result.error)
                if self.prompt and self.prompt["profile"] == result.profile:
                    self.prompt = None
                following = names.index(result.profile) + 1
                if following < len(names):
                    self.profile_steps[names[following]].state = "working"
            self._changed()

        try:
            results = self._provider.bootstrap(prompt=prompt, progress=progress)
        except AuthError as exc:
            return self._fail(_error_text(exc))
        if all(result.ready for result in results):
            self._set(phase="done", message="All set. Restart your AI apps so they load the connectors.")
        else:
            self._fail("Sign-in did not finish. Nothing was approved on your behalf; try again when ready.")

    def _step(self, step: _Step, state: str, detail: str = "") -> None:
        with self._lock:
            step.state = state
            step.detail = detail
        self._changed()

    def _set(self, *, phase: str, message: str) -> None:
        with self._lock:
            self.phase = phase
            self.message = message
        self._changed()

    def _fail(self, message: str) -> NoReturn:
        with self._lock:
            self.phase = "failed"
            self.message = message
            self.prompt = None
        self._changed()
        raise _Stop

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


class _Stop(Exception):
    """Ends the run after its failure has been recorded in the state."""


def _uv_installer() -> Callable[[Connector], Any]:
    uv = tools.find_uv()
    return lambda connector: tools.install(connector, uv=uv)


def _error_text(error: BaseException | None) -> str:
    """Auth errors carry operator guidance and never token values; show their class and message."""
    if error is None:
        return ""
    return f"{type(error).__name__}: {error}"
