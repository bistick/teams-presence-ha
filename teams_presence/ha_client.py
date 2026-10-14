"""Minimal Home Assistant REST client for publishing one sensor state."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from email.message import Message
from enum import Enum
from typing import IO

DEFAULT_TIMEOUT_SECONDS = 5.0


class HAErrorKind(Enum):
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    HTTP = "http"
    NOT_CONFIGURED = "not_configured"


class HAError(Exception):
    def __init__(self, kind: HAErrorKind, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        entity_id: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._token = token
        self._entity_id = entity_id
        self._timeout = timeout
        # Home Assistant lives on the local network: never route it through an HTTP proxy.
        # Redirects are refused: urllib would turn the POST into a GET and forward the token.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirectHandler()
        )

    def __repr__(self) -> str:
        return f"HomeAssistantClient({self._base_url!r}, entity_id={self._entity_id!r})"

    def publish(
        self, state: str, attributes: Mapping[str, object], timeout: float | None = None
    ) -> None:
        body = json.dumps({"state": state, "attributes": dict(attributes)}).encode("utf-8")
        self._request("POST", f"/api/states/{self._entity_id}", body, timeout)

    def check(self) -> None:
        """Raise ``HAError`` unless ``GET /api/`` answers ``API running.``."""
        raw = self._request("GET", "/api/", None, None)
        try:
            message = json.loads(raw).get("message")
        except (ValueError, AttributeError) as exc:
            raise HAError(HAErrorKind.HTTP, "unexpected response from /api/") from exc
        if message != "API running.":
            raise HAError(HAErrorKind.HTTP, "unexpected response from /api/")

    def _request(self, method: str, path: str, body: bytes | None, timeout: float | None) -> bytes:
        request = urllib.request.Request(
            self._base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=timeout or self._timeout) as response:
                data: bytes = response.read()
                return data
        except urllib.error.HTTPError as exc:
            kind = HAErrorKind.UNAUTHORIZED if exc.code in (401, 403) else HAErrorKind.HTTP
            raise HAError(kind, f"HTTP {exc.code}", exc.code) from exc
        except (urllib.error.URLError, OSError) as exc:  # TimeoutError is an OSError
            raise HAError(HAErrorKind.UNREACHABLE, str(exc)) from exc
        except http.client.HTTPException as exc:  # e.g. a non-HTTP reply or an invalid URL
            raise HAError(HAErrorKind.UNREACHABLE, type(exc).__name__) from exc
        except ValueError:
            # http.client rejects invalid header values with a message quoting them,
            # which would include the token: drop the original exception entirely.
            raise HAError(HAErrorKind.HTTP, "invalid request (check URL and token)") from None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None
