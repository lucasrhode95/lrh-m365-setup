from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit

from m365_setup.clients import ClaudeDesktop, Codex, RegistrationError, Server, VSCode

SERVERS = [Server("lrh-example-connector", Path("C:/tools/bin/example-connector.exe"))]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    return tmp_path


def test_vscode_keeps_other_servers_backs_up_and_flags_checkout_entries(home: Path) -> None:
    path = home / "Roaming" / "Code" / "User" / "mcp.json"
    path.parent.mkdir(parents=True)
    original = {
        "servers": {
            "other": {"type": "stdio", "command": "other.exe"},
            "old-example": {
                "command": "uv.exe",
                "args": ["run", "--directory", "C:/src", "example-connector", "mcp"],
            },
        },
        "inputs": [],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    registration = VSCode().register(SERVERS)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["inputs"] == []
    assert data["servers"]["other"] == original["servers"]["other"]
    assert data["servers"]["lrh-example-connector"] == {
        "type": "stdio",
        "command": str(SERVERS[0].command),
        "args": ["mcp"],
    }
    assert registration.duplicates == ("old-example",)
    assert registration.backup is not None
    assert json.loads(registration.backup.read_text(encoding="utf-8")) == original


def test_jsonc_settings_are_refused_without_writing(home: Path) -> None:
    path = home / "Roaming" / "Code" / "User" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text('{\n  // my servers\n  "servers": {}\n}\n', encoding="utf-8")

    with pytest.raises(RegistrationError, match="not plain JSON"):
        VSCode().register(SERVERS)

    assert "// my servers" in path.read_text(encoding="utf-8")
    assert list(path.parent.iterdir()) == [path]


def test_claude_desktop_uses_the_packaged_app_folder(home: Path) -> None:
    (home / "Local" / "Packages" / "Claude_example").mkdir(parents=True)
    client = ClaudeDesktop()

    assert client.detected()
    registration = client.register(SERVERS)

    expected = (
        home
        / "Local"
        / "Packages"
        / "Claude_example"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude_desktop_config.json"
    )
    assert registration.config == expected
    assert registration.backup is None
    assert json.loads(expected.read_text(encoding="utf-8"))["mcpServers"]["lrh-example-connector"][
        "args"
    ] == ["mcp"]


def test_claude_desktop_is_not_detected_without_an_install(home: Path) -> None:
    assert not ClaudeDesktop().detected()


def test_codex_preserves_comments_and_other_tables(home: Path) -> None:
    path = home / "codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '# keep me\nmodel = "example"\n\n[mcp_servers.other]\ncommand = "other.exe"\n', encoding="utf-8"
    )

    Codex().register(SERVERS)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# keep me\n")
    document = tomlkit.parse(text)
    servers = document["mcp_servers"]
    assert servers["other"]["command"] == "other.exe"  # type: ignore[index]
    assert servers["lrh-example-connector"]["command"] == str(SERVERS[0].command)  # type: ignore[index]
    assert servers["lrh-example-connector"]["args"] == ["mcp"]  # type: ignore[index]
