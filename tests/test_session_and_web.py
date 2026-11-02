from __future__ import annotations

from pathlib import Path

from m365_auth import AccessToken, AuthUpstream, BootstrapResult, DeviceCodePrompt
from starlette.testclient import TestClient

from m365_setup import web
from m365_setup.clients import Registration, Server
from m365_setup.manifest import Connector
from m365_setup.session import Session
from m365_setup.tools import InstallError

CONNECTOR = Connector("Example", "lrh-example-connector", "0" * 40, "example-connector")


class FakeProvider:
    """Two profiles: the first asks for a device code, the second settles as scripted."""

    def __init__(self, *, second_ready: bool = True) -> None:
        self.profiles = {"example.one": _Spec(), "example.two": _Spec()}
        self.second_ready = second_ready

    def bootstrap(self, *, prompt, progress) -> tuple[BootstrapResult, ...]:  # noqa: ANN001
        prompt(DeviceCodePrompt("example.one", "CODE123", "https://microsoft.com/devicelogin", "msg", None))
        first = BootstrapResult("example.one", AccessToken("example.one", "token", "cache", None), None)
        progress(first)
        second = (
            BootstrapResult("example.two", AccessToken("example.two", "token", "cache", None), None)
            if self.second_ready
            else BootstrapResult("example.two", None, AuthUpstream("declined"))
        )
        progress(second)
        return (first, second)


class _Spec:
    client_id = "00000000-0000-0000-0000-000000000000"


class FakeClient:
    key = "fake"
    title = "Fake app"

    def __init__(self) -> None:
        self.registered: list[Server] = []

    def detected(self) -> bool:
        return True

    def config_path(self) -> Path:
        return Path("fake.json")

    def register(self, servers):  # noqa: ANN001, ANN201
        self.registered = list(servers)
        return Registration(self.title, Path("fake.json"), None, ("old-example",))


def session(client: FakeClient, provider: FakeProvider, installer=None) -> Session:  # noqa: ANN001
    return Session(
        [client],  # type: ignore[list-item]
        provider=provider,  # type: ignore[arg-type]
        connectors=[CONNECTOR],
        installer=installer or (lambda _connector: Path("C:/tools/bin/example-connector.exe")),
    )


def test_run_installs_registers_and_signs_in() -> None:
    client = FakeClient()
    run = session(client, FakeProvider())
    assert run.start(["fake"])
    run.wait()

    state = run.snapshot()
    assert state["phase"] == "done"
    assert client.registered == [Server("lrh-example-connector", Path("C:/tools/bin/example-connector.exe"))]
    assert state["clients"][0]["duplicates"] == ["old-example"]
    assert [p["state"] for p in state["profiles"]] == ["done", "done"]
    assert state["prompt"] is None


def test_unselected_clients_are_skipped_and_untouched() -> None:
    client = FakeClient()
    run = session(client, FakeProvider())
    run.start([])
    run.wait()

    assert run.snapshot()["clients"][0]["state"] == "skipped"
    assert client.registered == []


def test_failed_profile_fails_closed() -> None:
    run = session(FakeClient(), FakeProvider(second_ready=False))
    run.start(["fake"])
    run.wait()

    state = run.snapshot()
    assert state["phase"] == "failed"
    assert state["profiles"][1]["state"] == "failed"
    assert "AuthUpstream" in state["profiles"][1]["detail"]


def test_install_failure_stops_before_registration() -> None:
    client = FakeClient()

    def broken(_connector: Connector) -> Path:
        raise InstallError("uv could not install Example: network unreachable")

    run = session(client, FakeProvider(), installer=broken)
    run.start(["fake"])
    run.wait()

    assert run.snapshot()["phase"] == "failed"
    assert client.registered == []


def test_api_requires_the_run_token_and_a_loopback_host() -> None:
    run = session(FakeClient(), FakeProvider())
    app = web.build_app(run, "secret-token", 8765, lambda: None)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    assert client.get("/?token=wrong").status_code == 403
    assert client.get("/?token=secret-token").status_code == 200
    assert client.get("/api/state").status_code == 403
    assert client.get("/api/state", headers={web.TOKEN_HEADER: "secret-token"}).json()["phase"] == "choose"

    rebound = TestClient(app, base_url="http://attacker.example:8765")
    assert rebound.get("/api/state", headers={web.TOKEN_HEADER: "secret-token"}).status_code == 403


def test_api_rejects_unknown_clients() -> None:
    run = session(FakeClient(), FakeProvider())
    app = web.build_app(run, "secret-token", 8765, lambda: None)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    response = client.post(
        "/api/start", headers={web.TOKEN_HEADER: "secret-token"}, json={"clients": ["nope"]}
    )
    assert response.status_code == 400
