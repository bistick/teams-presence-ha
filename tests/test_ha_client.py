import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from teams_presence.ha_client import HAError, HAErrorKind, HomeAssistantClient


@dataclass
class Recorded:
    method: str
    path: str
    headers: Message
    body: bytes


@dataclass
class FakeHA:
    status: int = 200
    body: bytes = b'{"message": "API running."}'
    delay: float = 0.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)


@pytest.fixture
def fake_ha() -> Iterator[tuple[FakeHA, str]]:
    state = FakeHA()

    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            state.requests.append(Recorded(self.command, self.path, self.headers, body))
            time.sleep(state.delay)
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(state.body)))
            for name, value in state.extra_headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(state.body)

        do_GET = _handle
        do_POST = _handle

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def client(url: str, timeout: float = 5.0) -> HomeAssistantClient:
    return HomeAssistantClient(url, "secret", "sensor.teams_status", timeout=timeout)


@pytest.mark.parametrize("status", [200, 201])
def test_publish_posts_state(fake_ha: tuple[FakeHA, str], status: int) -> None:
    ha, url = fake_ha
    ha.status = status
    client(url + "/").publish("busy", {"teams_availability": "Busy"})
    request = ha.requests[0]
    assert request.method == "POST"
    assert request.path == "/api/states/sensor.teams_status"
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.body) == {
        "state": "busy",
        "attributes": {"teams_availability": "Busy"},
    }


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, HAErrorKind.UNAUTHORIZED),
        (403, HAErrorKind.UNAUTHORIZED),
        (404, HAErrorKind.HTTP),
        (500, HAErrorKind.HTTP),
    ],
)
def test_http_errors(fake_ha: tuple[FakeHA, str], status: int, kind: HAErrorKind) -> None:
    ha, url = fake_ha
    ha.status = status
    with pytest.raises(HAError) as info:
        client(url).publish("busy", {})
    assert info.value.kind is kind
    assert info.value.status == status


def test_timeout_is_unreachable(fake_ha: tuple[FakeHA, str]) -> None:
    ha, url = fake_ha
    ha.delay = 0.5
    with pytest.raises(HAError) as info:
        client(url, timeout=0.1).publish("busy", {})
    assert info.value.kind is HAErrorKind.UNREACHABLE


def test_connection_refused_is_unreachable() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(HAError) as info:
        client(f"http://127.0.0.1:{port}").publish("busy", {})
    assert info.value.kind is HAErrorKind.UNREACHABLE


def test_check_accepts_api_running(fake_ha: tuple[FakeHA, str]) -> None:
    ha, url = fake_ha
    client(url).check()
    assert (ha.requests[0].method, ha.requests[0].path) == ("GET", "/api/")


def test_check_rejects_unexpected_body(fake_ha: tuple[FakeHA, str]) -> None:
    ha, url = fake_ha
    ha.body = b"<html></html>"
    with pytest.raises(HAError) as info:
        client(url).check()
    assert info.value.kind is HAErrorKind.HTTP


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_not_followed(fake_ha: tuple[FakeHA, str], status: int) -> None:
    ha, url = fake_ha
    ha.status = status
    ha.extra_headers = {"Location": "http://elsewhere.invalid/api/states/x"}
    with pytest.raises(HAError) as info:
        client(url).publish("busy", {})
    assert info.value.kind is HAErrorKind.HTTP
    assert info.value.status == status
    assert len(ha.requests) == 1


def test_non_http_reply_is_unreachable() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def reply_garbage() -> None:
        connection, _ = listener.accept()
        connection.recv(65536)
        connection.sendall(b"this is not http\r\n\r\n")
        connection.close()

    threading.Thread(target=reply_garbage, daemon=True).start()
    try:
        with pytest.raises(HAError) as info:
            client(f"http://127.0.0.1:{listener.getsockname()[1]}").publish("busy", {})
    finally:
        listener.close()
    assert info.value.kind is HAErrorKind.UNREACHABLE


def test_malformed_token_error_does_not_leak_it(fake_ha: tuple[FakeHA, str]) -> None:
    _, url = fake_ha
    leaky = HomeAssistantClient(url, "abc\nSECRETPART", "sensor.teams_status")
    with pytest.raises(HAError) as info:
        leaky.publish("busy", {})
    assert "SECRETPART" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_repr_does_not_leak_token() -> None:
    assert "secret" not in repr(client("http://ha.local:8123"))
