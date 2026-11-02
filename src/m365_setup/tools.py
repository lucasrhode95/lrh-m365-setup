"""Install the pinned connectors as uv tools and locate their executables."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from m365_setup.manifest import Connector, auth_requirement


class InstallError(Exception):
    """A connector could not be installed; the message names the step, never command output secrets."""


def install(connector: Connector, *, uv: Path) -> Path:
    """Install or reinstall one connector at its pinned ref and return its executable path.

    `--reinstall` makes a rerun the update path: a new installer version moves every connector to its new
    pin, and a rerun of the same version repairs a damaged tool environment.
    """
    command = [
        str(uv),
        "tool",
        "install",
        "--reinstall",
        connector.source,
        "--with",
        auth_requirement(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise InstallError(f"uv could not install {connector.title}: {_last_line(completed.stderr)}")
    executable = tool_bin_dir(uv) / exe(connector.executable)
    if not executable.is_file():
        raise InstallError(f"uv installed {connector.title} but {executable.name} was not found.")
    return executable


def find_uv() -> Path:
    """uv from PATH, or the per-user location the bootstrap script installs it to."""
    found = shutil.which("uv")
    if found:
        return Path(found)
    default = Path.home() / ".local" / "bin" / exe("uv")
    if default.is_file():
        return default
    raise InstallError("uv was not found. Run install.cmd, which installs it first.")


def tool_bin_dir(uv: Path) -> Path:
    completed = subprocess.run(
        [str(uv), "tool", "dir", "--bin"], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise InstallError("uv could not report its tool folder.")
    return Path(completed.stdout.strip())


def exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no error output"
