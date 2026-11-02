"""The pinned connector set this installer version installs.

Each release of the installer pins exact commits. GitHub archive URLs need no Git on the user's machine.
The connectors' `[tool.uv.sources]` entries are ignored by `uv tool install`, so the shared auth package is
passed to every install explicitly at its own pin.
"""

from __future__ import annotations

from dataclasses import dataclass

GITHUB_OWNER = "lucasrhode95"

AUTH_REPO = "lrh-m365-auth"
AUTH_REF = "fca1fd60c0b6d66e7a99a104b0c99587be584fc5"


@dataclass(frozen=True)
class Connector:
    """One installable connector: its repository, pinned ref, executable and MCP server name."""

    title: str
    repo: str
    ref: str
    executable: str

    @property
    def server_name(self) -> str:
        """The MCP server name registered in every client; the repository name keeps it unique."""
        return self.repo

    @property
    def source(self) -> str:
        return archive_url(self.repo, self.ref)


CONNECTORS: tuple[Connector, ...] = (
    Connector(
        "Outlook", "lrh-outlook-connector", "adb1019f87f5b619bbd6adf1c43539b7be138167", "outlook-connector"
    ),
    Connector("Teams", "lrh-teams-connector", "d1a4bece5b525947d3d41409ea71ae6c36b73daa", "teams-connector"),
    Connector(
        "SharePoint and OneDrive",
        "lrh-sharepoint-connector",
        "d19d474e51141a48b777d80d2219a09115035400",
        "sharepoint-connector",
    ),
)


def auth_requirement() -> str:
    """The `--with` requirement that gives every connector the same pinned auth package."""
    return f"lrh-m365-auth @ {archive_url(AUTH_REPO, AUTH_REF)}"


def archive_url(repo: str, ref: str) -> str:
    return f"https://github.com/{GITHUB_OWNER}/{repo}/archive/{ref}.zip"
