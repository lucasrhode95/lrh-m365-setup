"""Register the installed connectors as MCP servers in the agent clients found on this machine.

Every client keeps its own format: Claude Desktop and VS Code use JSON files, Codex uses TOML and Claude
Code is changed through its own CLI. Each file is backed up before the first change of a run. Entries with
other names are never touched; entries elsewhere that run the same connector are reported as duplicates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError


@dataclass(frozen=True)
class Server:
    """One MCP server entry: the stdio command that starts an installed connector."""

    name: str
    command: Path
    args: tuple[str, ...] = ("mcp",)


@dataclass(frozen=True)
class Registration:
    client: str
    config: Path
    backup: Path | None
    duplicates: tuple[str, ...] = field(default_factory=tuple)


class RegistrationError(Exception):
    """A client's configuration could not be changed safely; nothing was written for it."""


@dataclass(frozen=True)
class ClaudeDesktop:
    key = "claude-desktop"
    title = "Claude Desktop"

    def detected(self) -> bool:
        return _claude_desktop_config() is not None

    def config_path(self) -> Path:
        path = _claude_desktop_config()
        if path is None:
            raise RegistrationError("Claude Desktop was not found.")
        return path

    def register(self, servers: Sequence[Server]) -> Registration:
        path = self.config_path()
        data = _read_json(path)
        entries = _json_table(data, "mcpServers", path)
        duplicates = _duplicates(_json_commands(entries), servers)
        for server in servers:
            entries[server.name] = {"command": str(server.command), "args": list(server.args)}
        backup = _write_text(path, json.dumps(data, indent=2) + "\n")
        return Registration(self.title, path, backup, duplicates)


@dataclass(frozen=True)
class VSCode:
    key = "vscode"
    title = "VS Code"

    def detected(self) -> bool:
        return self.config_path().parent.is_dir()

    def config_path(self) -> Path:
        return _appdata() / "Code" / "User" / "mcp.json"

    def register(self, servers: Sequence[Server]) -> Registration:
        path = self.config_path()
        data = _read_json(path)
        entries = _json_table(data, "servers", path)
        duplicates = _duplicates(_json_commands(entries), servers)
        for server in servers:
            entries[server.name] = {
                "type": "stdio",
                "command": str(server.command),
                "args": list(server.args),
            }
        backup = _write_text(path, json.dumps(data, indent=2) + "\n")
        return Registration(self.title, path, backup, duplicates)


@dataclass(frozen=True)
class Codex:
    key = "codex"
    title = "Codex"

    def detected(self) -> bool:
        return self.config_path().parent.is_dir() or shutil.which("codex") is not None

    def config_path(self) -> Path:
        home = os.environ.get("CODEX_HOME")
        return (Path(home) if home else Path.home() / ".codex") / "config.toml"

    def register(self, servers: Sequence[Server]) -> Registration:
        path = self.config_path()
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        try:
            document = tomlkit.parse(text)
        except ParseError as exc:
            raise RegistrationError(f"{path} is not valid TOML ({exc}); fix it, then rerun.") from None
        if "mcp_servers" not in document:
            document["mcp_servers"] = tomlkit.table(is_super_table=True)
        entries = document["mcp_servers"]
        if not isinstance(entries, Mapping):
            raise RegistrationError(f"{path} has an mcp_servers value that is not a table.")
        duplicates = _duplicates(_json_commands(entries), servers)
        for server in servers:
            table = tomlkit.table()
            table["command"] = str(server.command)
            table["args"] = list(server.args)
            entries[server.name] = table  # type: ignore[index]  # tomlkit tables are mutable mappings
        backup = _write_text(path, tomlkit.dumps(document))
        return Registration(self.title, path, backup, duplicates)


@dataclass(frozen=True)
class ClaudeCode:
    key = "claude-code"
    title = "Claude Code"

    def detected(self) -> bool:
        return shutil.which("claude") is not None

    def config_path(self) -> Path:
        root = os.environ.get("CLAUDE_CONFIG_DIR")
        return (Path(root) if root else Path.home()) / ".claude.json"

    def register(self, servers: Sequence[Server]) -> Registration:
        """Use `claude mcp` so Claude Code's own writer owns its busy settings file."""
        claude = shutil.which("claude")
        if claude is None:
            raise RegistrationError("The claude command was not found.")
        path = self.config_path()
        existing = _read_json(path) if path.is_file() else {}
        user_entries = existing.get("mcpServers", {}) if isinstance(existing, dict) else {}
        duplicates = _duplicates(
            _json_commands(user_entries if isinstance(user_entries, dict) else {}), servers
        )
        backup = _backup(path)
        for server in servers:
            _run([claude, "mcp", "remove", "--scope", "user", server.name], check=False)
            _run(
                [claude, "mcp", "add", "--scope", "user", "--transport", "stdio", server.name, "--"]
                + [str(server.command), *server.args],
                check=True,
            )
        return Registration(self.title, path, backup, duplicates)


Client = ClaudeDesktop | VSCode | Codex | ClaudeCode
CLIENTS: tuple[Client, ...] = (ClaudeDesktop(), ClaudeCode(), VSCode(), Codex())


def client_by_key(key: str) -> Client:
    for client in CLIENTS:
        if client.key == key:
            return client
    raise RegistrationError(f"Unknown client '{key}'.")


def _claude_desktop_config() -> Path | None:
    """The config file Claude Desktop reads: the MSIX package's redirected folder when packaged."""
    packages = _localappdata() / "Packages"
    if packages.is_dir():
        for package in sorted(packages.glob("Claude_*")):
            return package / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    roaming = _appdata() / "Claude"
    if roaming.is_dir() or (_localappdata() / "AnthropicClaude").is_dir():
        return roaming / "claude_desktop_config.json"
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RegistrationError(
            f"{path} is not plain JSON (it may have comments); add the servers by hand or remove them."
        ) from None
    if not isinstance(data, dict):
        raise RegistrationError(f"{path} does not hold a JSON object.")
    return data


def _json_table(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    table = data.setdefault(key, {})
    if not isinstance(table, dict):
        raise RegistrationError(f"{path} has a '{key}' value that is not an object.")
    return table


def _json_commands(entries: Mapping[str, Any]) -> dict[str, str]:
    """Each entry's command line as one string, for duplicate detection only."""
    commands: dict[str, str] = {}
    for name, entry in entries.items():
        if isinstance(entry, Mapping):
            args = entry.get("args", [])
            parts = [str(entry.get("command", ""))] + (
                [str(arg) for arg in args] if isinstance(args, list) else []
            )
            commands[str(name)] = " ".join(parts)
    return commands


def _duplicates(commands: Mapping[str, str], servers: Sequence[Server]) -> tuple[str, ...]:
    """Other entries that start one of the same connectors, such as an earlier checkout-based setup."""
    names = {server.name for server in servers}
    executables = {server.command.stem.lower() for server in servers}
    return tuple(
        sorted(
            name
            for name, command in commands.items()
            if name not in names and any(executable in command.lower() for executable in executables)
        )
    )


def _write_text(path: Path, text: str) -> Path | None:
    backup = _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".lrh-m365-setup.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return backup


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    return backup


def _run(command: list[str], *, check: bool) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and completed.returncode != 0:
        lines = [line for line in (completed.stderr or completed.stdout).splitlines() if line.strip()]
        raise RegistrationError(f"`claude mcp add` failed: {lines[-1] if lines else 'no output'}")


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
