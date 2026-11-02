# lrh-m365-setup

One installer for the local Microsoft 365 connectors:

- [Outlook](https://github.com/lucasrhode95/lrh-outlook-connector)
- [Teams](https://github.com/lucasrhode95/lrh-teams-connector)
- [SharePoint and OneDrive](https://github.com/lucasrhode95/lrh-sharepoint-connector)

The installer opens a page in your browser. The page installs the connectors, adds them to your AI apps
and signs you in to Microsoft 365. No Git, Python or administrator rights needed.

## Install

Open PowerShell and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/lucasrhode95/lrh-m365-setup/main/install.ps1 | iex"
```

Or download this repository as a zip, extract it and double-click `install.cmd`.

The script installs [uv](https://docs.astral.sh/uv/) for your user if it is missing, then starts the setup.
Keep the setup window open until the page says you are done.

## What the page does

1. **AI apps.** Lists the apps found on this computer: Claude Desktop, Claude Code, VS Code and Codex.
   Pick the ones to set up.
2. **Connectors.** Installs each connector with `uv tool install` at the version this installer pins.
3. **AI apps.** Adds one MCP server per connector to each app you picked. Each settings file is backed
   up next to itself (`<file>.bak-<date>-<time>`) before it changes. Claude Code is changed through
   `claude mcp add --scope user`.
4. **Sign-in.** Runs the shared sign-in once for all connectors. Each step shows a code, a **Copy code**
   button and an **Open Microsoft sign-in** button. You may be asked up to three times, once per Microsoft
   app the connectors use: Outlook Mobile, One Outlook Web and Microsoft Teams.

Restart your AI apps afterwards so they load the connectors.

The page listens on `127.0.0.1` only, behind a one-time link. It never enters codes or approves
anything for you. Tokens stay in the shared encrypted cache in `%USERPROFILE%\.lrh-m365-auth`.

## Update

Run the installer again. It reinstalls every connector at the pinned version and keeps your sign-in.

## Console mode

Without a browser, run the same steps in the console:

```powershell
.\install.cmd --no-ui
.\install.cmd --no-ui --client claude-code --client vscode
.\install.cmd --no-ui --skip-install
```

`--client` accepts `claude-desktop`, `claude-code`, `vscode` and `codex`. Without it, every app found is set up.

## Already set up from a checkout?

Earlier setups registered each connector with `uv run --directory <checkout>`. The installer names its
entries after each repository, such as `lrh-outlook-connector`. When another entry runs the same
connector, the page flags it. Remove the old entry so your AI app does not show the tools twice.

## Development

```bash
uv sync
uv run lrh-m365-setup            # page
uv run lrh-m365-setup --no-ui    # console
```

To try the bootstrap against a local checkout, set `LRH_M365_SETUP_SOURCE` (and `LRH_M365_AUTH_SOURCE`)
to folder paths before running `install.cmd`.
